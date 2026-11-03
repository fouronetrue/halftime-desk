"""Halftime scores for college basketball seasons whose hoopR schedule carries no linescores (2008 through 2022),
read off the hoopR play by play (sportsdataverse/sportsdataverse-data, release espn_mens_college_basketball_pbp,
play_by_play_YYYY.parquet, about 55 MB a season).

Scores never go down, so the halftime score needs no row order: it is the largest running score among the
plays of period 1, and it is trusted only when the largest score over every period equals the schedule's
final for both teams (the play by play is complete) and no second-period play carries a score below it.

Usage: python scripts/build_cbb_half_scores.py PBP_DIR data/cbb_half_scores.csv
Output: one row per game: game_id, season, h1a, h1h, fa, fh, periods (the play by play's own count).
The schedule build (build_cbb_games.py) reads this file for the seasons whose schedule has no linescores.
"""
import csv, glob, os, sys
import pyarrow.parquet as pq

COLS = ['game_id', 'period_number', 'home_score', 'away_score']


def half_scores(path):
    t = pq.read_table(path, columns=COLS).to_pandas()
    t = t.dropna(subset=['game_id', 'period_number'])
    t['period_number'] = t['period_number'].astype(int)
    t['home_score'] = t['home_score'].fillna(0).astype(int)
    t['away_score'] = t['away_score'].fillna(0).astype(int)
    out = []
    for gid, g in t.groupby('game_id'):
        p1 = g[g.period_number == 1]
        p2 = g[g.period_number == 2]
        if p1.empty or p2.empty:
            continue
        h1h, h1a = int(p1.home_score.max()), int(p1.away_score.max())
        # a second-period play with a score below the half means the first period's plays are not all there
        if int(p2.home_score.min()) < h1h or int(p2.away_score.min()) < h1a:
            continue
        out.append(dict(game_id=int(gid), h1a=h1a, h1h=h1h, fa=int(g.away_score.max()), fh=int(g.home_score.max()), periods=int(g.period_number.max())))
    return out


def main():
    pbp_dir, out_path = sys.argv[1:3]
    rows = []
    for path in sorted(glob.glob(os.path.join(pbp_dir, 'play_by_play_*.parquet'))):
        season = int(os.path.basename(path).split('_')[-1].split('.')[0])
        got = half_scores(path)
        for r in got:
            r['season'] = season
        rows += got
        print(f'{os.path.basename(path)}: {len(got)} games with a half score', flush=True)
    with open(out_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['game_id', 'season', 'h1a', 'h1h', 'fa', 'fh', 'periods'])
        w.writeheader()
        w.writerows(rows)
    print(f'{len(rows)} rows written to {out_path}')


if __name__ == '__main__':
    main()
