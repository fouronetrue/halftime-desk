"""python scripts/study_nba_pace_form.py (needs numpy; data/nba_first_half_box.csv comes from
scripts/build_nba_first_half_box.py over the hoopR-nba-data play-by-play parquet files). Two asks from Oct 20: (A) first-half pace by possessions, shots, free throws, fouls, turnovers: does it move the
second-half total beyond the points-based model and beyond the market's 2H line? (B) team form and tanking:
losing streaks, bottom teams late in the season, do their games score differently in the second half?"""
import csv, math, os, datetime as dt
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
games = list(csv.DictReader(open(os.path.join(ROOT, 'data', 'nba_games.csv'))))
pace = list(csv.DictReader(open(os.path.join(ROOT, 'data', 'nba_first_half_box.csv'))))
P = {}
for r in pace:
    P[(r['date'], r['away'], r['home'])] = r
G = []
for r in games:
    g = dict(date=r['date'], season=int(r['season']), playoffs=int(r['playoffs']), away=r['away'], home=r['home'],
             h1a=int(r['h1a']), h1h=int(r['h1h']), fa=int(r['fa']), fh=int(r['fh']), total=float(r['total']), home_spread=float(r['home_spread']),
             L=float(r['h2_total']) if r['h2_total'] else None)
    g['h1'] = g['h1a'] + g['h1h']; g['h2'] = g['fa'] + g['fh'] - g['h1']
    hfb = -g['home_spread']; g['fav_by'] = abs(hfb); m1 = g['h1h'] - g['h1a']; g['favm'] = m1 if hfb >= 0 else -m1
    g['hm'] = m1
    G.append(g)
G.sort(key=lambda g: g['date'])

# ---------- A. pace ----------
joined = 0
for g in G:
    p = P.get((g['date'], g['away'], g['home']))
    if p is None:
        d = dt.date.fromisoformat(g['date'])
        for off in (-1, 1):
            p = P.get(((d + dt.timedelta(days=off)).isoformat(), g['away'], g['home']))
            if p: break
    if p is None or (int(p['h1h']), int(p['h1a'])) != (g['h1h'], g['h1a']):
        continue
    joined += 1
    g['poss'] = (float(p['h_poss']) + float(p['a_poss'])) / 2
    g['fga'] = int(p['h_fga']) + int(p['a_fga']); g['tpa'] = int(p['h_tpa']) + int(p['a_tpa'])
    g['fta'] = int(p['h_ft']) + int(p['a_ft']); g['fouls'] = int(p['h_foul']) + int(p['a_foul']); g['tov'] = int(p['h_tov']) + int(p['a_tov'])
    g['oreb'] = int(p['h_oreb']) + int(p['a_oreb'])
    g['ppp'] = g['h1'] / (2 * g['poss'])   # points per possession in the first half
PG = [g for g in G if 'poss' in g]
print(f"A. PACE: {joined} games joined to play-by-play first-half box scores (2019-20 through 2025-26), halftime score matched exactly")
def X_base(gs):
    return np.array([[1.0, g['total'], g['h1'], abs(g['favm']), g['favm'], (g['fav_by'] if g['favm'] < 0 else 0.0)] for g in gs])
def X_pace(gs):
    return np.array([[1.0, g['total'], g['h1'], abs(g['favm']), g['favm'], (g['fav_by'] if g['favm'] < 0 else 0.0),
                      g['poss'], g['fta'], g['fouls'], g['tov'], g['tpa']] for g in gs])
def ols(X, y):
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ c
    s2 = np.sum(r ** 2) / (len(y) - X.shape[1]); cov = s2 * np.linalg.inv(X.T @ X)
    return c, r, np.sqrt(np.diag(cov))
tr = [g for g in PG if g['season'] <= 2024]; te = [g for g in PG if g['season'] >= 2025]
y_tr = np.array([g['h2'] for g in tr], float); y_te = np.array([g['h2'] for g in te], float)
cb, rb, seb = ols(X_base(tr), y_tr); cp, rp, sep = ols(X_pace(tr), y_tr)
names = ['const', 'total', '1H pts', '|favm|', 'favm', 'fav_by if trailing', '1H possessions (per team)', '1H free throws', '1H fouls', '1H turnovers', '1H three-point attempts']
print('   coefficients with the pace features added (fit 2019-20 to 2023-24):')
for i, n in enumerate(names):
    print(f"   {n:28s} {cp[i]:+8.4f}  t {cp[i]/sep[i]:+6.2f}")
