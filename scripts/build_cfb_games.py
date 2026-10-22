"""Build the FBS halftime table from the cfbfastR play-by-play files, the schedules and the CFBD lines file.

One row per game: season, week, date, teams, the halftime score, the final, the closing total and the home
spread (minus = home favored). The final (overtime included, since a full-game total settles on it) comes from
the schedule file; the halftime score is read off the play by play, and a game is kept only when the play by
play's own final agrees with the schedule, which proves its scores are complete and in order.

Sources (sportsdataverse/cfbfastR-data on GitHub, free):
  cfb/pbp/parquet/play_by_play_YYYY.parquet   ESPN play by play, 2004 on, with the running score and period
  schedules/parquet/cfb_schedules_YYYY.parquet  finals and divisions (fbs/fcs)
  betting/csv/cfb_line_odds.csv.gz              CFBD lines by book, 2006 on: the total is Pinnacle's close
                                                when it has one, otherwise the median close across books;
                                                the spread the same way, from the home team's side

The play by play needs care. Row order is unreliable before 2014 (game_play_number runs backwards in some
seasons, sequenceNumber is scrambled within a half in others) and ESPN drops stray 0-0 score rows mid game.
So the halftime score is read two ways that need no order: the largest running score over the plays of
periods 1 and 2 (right because a score never goes down) and the lowest score carried by a third-period play
(the kickoff). The game is kept only when the two agree.

Usage: python scripts/build_cfb_games.py LINES.csv.gz PBP_DIR SCHED_DIR data/cfb_games.csv
       (PBP_DIR holds pbp_YYYY.parquet, SCHED_DIR holds cfb_schedules_YYYY.parquet)
"""
import os, sys, glob, statistics
import pandas as pd
import pyarrow.parquet as pq

COLS = ['id', 'game_id', 'game_play_number', 'sequenceNumber', 'season', 'period', 'homeScore', 'awayScore', 'end.homeScore', 'end.awayScore',
        'homeTeamName', 'awayTeamName', 'homeTeamAbbrev', 'awayTeamAbbrev', 'homeTeamSpread']


def lines(path):
    """game_id -> (total, spread rows) from the closing lines, Pinnacle first, else the median across books."""
    o = pd.read_csv(path, low_memory=False)
    o = o[o['game_id'].notna() & o['lines'].notna()]
    o['game_id'] = o['game_id'].astype(int)
    out = {}
    for gid, g in o.groupby('game_id'):
        t = g[g.market_type == 'total']
        s = g[g.market_type == 'spread']
        total = spread = None
        if len(t):
            p = t[t.book.str.upper().str.contains('PINNACLE', na=False)]
            total = float(p['lines'].iloc[0]) if len(p) else float(statistics.median(t['lines'].astype(float)))
        if len(s):
            # the spread rows carry the team abbreviation; the home side is whichever row names the home team,
            # which the pbp knows. Keep every (abbr, line, book) here and let the pbp pick the home one.
            spread = [(str(a), float(l), str(b)) for a, l, b in zip(s['abbr'], s['lines'], s['book'])]
        out[gid] = (total, spread)
    return out


def home_spread(rows, home_abbr, away_abbr):
    """The home team's closing spread (minus = home favored), Pinnacle first, else the median across books."""
    if not rows:
        return None
    mine = [(l, b) for a, l, b in rows if a == home_abbr]
    theirs = [(-l, b) for a, l, b in rows if a == away_abbr]
    cands = mine + theirs
    if not cands:
        return None
    p = [l for l, b in cands if 'PINNACLE' in b.upper()]
    return p[0] if p else float(statistics.median(l for l, b in cands))


def schedule(path):
    """game_id -> final and divisions from the schedule file."""
    t = pq.read_table(path, columns=['game_id', 'season', 'week', 'season_type', 'start_date', 'home_team', 'away_team',
                                     'home_points', 'away_points', 'home_division', 'away_division', 'neutral_site']).to_pandas()
    t = t[t.home_points.notna() & t.away_points.notna()]
    return {int(r.game_id): r for r in t.itertuples()}


