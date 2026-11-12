"""Repair the home spread in data/cfb_games.csv from the CFBD lines file, without the play by play.

Why (Nov 12, 2026): scripts/build_cfb_games.py matched a spread row to a team only when the row's label equaled
ESPN's abbreviation. The lines file labels rows with a sportsbook feed's own abbreviations in a sixth of the
2006-19 games and with the full team name from 2020 on, so those games fell back to the play by play's
homeTeamSpread, which is signed the other way (plus = home favored) and is a 2.5 placeholder where ESPN had no
line. 5,644 of 13,127 games carried the wrong sign: the correlation between the final home margin and the home
team being favored ran -0.5 in 2021-25 where a right table reads +0.7. Every study that named a favorite on
those seasons (the trailing-favorite cells, the favorite terms of the cfb block) read the wrong team.

This rewrites the home_spread column in place with build_cfb_games.game_home_spread (the fixed resolver: every
label the team could carry, the lines file's own Away@Home description as the last resort). Nothing else in the
table changes. A game whose two sides cannot be told apart is dropped and listed (14 of them). The run fails if any season's sign check
(correlation of the final home margin with minus the home spread) comes out under 0.55.

Usage: python scripts/repair_cfb_spreads.py betting/csv/cfb_line_odds.csv.gz data/cfb_games.csv [--dry]
       (the lines file is sportsdataverse/cfbfastR-data on GitHub, betting/csv/cfb_line_odds.csv.gz)
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_cfb_games import lines, game_home_spread


def repair(lines_path, games_path, dry=False):
    L = lines(lines_path)
    c = pd.read_csv(games_path)
    cols = list(c.columns)
    new, lost = [], []
    for r in c.itertuples():
        total, sp, desc = L.get(int(r.game_id), (None, None, ''))
        hs = game_home_spread(sp, r.home_abbr, r.home, r.away_abbr, r.away, desc)
        if hs is None:
            lost.append(r)
        new.append(hs)
    c['old'] = c['home_spread']
    c['home_spread'] = new
    kept = c[c.home_spread.notna()].copy()
    hm = kept.fh - kept.fa
    print('season   games  sign flipped  size changed 1+  dropped   sign check (old -> new)   home favored')
    bad = []
    for season, g in c.groupby('season'):
        k = g[g.home_spread.notna()]
        flipped = int(((np.sign(k.old) != np.sign(k.home_spread)) & (k.old != 0) & (k.home_spread != 0)).sum())
        resized = int(((k.old.abs() - k.home_spread.abs()).abs() >= 1).sum())
        m = k.fh - k.fa
        r_old = float(np.corrcoef(m, -k.old)[0, 1]) if k.old.std() > 0 else float('nan')
        r_new = float(np.corrcoef(m, -k.home_spread)[0, 1])
        print(f'{season}   {len(g):>6} {flipped:>13} {resized:>16} {len(g) - len(k):>8}   {r_old:+.2f} -> {r_new:+.2f}                {100 * (k.home_spread < 0).mean():.0f}%')
        if not r_new >= 0.55:
            bad.append((season, r_new))
    flipped_all = int(((np.sign(kept.old) != np.sign(kept.home_spread)) & (kept.old != 0) & (kept.home_spread != 0)).sum())
    print(f'all      {len(c):>6} {flipped_all:>13} {"":>16} {len(lost):>8}   {np.corrcoef(c.fh - c.fa, -c.old)[0, 1]:+.2f} -> {np.corrcoef(hm, -kept.home_spread)[0, 1]:+.2f}                {100 * (kept.home_spread < 0).mean():.0f}%')
    for r in lost:
        print(f'  dropped, sides not told apart: {r.season} {r.away} @ {r.home} ({r.game_id})')
    if bad:
        raise SystemExit(f'sign check failed: {bad}')
    if not dry:
        kept[cols].to_csv(games_path, index=False)
        print(len(kept), 'games written to', games_path)
    return kept[cols]


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    repair(args[0], args[1], dry='--dry' in sys.argv)