print(f"   in-sample MAE base {np.mean(np.abs(rb)):.3f}  with pace {np.mean(np.abs(rp)):.3f}")
mb = np.maximum(8, X_base(te) @ cb); mp = np.maximum(8, X_pace(te) @ cp)
print(f"   out of sample (2024-25, 2025-26, n {len(te)}): MAE base {np.mean(np.abs(y_te - mb)):.3f}  with pace {np.mean(np.abs(y_te - mp)):.3f}  closer {100*np.mean(np.abs(y_te-mp) < np.abs(y_te-mb)):.1f}% of games")
print('   residual of the base model by first-half pace (possessions per team) and by free throws:')
allr = np.array([g['h2'] for g in PG]) - np.maximum(8, X_base(PG) @ cb)
for lo, hi in [(0, 45), (45, 47), (47, 49), (49, 51), (51, 53), (53, 99)]:
    idx = [i for i, g in enumerate(PG) if lo <= g['poss'] < hi]
    gl = [i for i in idx if PG[i]['L'] is not None]
    miss = np.array([PG[i]['h2'] - PG[i]['L'] for i in gl]) if gl else np.array([0.0])
    print(f"   poss {lo}-{hi}: n {len(idx):5d}  1H pts {np.mean([PG[i]['h1'] for i in idx]):6.1f}  2H pts {np.mean([PG[i]['h2'] for i in idx]):6.1f}  base resid {np.mean(allr[idx]):+5.2f}  | vs 2H line n {len(gl):4d} miss {np.mean(miss):+5.2f} over {100*np.mean(miss>0)/max(1e-9,np.mean(miss!=0)):4.1f}%")
for lo, hi in [(0, 14), (14, 18), (18, 22), (22, 26), (26, 99)]:
    idx = [i for i, g in enumerate(PG) if lo <= g['fta'] < hi]
    gl = [i for i in idx if PG[i]['L'] is not None]
    miss = np.array([PG[i]['h2'] - PG[i]['L'] for i in gl]) if gl else np.array([0.0])
    print(f"   1H FTA {lo}-{hi}: n {len(idx):5d}  base resid {np.mean(allr[idx]):+5.2f}  | vs 2H line n {len(gl):4d} miss {np.mean(miss):+5.2f} over {100*np.mean(miss>0)/max(1e-9,np.mean(miss!=0)):4.1f}%")
for lo, hi in [(0, 14), (14, 17), (17, 20), (20, 23), (23, 99)]:
    idx = [i for i, g in enumerate(PG) if lo <= g['fouls'] < hi]
    print(f"   1H fouls {lo}-{hi}: n {len(idx):5d}  base resid {np.mean(allr[idx]):+5.2f}")
print('   a fast, cold first half (possessions 51+, points per possession under 1.05) vs a slow, hot one (possessions under 47, ppp over 1.15):')
for name, pred in [('fast and cold', lambda g: g['poss'] >= 51 and g['ppp'] < 1.05), ('slow and hot', lambda g: g['poss'] < 47 and g['ppp'] > 1.15), ('fast and hot', lambda g: g['poss'] >= 51 and g['ppp'] > 1.15), ('slow and cold', lambda g: g['poss'] < 47 and g['ppp'] < 1.05)]:
    idx = [i for i, g in enumerate(PG) if pred(g)]
    gl = [i for i in idx if PG[i]['L'] is not None]
    miss = np.array([PG[i]['h2'] - PG[i]['L'] for i in gl]) if gl else np.array([0.0])
    print(f"   {name:14s} n {len(idx):4d}  1H pts {np.mean([PG[i]['h1'] for i in idx]):6.1f}  2H pts {np.mean([PG[i]['h2'] for i in idx]):6.1f}  base resid {np.mean(allr[idx]):+5.2f}  | vs line n {len(gl):4d} miss {np.mean(miss):+5.2f} over {100*np.mean(miss>0)/max(1e-9,np.mean(miss!=0)):4.1f}%")
