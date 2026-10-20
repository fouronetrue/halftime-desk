"""Build the clean NBA game table from the Kaggle-format odds archive (SBR lineage).
One row per game: date, season, playoffs, teams, halftime score, final, OT points, closing spread (home
perspective, minus = home favored), closing total, and the market's second-half total and spread where the
archive carries them (2007-08 through early 2022-23)."""
import csv, sys
src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src)))
out = []
for r in rows:
    try:
        q = {k: int(r[k]) for k in ('q1_away', 'q2_away', 'q3_away', 'q4_away', 'ot_away', 'q1_home', 'q2_home', 'q3_home', 'q4_home', 'ot_home')}
        fa, fh = int(r['score_away']), int(r['score_home'])
        total = float(r['total'])
        spread = float(r['spread'])
    except Exception:
        continue
    home_spread = -spread if r['whos_favored'] == 'home' else spread
    h2t = r['h2_total'].strip()
    h2s = r['h2_spread'].strip()
    out.append(dict(
        date=r['date'], season=int(r['season']), playoffs=1 if r['playoffs'] == 'True' else 0,
        away=r['away'], home=r['home'],
        h1a=q['q1_away'] + q['q2_away'], h1h=q['q1_home'] + q['q2_home'],
        q3a=q['q3_away'], q3h=q['q3_home'], q4a=q['q4_away'], q4h=q['q4_home'], ota=q['ot_away'], oth=q['ot_home'],
        fa=fa, fh=fh, total=total, home_spread=home_spread,
        h2_total=float(h2t) if h2t else '', h2_spread_fav=float(h2s) if h2s else '',
    ))
with open(dst, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
    w.writeheader()
    w.writerows(out)
print(len(out), 'games written')
