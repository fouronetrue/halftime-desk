"""NFL schedule study (Roadmap v2, S3): rest days, Thursday and Monday games, byes, international games, time
zones and body clocks, and whether any of it is left in the second half once the pregame total is known.

Data: data/nfl_games.csv (the halftime table, 2006 on) joined on game_id to the nflverse schedule table
(github.com/nflverse/nfldata, data/games.csv: gameday, weekday, gametime in Eastern, location, stadium,
away_rest and home_rest in days), and data/odds_h2_nfl.csv (DraftKings' second-half total read 7 minutes
into the break, 2023 on) for the book's own miss.

Two residuals per game:
  resid   actual second-half points minus the model block's number (what the desk would miss)
  vs book actual second-half points minus the book's halftime line (what the market missed), with the over rate
A feature earns a term only when its bucket sits past 2 SE with a mechanism, the regression on every feature at
once keeps it past 2 (t), and adding it to the block improves leave-one-season-out MAE and Brier at the rungs the
desk prices. The NBA study found every one of these priced before tip; this is the NFL's own answer.

Usage: python scripts/study_nfl_schedule.py [SCHEDULE_CSV]   (default data/nfl_schedule.csv, the nflverse table trimmed to the columns used, 2006 on)
"""
import sys, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from fit_cfb import features, mu_of
from study_tools import cell, regress, loso_with

# home time zones as hours behind Eastern (AZ keeps standard time, which is Pacific in the season's daylight weeks)
TZ = {'ET': 0, 'CT': -1, 'MT': -2, 'PT': -3}
TEAM_TZ = {'ARI': 'PT', 'ATL': 'ET', 'BAL': 'ET', 'BUF': 'ET', 'CAR': 'ET', 'CHI': 'CT', 'CIN': 'ET', 'CLE': 'ET', 'DAL': 'CT', 'DEN': 'MT',
           'DET': 'ET', 'GB': 'CT', 'HOU': 'CT', 'IND': 'ET', 'JAX': 'ET', 'KC': 'CT', 'LA': 'PT', 'LAC': 'PT', 'LV': 'PT', 'MIA': 'ET',
           'MIN': 'CT', 'NE': 'ET', 'NO': 'CT', 'NYG': 'ET', 'NYJ': 'ET', 'OAK': 'PT', 'PHI': 'ET', 'PIT': 'ET', 'SD': 'PT', 'SEA': 'PT',
           'SF': 'PT', 'STL': 'CT', 'TB': 'ET', 'TEN': 'CT', 'WAS': 'ET'}
ABROAD = ('Wembley', 'Tottenham', 'Twickenham', 'Azteca', 'Allianz', 'Deutsche Bank', 'Frankfurt', 'Croke', 'Bernab', 'Corinthians',
          'Arena Corinthians', 'Rogers Centre', 'Melbourne', 'Accor', 'Stade', 'Olympiastadion', 'Olympic Stadium')


def load(sched_path):
    d = pd.read_csv(os.path.join(ROOT, 'data', 'nfl_games.csv'))
    d = d[(d.season >= 2006) & (d.total > 20) & (d.total < 80) & (d.home_spread.abs() < 30)]
    s = pd.read_csv(sched_path, usecols=['game_id', 'weekday', 'gametime', 'location', 'stadium', 'away_rest', 'home_rest', 'div_game'])
    d = d.merge(s, on='game_id', how='left').reset_index(drop=True)
    d['y'] = (d.fh + d.fa) - (d.h1h + d.h1a)
    d['hour'] = pd.to_numeric(d.gametime.astype(str).str.slice(0, 2), errors='coerce') + pd.to_numeric(d.gametime.astype(str).str.slice(3, 5), errors='coerce') / 60
    d['away_off'] = d.away.map(lambda t: TZ[TEAM_TZ.get(t, 'ET')])
    d['home_off'] = d.home.map(lambda t: TZ[TEAM_TZ.get(t, 'ET')])
    d['shift'] = d.home_off - d.away_off              # hours the away team moved: plus = east, minus = west
    d['body_away'] = d.hour + d.away_off              # kickoff on the away team's home clock
    d['body_home'] = d.hour + d.home_off
    d['intl'] = (d.location == 'Neutral') & d.stadium.astype(str).str.contains('|'.join(ABROAD), case=False, regex=True)
    d['neutral_us'] = (d.location == 'Neutral') & ~d.intl & (d.season_type == 'REG')
    d['thu'] = d.weekday == 'Thursday'
    d['mon'] = d.weekday == 'Monday'
    d['sat'] = d.weekday == 'Saturday'
    d['prime'] = d.hour >= 20
    d['short_away'] = d.away_rest <= 5
    d['short_home'] = d.home_rest <= 5
    d['bye_away'] = d.away_rest >= 13
    d['bye_home'] = d.home_rest >= 13
    d['rest_edge'] = d.home_rest - d.away_rest
    m = engine.MODEL['nfl']
    X = features(d, m.get('knee', 14) if len(m['coef']) > 6 else None)
    d['mu'] = mu_of(np.array(m['coef']), X)
    d['resid'] = d.y - d.mu
    o = pd.read_csv(os.path.join(ROOT, 'data', 'odds_h2_nfl.csv'), usecols=['game_id', 'line_med'])
    d = d.merge(o, on='game_id', how='left')
    d['vs_book'] = d.y - d.line_med
    d['over'] = np.where(d.line_med.notna(), (d.y > d.line_med).astype(float), np.nan)
    d.loc[d.y == d.line_med, 'over'] = np.nan
    return d