# pace model against the market line, where both exist
gl = [g for g in PG if g['L'] is not None]
if gl:
    Xl = X_pace(gl); y = np.array([g['h2'] for g in gl], float); L = np.array([g['L'] for g in gl])
    m = np.maximum(8, Xl @ cp); mb2 = np.maximum(8, X_base(gl) @ cb)
    print(f"   vs the market 2H line (n {len(gl)}): MAE market {np.mean(np.abs(y-L)):.2f}, base model {np.mean(np.abs(y-mb2)):.2f}, pace model {np.mean(np.abs(y-m)):.2f}; pace model side when it disagrees with the line by 2+: {100*np.mean([(y[i]>L[i])==(m[i]>L[i]) for i in range(len(y)) if abs(m[i]-L[i])>=2 and y[i]!=L[i]]):.1f}% (n {sum(1 for i in range(len(y)) if abs(m[i]-L[i])>=2 and y[i]!=L[i])})")

# ---------- B. form and tanking ----------
print()
print('B. FORM AND TANKING (regular season, 2012-13 on; season-to-date record and streak before the game)')
rec = {}
for g in G:
    if g['playoffs']:
        continue
    for side, team, won in (('a', g['away'], g['fa'] > g['fh']), ('h', g['home'], g['fh'] > g['fa'])):
        st = rec.setdefault((g['season'], team), dict(w=0, l=0, streak=0, gp=0))
        g[side + '_wpct'] = st['w'] / st['gp'] if st['gp'] else 0.5
        g[side + '_lstreak'] = -st['streak'] if st['streak'] < 0 else 0
        g[side + '_wstreak'] = st['streak'] if st['streak'] > 0 else 0
        g[side + '_gp'] = st['gp']
        st['gp'] += 1; st['w' if won else 'l'] += 1
        st['streak'] = (st['streak'] + 1 if st['streak'] > 0 else 1) if won else (st['streak'] - 1 if st['streak'] < 0 else -1)
# season rank by final record, to find the bottom teams
final = {}
for (s, t), st in rec.items():
    final.setdefault(s, []).append((st['w'] / max(1, st['gp']), t))
bottom5 = {s: {t for _, t in sorted(v)[:5]} for s, v in final.items()}
F = [g for g in G if not g['playoffs'] and g['season'] >= 2013 and 'a_wpct' in g]
cf, rf, _ = ols(X_base(F), np.array([g['h2'] for g in F], float))
for i, g in enumerate(F):
    g['res'] = rf[i]
def row(name, pred):
    gs = [g for g in F if pred(g)]
    if len(gs) < 150:
        return
    res = np.array([g['res'] for g in gs]); gl = [g for g in gs if g['L'] is not None]
    miss = np.array([g['h2'] - g['L'] for g in gl]) if gl else np.array([0.0])
    print(f"  {name:58s} n {len(gs):5d}  total {np.mean([g['total'] for g in gs]):6.1f}  2H resid {np.mean(res):+5.2f} (se {np.std(res)/math.sqrt(len(res)):.2f})  | vs line n {len(gl):4d} miss {np.mean(miss):+5.2f} over {100*np.mean(miss>0)/max(1e-9,np.mean(miss!=0)):4.1f}%")
