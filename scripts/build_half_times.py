"""The halftime timetable for the Odds API history pull: when each game's break started and ended, on the wall
clock, next to the numbers the model needs (closing total and spread, halftime score, final).

NFL: the nflverse play by play carries time_of_day (UTC) on most plays. The break starts at the last timed play
of the first half and ends at the first of the second; the 2H line is read inside it (scripts/odds_history.py).
Games with no clock on either side of the break are left out. Team names are mapped to the full names the Odds
API uses.

Usage: python scripts/build_half_times.py nfl PBP_DIR data/nfl_games.csv data/half_times_nfl.csv [--since 2023]
       python scripts/build_half_times.py cfb PBP_DIR data/cfb_games.csv data/half_times_cfb.csv
       python scripts/build_half_times.py nba PBP_DIR data/nba_games.csv data/half_times_nba.csv --since 2024   (hoopR files, season = year it ends)
"""
import os, sys, glob, argparse
import pandas as pd
import pyarrow.parquet as pq

NFL_NAMES = {'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers',
             'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos',
             'DET': 'Detroit Lions', 'GB': 'Green Bay Packers', 'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
             'KC': 'Kansas City Chiefs', 'LA': 'Los Angeles Rams', 'LAR': 'Los Angeles Rams', 'LAC': 'Los Angeles Chargers', 'LV': 'Las Vegas Raiders',
             'OAK': 'Oakland Raiders', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints',
             'NYG': 'New York Giants', 'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks',
             'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders', 'SD': 'San Diego Chargers',
             'STL': 'St. Louis Rams'}


def nfl_half_times(pbp_dir, since):
    out = {}
    for path in sorted(glob.glob(os.path.join(pbp_dir, 'pbp_*.parquet'))):
        season = int(os.path.basename(path)[4:8])
        if season < since:
            continue
        names = pq.ParquetFile(path).schema_arrow.names
        if 'time_of_day' not in names:
            print(f'{os.path.basename(path)}: no time_of_day column, skipped')
            continue
        t = pq.read_table(path, columns=['game_id', 'play_id', 'qtr', 'game_half', 'time_of_day', 'desc']).to_pandas()
        t = t[t.time_of_day.notna() & t.qtr.notna()]
        kept = 0
        for gid, g in t.groupby('game_id'):
            g = g.sort_values('play_id')
            h1 = g[(g.game_half == 'Half1') & (g.qtr == 2)]
            h2 = g[(g.game_half == 'Half2') & (g.qtr == 3)]
            if h1.empty or h2.empty:
                continue
            half, q3 = str(h1.time_of_day.iloc[-1]), str(h2.time_of_day.iloc[0])
            kick = str(g.time_of_day.iloc[0])
            try:
                gap = (pd.Timestamp(q3) - pd.Timestamp(half)).total_seconds()
            except Exception:
                continue
            if not 5 * 60 <= gap <= 45 * 60:
                continue                                   # a clock glitch, or a stoppage that was not the break
            out[gid] = dict(kick_utc=kick, half_utc=half, q3_utc=q3, break_s=int(gap))
            kept += 1
        print(f'{os.path.basename(path)}: {kept} games with a clocked halftime')
    return out


def cfb_half_times(pbp_dir, since):
    """CFB from the cfbfastR (ESPN) files: wallclock on nearly every play. Row order is unreliable, so the break
    starts at the latest wallclock among the plays of periods 1-2 and ends at the earliest among period 3."""
    out = {}
    for path in sorted(glob.glob(os.path.join(pbp_dir, 'pbp_*.parquet'))):
        season = int(os.path.basename(path)[4:8])
        if season < since:
            continue
        names = pq.ParquetFile(path).schema_arrow.names
        if 'wallclock' not in names:
            print(f'{os.path.basename(path)}: no wallclock column, skipped')
            continue
        t = pq.read_table(path, columns=['game_id', 'period', 'wallclock']).to_pandas()
        t = t[t.game_id.notna() & t.period.notna() & t.wallclock.notna()]
        t['game_id'] = pd.to_numeric(t.game_id, errors='coerce')
        t = t[t.game_id.notna()]
        t['game_id'] = t.game_id.astype(int)
        t['period'] = pd.to_numeric(t.period, errors='coerce')
        t['ts'] = pd.to_datetime(t.wallclock, errors='coerce', utc=True)
        t = t[t.ts.notna()]
        kept = 0
        for gid, g in t.groupby('game_id'):
            first, third = g[g.period <= 2], g[g.period == 3]
            if first.empty or third.empty:
                continue
            half, q3, kick = first.ts.max(), third.ts.min(), g.ts.min()
            gap = (q3 - half).total_seconds()
            if not 5 * 60 <= gap <= 45 * 60:
                continue
            if not 40 * 60 <= (half - kick).total_seconds() <= 3 * 3600:
                kick = half - pd.Timedelta(minutes=95)      # a placeholder clock on the first plays; a first half runs about 95 minutes
            fmt = lambda x: x.strftime('%Y-%m-%dT%H:%M:%SZ')
            out[gid] = dict(kick_utc=fmt(kick), half_utc=fmt(half), q3_utc=fmt(q3), break_s=int(gap))
            kept += 1
        print(f'{os.path.basename(path)}: {kept} games with a clocked halftime')
    return out


