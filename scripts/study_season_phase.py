"""Season phase and weather (Roadmap v2, S2): early vs late season, playoffs and bowls, dome vs outdoors,
temperature and wind, in the NFL and FBS second half.

Residual = actual second-half points minus the model block's number (what the desk would miss), and, where the
book's halftime line is on file (data/odds_h2_<sport>.csv, 2023 on), the book's own miss and the over rate.
NFL weather (roof, temp, wind) comes from the nflverse play-by-play in data/nfl_games.csv; the FBS table has
the week and the bowl flag only (venue weather is an Open-Meteo pull, a later study if the week buckets say
anything). The gate is the same as every other study: a bucket past 2 SE with a mechanism, the all-features
regression past t 2, and leave-one-season-out MAE and Brier at the rungs improved by the term.

Usage: python scripts/study_season_phase.py [nfl|cfb|all]
"""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from study_tools import load_games, add_book, cell, regress, loso_with


def nfl():
    d = add_book(load_games('nfl'), 'nfl')
    d['temp'] = pd.to_numeric(d.temp, errors='coerce')
    d['wind'] = pd.to_numeric(d.wind, errors='coerce')
    out = d.roof.isin(['outdoors', 'open'])
    print(f"NFL: {len(d)} games 2006-{d.season.max()}, {int(d.line_med.notna().sum())} with the book's halftime line; model miss {d.resid.mean():+.2f} sd {d.resid.std():.2f}")
    print('\nSeason phase:')
    cell(d, d.week <= 4, 'weeks 1 to 4')
    cell(d, (d.week >= 5) & (d.week <= 9), 'weeks 5 to 9')
    cell(d, (d.week >= 10) & (d.week <= 14), 'weeks 10 to 14')
    cell(d, (d.week >= 15) & (d.season_type == 'REG'), 'week 15 on, regular season')
    cell(d, d.season_type != 'REG', 'playoffs')
    cell(d, d.week == 1, 'week 1 alone')
    cell(d, d.week == 18, 'week 18 (resting starters)')
    print('\nRoof:')
    cell(d, d.roof == 'dome', 'dome')
    cell(d, d.roof == 'closed', 'retractable, closed')
    cell(d, out, 'outdoors or open')
    print('\nTemperature (outdoors):')
    for lo, hi, lab in [(-50, 32, 'freezing (32 or under)'), (33, 45, '33 to 45'), (46, 60, '46 to 60'), (61, 75, '61 to 75'), (76, 120, '76 and up')]:
        cell(d, out & (d.temp >= lo) & (d.temp <= hi), lab)
    print('\nWind (outdoors, mph):')
    for lo, hi, lab in [(0, 5, '0 to 5'), (6, 10, '6 to 10'), (11, 15, '11 to 15'), (16, 99, '16 and up')]:
        cell(d, out & (d.wind >= lo) & (d.wind <= hi), lab)
    cell(d, out & (d.wind >= 16) & (d.total >= 47), 'wind 16+ on a total of 47 or more')
    cell(d, out & (d.wind >= 11) & (d.total >= 47), 'wind 11+ on a total of 47 or more')
    cell(d, out & (d.temp <= 32) & (d.week >= 13), 'freezing, week 13 on (the December game)')
    print('\nRegression on every feature at once (t past 2 is the bar):')
    cols = {'weeks_1_4': d.week <= 4, 'week_15_on': (d.week >= 15) & (d.season_type == 'REG'), 'playoffs': d.season_type != 'REG',
            'dome_or_closed': d.roof.isin(['dome', 'closed']), 'freezing': out & (d.temp <= 32), 'hot_76': out & (d.temp >= 76),
            'wind_11_15': out & (d.wind >= 11) & (d.wind <= 15), 'wind_16': out & (d.wind >= 16), 'wind_x_total': (out & (d.wind >= 11)) * (d.total - 44)}
    flagged = regress(d, cols)
    print('\nThe gate:')
    if not flagged:
        print('  nothing past t 2: no term.')
    for name in flagged:
        loso_with(d, 'nfl', cols[name], name)


def cfb():
    d = add_book(load_games('cfb'), 'cfb')
    bowl = d.season_type.astype(str).str.lower() != 'regular'
    print(f"\nFBS: {len(d)} games 2006-{d.season.max()}, {int(d.line_med.notna().sum())} with the book's halftime line; model miss {d.resid.mean():+.2f} sd {d.resid.std():.2f}")
    print('\nSeason phase:')
    cell(d, (d.week <= 2) & ~bowl, 'weeks 1 to 2 (openers)')
    cell(d, (d.week >= 3) & (d.week <= 4) & ~bowl, 'weeks 3 to 4')
    cell(d, (d.week >= 5) & (d.week <= 8) & ~bowl, 'weeks 5 to 8')
    cell(d, (d.week >= 9) & (d.week <= 12) & ~bowl, 'weeks 9 to 12')
    cell(d, (d.week >= 13) & ~bowl, 'week 13 on (rivalry week, conference title games)')
    cell(d, bowl, 'bowls and playoff')
    cell(d, (d.week <= 4) & ~bowl & (d.home_spread.abs() >= 21), 'early season, spread 21+ (the paycheck game)')
    cell(d, ((d.away_div != 'fbs') | (d.home_div != 'fbs')), 'an FCS team in the game')
    cell(d, d.neutral == 1, 'neutral site')
    print('\nRegression on every feature at once (t past 2 is the bar):')
    cols = {'weeks_1_2': (d.week <= 2) & ~bowl, 'weeks_3_4': (d.week >= 3) & (d.week <= 4) & ~bowl, 'week_13_on': (d.week >= 13) & ~bowl,
            'bowl': bowl, 'fcs': (d.away_div != 'fbs') | (d.home_div != 'fbs'), 'neutral': d.neutral == 1}
    flagged = regress(d, cols)
    print('\nThe gate:')
    if not flagged:
        print('  nothing past t 2: no term.')
    for name in flagged:
        loso_with(d, 'cfb', cols[name], name)


if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if which in ('nfl', 'all'):
        nfl()
    if which in ('cfb', 'all'):
        cfb()
