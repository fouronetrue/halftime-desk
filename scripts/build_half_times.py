"""The halftime timetable for the Odds API history pull: when each game's break started and ended, on the wall
clock, next to the numbers the model needs (closing total and spread, halftime score, final).

NFL: the nflverse play by play carries time_of_day (UTC) on most plays. The break starts at the last timed play
of the first half and ends at the first of the second; the 2H line is read inside it (scripts/odds_history.py).
Games with no clock on either side of the break are left out. Team names are mapped to the full names the Odds
API uses.

Usage: python scripts/build_half_times.py nfl PBP_DIR data/nfl_games.csv data/half_times_nfl.csv [--since 2023]
       python scripts/build_half_times.py cfb PBP_DIR data/cfb_games.csv data/half_times_cfb.csv
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sport')
    ap.add_argument('pbp_dir')
    ap.add_argument('games_csv')
    ap.add_argument('dst')
    ap.add_argument('--since', type=int, default=2023, help='the Odds API has period markets from May 3, 2023')
    a = ap.parse_args()
    if a.sport not in ('nfl', 'cfb'):
        sys.exit('nfl and cfb so far; nba needs the hoopR wallclocks')
    games = pd.read_csv(a.games_csv)
    games = games[games.season >= a.since]
    times = (nfl_half_times if a.sport == 'nfl' else cfb_half_times)(a.pbp_dir, a.since)
    rows = []
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