def season_games(path):
    """Per game: the halftime score off the play by play, plus the play by play's own final for the check."""
    names = pq.ParquetFile(path).schema_arrow.names
    t = pq.read_table(path, columns=[c for c in COLS if c in names]).to_pandas()
    t = t[t['game_id'].notna() & t['period'].notna()].copy()
    t['game_id'] = pd.to_numeric(t['game_id'], errors='coerce')
    t['period'] = pd.to_numeric(t['period'], errors='coerce')
    t = t[t['game_id'].notna() & t['period'].notna()]
    t['game_id'] = t['game_id'].astype(int)
    t['period'] = t['period'].astype(int)
    hs = t['end.homeScore'] if 'end.homeScore' in t else t['homeScore']
    as_ = t['end.awayScore'] if 'end.awayScore' in t else t['awayScore']
    t = t.assign(hs=hs.fillna(t['homeScore']), as_=as_.fillna(t['awayScore']))
    t = t[t['hs'].notna() & t['as_'].notna()]
    for key in ('sequenceNumber', 'game_play_number', 'id'):
        if key in t and t[key].notna().any():
            t['ord'] = pd.to_numeric(t[key], errors='coerce').fillna(0)
            break
    else:
        t['ord'] = range(len(t))
    out = []
    for gid, g in t.groupby('game_id'):
        g = g.sort_values('ord', kind='mergesort')
        periods = set(g.period)
        if not {1, 2, 3, 4} <= periods:
            continue                                   # a period is missing from the record
        first = g[g.period <= 2]
        h1h, h1a = int(first['hs'].max()), int(first['as_'].max())
        # the same score read the other way: the lowest score carried by a third-period play (the kickoff), skipping
        # the stray 0-0 rows unless the half really was 0-0. The two must agree or the game is dropped.
        third = g[g.period == 3]
        if h1h + h1a > 0:
            third = third[(third['hs'] + third['as_']) > 0]
        if third.empty:
            continue
        q3 = third.iloc[(third['hs'] + third['as_']).values.argmin()]
        r = g.iloc[0]
        out.append(dict(game_id=gid, season=int(r['season']),
                        home=r['homeTeamName'], away=r['awayTeamName'], home_abbr=r.get('homeTeamAbbrev'), away_abbr=r.get('awayTeamAbbrev'),
                        h1h=h1h, h1a=h1a, half_agrees=int(q3['hs'] == h1h and q3['as_'] == h1a),
                        pbp_fh=int(g['hs'].max()), pbp_fa=int(g['as_'].max()), ot=int(max(periods) > 4),
                        pbp_home_spread=float(r['homeTeamSpread']) if pd.notna(r.get('homeTeamSpread')) else None))
    return out


def main(lines_path, pbp_dir, sched_dir, dst):
    L = lines(lines_path)
    rows = []
    for path in sorted(glob.glob(os.path.join(pbp_dir, 'pbp_*.parquet'))):
        season = int(os.path.basename(path)[4:8])
        S = schedule(os.path.join(sched_dir, f'cfb_schedules_{season}.parquet'))
        games = season_games(path)
        kept = nolines = mismatch = half_off = 0
        for g in games:
            s = S.get(g['game_id'])
            if s is None or int(s.home_points) != g['pbp_fh'] or int(s.away_points) != g['pbp_fa']:
                mismatch += 1                          # the play by play does not reach the schedule's final
                continue
            if not g['half_agrees']:
                half_off += 1                          # the two halftime reads disagree
                continue
            total, sp = L.get(g['game_id'], (None, None))
            hs = home_spread(sp, g['home_abbr'], g['away_abbr']) if total is not None else None
            if hs is None:
                hs = g['pbp_home_spread'] if total is not None else None
            if total is None or hs is None:
                nolines += 1
                continue
            g.update(season_type=s.season_type, week=int(s.week), date=str(s.start_date)[:10], fh=int(s.home_points), fa=int(s.away_points),
                     home_div=s.home_division, away_div=s.away_division, neutral=int(bool(s.neutral_site)), total=total, home_spread=hs)
            rows.append(g)
            kept += 1
        print(f"{season}: {len(games)} games with four periods, {mismatch} dropped (play by play final differs from the schedule), "
              f"{half_off} dropped (the two halftime reads disagree), {nolines} without a closing total and spread, {kept} kept")
    cols = ['game_id', 'season', 'season_type', 'week', 'date', 'away', 'home', 'away_abbr', 'home_abbr', 'away_div', 'home_div', 'neutral',
            'h1a', 'h1h', 'fa', 'fh', 'ot', 'total', 'home_spread']
    pd.DataFrame(rows)[cols].sort_values(['season', 'date', 'game_id']).to_csv(dst, index=False)
    print(len(rows), 'games written to', dst)


if __name__ == '__main__':
    main(*sys.argv[1:5])
