"""python scripts/build_nba_h2_spread.py <dir of "nba odds YYYY-YY.csv"> data/nba_games.csv data/nba_games_h2.csv
The market's second-half spread with its side, straight from the raw sportsbookreviewsonline season files
(the rows come in visitor/home pairs; the 2H column holds the spread on the second-half favorite's row and the
2H total on the other row). Seasons 2008-09 through 2019-20. Matched to data/nba_games.csv by date and the four
quarter scores, so no team-name mapping is needed. Output columns: date, away, home, h1a, h1h, h2_fav, h2_spread,
h2_total, plus every column of the game table."""
import csv, sys, os, glob
src_dir, games_path, dst = sys.argv[1], sys.argv[2], sys.argv[3]
games = list(csv.DictReader(open(games_path)))
idx = {}
for g in games:
    idx.setdefault((g['date'][5:7] + g['date'][8:10], g['season']), []).append(g)
def f(x):
    try:
        return float(x)
    except Exception:
        return None
out, nomatch, skipped = [], 0, 0
for path in sorted(glob.glob(os.path.join(src_dir, 'nba odds *.csv'))):
    season = int(os.path.basename(path).split()[2][:4]) + 1   # 'nba odds 2018-19.csv' -> season 2019
    rows = list(csv.DictReader(open(path)))
    for i in range(0, len(rows) - 1, 2):
        v, h = rows[i], rows[i + 1]
        if v.get('VH') not in ('V', 'N') or h.get('VH') not in ('H', 'N'):
            continue
        v2, h2 = f(v['2H']), f(h['2H'])
        if v2 is None or h2 is None:
            skipped += 1; continue
        if v2 < 30 and h2 >= 30:
            fav, spread, total = 'away', v2, h2
        elif h2 < 30 and v2 >= 30:
            fav, spread, total = 'home', h2, v2
        else:
            skipped += 1; continue
        key = (v['Date'].zfill(4), str(season))
        match = None
        for g in idx.get(key, []):
            try:
                if (int(g['h1a']), int(g['h1h']), int(g['q3a']), int(g['q3h'])) == (int(v['1st']) + int(v['2nd']), int(h['1st']) + int(h['2nd']), int(v['3rd']), int(h['3rd'])):
                    match = g; break
            except Exception:
                continue
        if match is None:
            nomatch += 1; continue
        out.append(dict(match, h2_fav=fav, h2_spread=spread, h2_total_raw=total))
with open(dst, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
print(len(out), 'games with a sided 2H spread;', nomatch, 'unmatched,', skipped, 'without a usable 2H column')
