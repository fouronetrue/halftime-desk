"""Build the NFL halftime table from the nflverse play-by-play files.

One row per game: season, week, date, teams, the halftime score, the final (overtime included, since a
full-game total settles on it), the closing total and the home spread (minus = home favored), plus roof, temp
and wind for the Build Plan's weather test later.

Source: github.com/nflverse/nflverse-data, releases/download/pbp/play_by_play_YYYY.parquet (free), 1999 on.
spread_line there is positive when the home team is favored, so home_spread = -spread_line. home_score and
away_score are the game's final on every row.

The halftime score is read two ways that need no row order: the largest running score over the first-half
plays (a score never goes down) and the lowest score carried by a second-half play. A game is kept only when
the two agree, when the play by play's largest score is the final, and when it has a closing total and spread.

Usage: python scripts/build_nfl_games.py PBP_DIR data/nfl_games.csv     (PBP_DIR holds pbp_YYYY.parquet)
"""
import os, sys, glob
import pandas as pd
import pyarrow.parquet as pq

COLS = ['game_id', 'season', 'week', 'season_type', 'game_date', 'home_team', 'away_team', 'qtr', 'game_half', 'total_home_score',
        'total_away_score', 'home_score', 'away_score', 'spread_line', 'total_line', 'roof', 'temp', 'wind']


def season_games(path):
    names = pq.ParquetFile(path).schema_arrow.names
    t = pq.read_table(path, columns=[c for c in COLS if c in names]).to_pandas()
    t = t[t.game_id.notna() & t.qtr.notna() & t.total_home_score.notna() & t.total_away_score.notna()]
    out = []
    dropped = dict(half=0, final=0, lines=0, periods=0)
    for gid, g in t.groupby('game_id'):
        r = g.iloc[0]
        if not {1, 2, 3, 4} <= set(g.qtr.astype(int)):
            dropped['periods'] += 1
            continue
        first = g[g.game_half == 'Half1']
        second = g[g.game_half == 'Half2']
        if first.empty or second.empty:
            dropped['periods'] += 1
            continue
        h1h, h1a = int(first.total_home_score.max()), int(first.total_away_score.max())
        s2 = second
        if h1h + h1a > 0:
            s2 = second[(second.total_home_score + second.total_away_score) > 0]
        if s2.empty:
            dropped['half'] += 1
            continue
        q3 = s2.iloc[(s2.total_home_score + s2.total_away_score).values.argmin()]
        if int(q3.total_home_score) != h1h or int(q3.total_away_score) != h1a:
            dropped['half'] += 1
            continue
        fh, fa = int(r.home_score), int(r.away_score)
        if int(g.total_home_score.max()) != fh or int(g.total_away_score.max()) != fa:
            dropped['final'] += 1
            continue
        if pd.isna(r.total_line) or pd.isna(r.spread_line):
            dropped['lines'] += 1
            continue
        out.append(dict(game_id=gid, season=int(r.season), season_type=r.season_type, week=int(r.week), date=str(r.game_date)[:10],
                        away=r.away_team, home=r.home_team, h1a=h1a, h1h=h1h, fa=fa, fh=fh, ot=int(g.qtr.max() > 4),
                        total=float(r.total_line), home_spread=-float(r.spread_line),
                        roof=r.get('roof'), temp=r.get('temp'), wind=r.get('wind')))
    return out, dropped


def main(pbp_dir, dst):
    rows = []
    for path in sorted(glob.glob(os.path.join(pbp_dir, 'pbp_*.parquet'))):
        games, dropped = season_games(path)
        rows += games
        print(f"{os.path.basename(path)}: {len(games)} games kept; dropped {dropped}")
    cols = ['game_id', 'season', 'season_type', 'week', 'date', 'away', 'home', 'h1a', 'h1h', 'fa', 'fh', 'ot', 'total', 'home_spread', 'roof', 'temp', 'wind']
    pd.DataFrame(rows)[cols].sort_values(['season', 'date', 'game_id']).to_csv(dst, index=False)
    print(len(rows), 'games written to', dst)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