NBA_NAMES = {'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BKN': 'Brooklyn Nets', 'CHA': 'Charlotte Hornets', 'CHI': 'Chicago Bulls',
             'CLE': 'Cleveland Cavaliers', 'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets', 'DET': 'Detroit Pistons', 'GS': 'Golden State Warriors',
             'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers', 'LAC': 'Los Angeles Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies',
             'MIA': 'Miami Heat', 'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves', 'NO': 'New Orleans Pelicans', 'NY': 'New York Knicks',
             'OKC': 'Oklahoma City Thunder', 'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns', 'POR': 'Portland Trail Blazers',
             'SAC': 'Sacramento Kings', 'SA': 'San Antonio Spurs', 'TOR': 'Toronto Raptors', 'UTAH': 'Utah Jazz', 'WSH': 'Washington Wizards'}


def nba_half_times(pbp_dir, since):
    """NBA from the hoopR (ESPN) files: wallclock on every play. Keyed by (ET date, home final, away final) so the
    SBR-lineage game table (data/nba_games.csv) matches without a team-name map; the full names come from the
    ESPN abbreviations. The hoopR season number is the year the season ends, like the game table's."""
    out = {}
    for path in sorted(glob.glob(os.path.join(pbp_dir, 'pbp_*.parquet'))):
        season = int(os.path.basename(path)[4:8])
        if season < since:
            continue
        cols = ['game_id', 'game_date', 'period_number', 'wallclock', 'home_team_abbrev', 'away_team_abbrev', 'home_score', 'away_score', 'season_type']
        t = pq.read_table(path, columns=cols).to_pandas()
        t = t[t.game_id.notna() & t.period_number.notna() & t.wallclock.notna()]
        t['ts'] = pd.to_datetime(t.wallclock, errors='coerce', utc=True)
        t = t[t.ts.notna()]
        kept = 0
        for gid, g in t.groupby('game_id'):
            first, third = g[g.period_number <= 2], g[g.period_number == 3]
            if first.empty or third.empty:
                continue
            half, q3, kick = first.ts.max(), third.ts.min(), g.ts.min()
            gap = (q3 - half).total_seconds()
            if not 5 * 60 <= gap <= 45 * 60:
                continue
            if not 40 * 60 <= (half - kick).total_seconds() <= 3 * 3600:
                kick = half - pd.Timedelta(minutes=70)
            r = g.iloc[0]
            if r.home_team_abbrev not in NBA_NAMES or r.away_team_abbrev not in NBA_NAMES:
                continue                                   # the All-Star game and the like
            fmt = lambda x: x.strftime('%Y-%m-%dT%H:%M:%SZ')
            key = (str(r.game_date)[:10], int(g.home_score.max()), int(g.away_score.max()))
            out[key] = dict(game_id=int(gid), home_full=NBA_NAMES[r.home_team_abbrev], away_full=NBA_NAMES[r.away_team_abbrev],
                            h1h=int(first.home_score.max()), h1a=int(first.away_score.max()), playoffs=int(r.season_type != 2),
                            kick_utc=fmt(kick), half_utc=fmt(half), q3_utc=fmt(q3), break_s=int(gap))
            kept += 1
        print(f'{os.path.basename(path)}: {kept} games with a clocked halftime')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sport')
    ap.add_argument('pbp_dir')
    ap.add_argument('games_csv')
    ap.add_argument('dst')
    ap.add_argument('--since', type=int, default=2023, help='the Odds API has period markets from May 3, 2023 (nba: 2024, the season that ends in 2024)')
    a = ap.parse_args()
    games = pd.read_csv(a.games_csv)
    games = games[games.season >= a.since]
    rows = []
    if a.sport == 'nba':
        times = nba_half_times(a.pbp_dir, a.since)
        off = 0
        for r in games.itertuples():
            t = times.get((str(r.date)[:10], int(r.fh), int(r.fa)))
            if not t:
                continue
            if (t['h1h'], t['h1a']) != (int(r.h1h), int(r.h1a)):
                off += 1                                   # same date and final, different half: not the same game
                continue
            rows.append(dict(sport='nba', game_id=t['game_id'], season=r.season, week='', date=r.date, away=r.away, home=r.home,
                             away_full=t['away_full'], home_full=t['home_full'], h1a=r.h1a, h1h=r.h1h, fa=r.fa, fh=r.fh,
                             ot=int((r.ota or 0) + (r.oth or 0) > 0), total=r.total, home_spread=r.home_spread,
                             kick_utc=t['kick_utc'], half_utc=t['half_utc'], q3_utc=t['q3_utc'], break_s=t['break_s']))
        if off:
            print(f'{off} games matched on date and final but not on the halftime score, left out')
    else:
        times = (nfl_half_times if a.sport == 'nfl' else cfb_half_times)(a.pbp_dir, a.since)
        for r in games.itertuples():
            t = times.get(r.game_id)
            if not t:
                continue
            full = (lambda x: NFL_NAMES.get(x, x)) if a.sport == 'nfl' else (lambda x: x)
            rows.append(dict(sport=a.sport, game_id=r.game_id, season=r.season, week=r.week, date=r.date, away=r.away, home=r.home,
                             away_full=full(r.away), home_full=full(r.home),
                             h1a=r.h1a, h1h=r.h1h, fa=r.fa, fh=r.fh, ot=r.ot, total=r.total, home_spread=r.home_spread, **t))
    # most recent season first: the pull takes the table in order, and the credits may not cover every season
    pd.DataFrame(rows).sort_values(['season', 'date', 'game_id'], ascending=[False, True, True]).to_csv(a.dst, index=False)
    print(len(rows), 'games written to', a.dst, f'(of {len(games)} since {a.since})')


if __name__ == '__main__':
    main()