def main(sched):
    d = load(sched)
    have = d.weekday.notna()
    print(f"{len(d)} NFL games 2006-{d.season.max()}, {int(have.sum())} with the schedule row, {int(d.line_med.notna().sum())} with the book's halftime line; "
          f"model miss {d.resid.mean():+.2f} sd {d.resid.std():.2f}")
    d = d[have].reset_index(drop=True)
    print('\nRest (days since the last game):')
    cell(d, d.short_away, 'away on short rest (5 days or less)')
    cell(d, d.short_home, 'home on short rest')
    cell(d, d.short_away & d.short_home, 'both on short rest (Thursday after Sunday)')
    cell(d, (d.away_rest >= 6) & (d.away_rest <= 8) & (d.home_rest >= 6) & (d.home_rest <= 8), 'both on a normal week')
    cell(d, d.bye_away, 'away off a bye (13+ days)')
    cell(d, d.bye_home, 'home off a bye')
    cell(d, d.bye_away & ~d.bye_home, 'away off a bye, home not')
    cell(d, d.bye_home & ~d.bye_away, 'home off a bye, away not')
    cell(d, d.rest_edge >= 4, 'home rest edge 4+ days')
    cell(d, d.rest_edge <= -4, 'away rest edge 4+ days')
    print('\nDay and slot:')
    cell(d, d.thu, 'Thursday')
    cell(d, d.mon, 'Monday night')
    cell(d, d.sat, 'Saturday')
    cell(d, d.prime, 'prime time (8 PM ET or later)')
    cell(d, (d.hour >= 12.5) & (d.hour <= 13.5), '1 PM ET window')
    cell(d, (d.hour >= 16) & (d.hour <= 17), 'late-afternoon window')
    print('\nTravel and time zones:')
    cell(d, d.intl, 'international (London, Germany, Mexico, Brazil, ...)')
    cell(d, d.neutral_us, 'neutral site in the US (regular season)')
    cell(d, d['shift'] >= 3, 'away team crossed 3 zones east (West Coast team in the East)')
    cell(d, d['shift'] <= -3, 'away team crossed 3 zones west (East team on the West Coast)')
    cell(d, d['shift'].abs() == 2, 'two zones either way')
    cell(d, d['shift'] == 0, 'same zone')
    cell(d, d.body_away <= 10.5, 'away body clock 10:30 AM or earlier (West team at 1 PM ET)')
    cell(d, d.body_home <= 10.5, 'home body clock 10:30 AM or earlier')
    cell(d, d.body_away >= 21, 'away body clock 9 PM or later (East team in a West night game)')
    cell(d, (d['shift'] <= -3) & d.prime, 'East team, West Coast prime time')
    cell(d, (d['shift'] >= 3) & (d.hour <= 13.5), 'West team, 1 PM ET')
    cell(d, d.div_game == 1, 'division game')
    print('\nThe regression: the model residual on every feature at once (t past 2 is the bar)')
    cols = {'short_away': d.short_away, 'short_home': d.short_home, 'bye_away': d.bye_away, 'bye_home': d.bye_home, 'thu': d.thu, 'mon': d.mon,
            'prime': d.prime, 'intl': d.intl, 'shift_east3': d['shift'] >= 3, 'shift_west3': d['shift'] <= -3,
            'body_away_early': d.body_away <= 10.5, 'body_away_late': d.body_away >= 21, 'div_game': d.div_game == 1}
    flagged = regress(d, cols)
    print('\nThe gate for anything flagged (leave one season out, the full table):')
    if not flagged:
        print('  nothing past t 2: no term. The pregame total already carries the schedule.')
    for name in flagged:
        loso_with(d, 'nfl', cols[name], name)
    # the book's own view, 2023 on: does the schedule explain where DraftKings' halftime line misses?
    b = d[d.line_med.notna()]
    if len(b) >= 200:
        print(f"\nThe book's halftime line, {len(b)} games 2023 on: miss {b.vs_book.mean():+.2f}, over {100 * b.over.mean():.1f}%")
        for name, c in cols.items():
            m = c[b.index] if hasattr(c, 'index') else c
            m = m.loc[b.index] if hasattr(m, 'loc') else m
            n = int(m.sum())
            if n >= 25:
                ov = b.over[m & b.over.notna()]
                print(f"  {name:<18} n {n:>4}  vs book {b.vs_book[m].mean():+5.2f}  over {100 * ov.mean():4.1f}%")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'data', 'nfl_schedule.csv'))