late = lambda g: int(g['date'][5:7]) in (3, 4) and g['a_gp'] >= 55
row('either team on a 5+ game losing streak', lambda g: g['a_lstreak'] >= 5 or g['h_lstreak'] >= 5)
row('either team on an 8+ game losing streak', lambda g: g['a_lstreak'] >= 8 or g['h_lstreak'] >= 8)
row('both teams on a 3+ game losing streak', lambda g: g['a_lstreak'] >= 3 and g['h_lstreak'] >= 3)
row('either team on a 5+ game winning streak', lambda g: g['a_wstreak'] >= 5 or g['h_wstreak'] >= 5)
row('a bottom-5 team (final standings) playing, Mar-Apr', lambda g: late(g) and (g['away'] in bottom5[g['season']] or g['home'] in bottom5[g['season']]))
row('two bottom-5 teams, Mar-Apr', lambda g: late(g) and g['away'] in bottom5[g['season']] and g['home'] in bottom5[g['season']])
row('a bottom-5 team playing, Oct-Dec', lambda g: int(g['date'][5:7]) in (10, 11, 12) and (g['away'] in bottom5[g['season']] or g['home'] in bottom5[g['season']]))
row('team under .300 after 40 games playing', lambda g: (g['a_gp'] >= 40 and g['a_wpct'] < .3) or (g['h_gp'] >= 40 and g['h_wpct'] < .3))
row('team under .300 after 40 games, trailing at the half', lambda g: (g['a_gp'] >= 40 and g['a_wpct'] < .3 and g['hm'] > 0) or (g['h_gp'] >= 40 and g['h_wpct'] < .3 and g['hm'] < 0))
row('team over .700 after 40 games playing', lambda g: (g['a_gp'] >= 40 and g['a_wpct'] > .7) or (g['h_gp'] >= 40 and g['h_wpct'] > .7))
row('mismatch: .700+ team vs under-.300 team', lambda g: (g['a_gp'] >= 40 and g['h_gp'] >= 40) and ((g['a_wpct'] > .7 and g['h_wpct'] < .3) or (g['h_wpct'] > .7 and g['a_wpct'] < .3)))
row('April games (last two weeks of the season)', lambda g: int(g['date'][5:7]) == 4 and g['a_gp'] >= 70)
row('April, a bottom-5 team playing', lambda g: int(g['date'][5:7]) == 4 and g['a_gp'] >= 70 and (g['away'] in bottom5[g['season']] or g['home'] in bottom5[g['season']]))
print('   the pregame total already moves for bad teams: mean total when a bottom-5 team plays in April vs October through February')
for name, pred in [('Oct-Feb, bottom-5 team', lambda g: int(g['date'][5:7]) in (10, 11, 12, 1, 2) and (g['away'] in bottom5[g['season']] or g['home'] in bottom5[g['season']])),
                   ('April, bottom-5 team', lambda g: int(g['date'][5:7]) == 4 and (g['away'] in bottom5[g['season']] or g['home'] in bottom5[g['season']])),
                   ('April, no bottom-5 team', lambda g: int(g['date'][5:7]) == 4 and not (g['away'] in bottom5[g['season']] or g['home'] in bottom5[g['season']]))]:
    gs = [g for g in F if pred(g)]
    print(f"   {name:26s} n {len(gs):5d}  total {np.mean([g['total'] for g in gs]):6.1f}  actual {np.mean([g['fa']+g['fh'] for g in gs]):6.1f}  diff {np.mean([g['fa']+g['fh']-g['total'] for g in gs]):+5.2f}")

print()
print('C. PACE TILT ON THE MARKET LINE, OUT OF SAMPLE')
gl = [g for g in PG if g['L'] is not None]
fit = [g for g in gl if g['season'] <= 2021]; test = [g for g in gl if g['season'] >= 2022]
xf = np.array([g['poss'] - 49 for g in fit]); yf = np.array([g['h2'] - g['L'] for g in fit], float)
Xf = np.column_stack([np.ones(len(xf)), xf]); c, *_ = np.linalg.lstsq(Xf, yf, rcond=None)
print(f"   fit 2019-20 to 2020-21 (n {len(fit)}): miss vs line = {c[0]:+.2f} + {c[1]:+.3f} x (possessions - 49)")
xt = np.array([g['poss'] - 49 for g in test]); yt = np.array([g['h2'] for g in test], float); Lt = np.array([g['L'] for g in test])
for slope in (0.0, 0.15, 0.25, 0.35):
    f = Lt + slope * xt
    print(f"   slope {slope:.2f}: test (2021-22 to 2022-23, n {len(test)}) MAE {np.mean(np.abs(yt - f)):.3f}", end='')
    sel = np.abs(slope * xt) >= 1.0
    if sel.any():
        hits = np.mean([(yt[i] > Lt[i]) == (f[i] > Lt[i]) for i in range(len(yt)) if sel[i] and yt[i] != Lt[i]])
        print(f"  when the tilt is 1+ point (n {int(sel.sum())}): tilt side hits {100*hits:.1f}%", end='')
    print()
for lo, hi in [(0, 45), (45, 47), (47, 49), (49, 51), (51, 53), (53, 99)]:
    idx = [i for i, g in enumerate(test) if lo <= g['poss'] < hi]
    miss = yt[idx] - Lt[idx]
    print(f"   test poss {lo}-{hi}: n {len(idx):4d} miss {np.mean(miss):+5.2f} over {100*np.mean(miss>0)/max(1e-9,np.mean(miss!=0)):4.1f}%")
# and against the model-only center for the seasons without a line (2024-2026): the base model plus the tilt
late = [g for g in PG if g['season'] >= 2024]
yb = np.array([g['h2'] for g in late], float); mb3 = np.maximum(8, X_base(late) @ cb); xp = np.array([g['poss'] - 49 for g in late])
for slope in (0.0, 0.15, 0.25, 0.35):
    print(f"   2023-24 to 2025-26 (n {len(late)}), base model + {slope:.2f} x (poss - 49): MAE {np.mean(np.abs(yb - (mb3 + slope * xp))):.3f}")
