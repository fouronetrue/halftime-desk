"""Fit the NBA second-half points model in the engine's shape and print the study behind it.

  python scripts/fit_nba.py data/nba_games.csv            # the report
  python scripts/fit_nba.py data/nba_games.csv --write    # also rewrite the "nba" block of model.json

Data: data/nba_games.csv, one row per game, 2007-08 through 2025-26 (24,437 games): halftime score, final,
overtime points, closing spread and total, and the market's second-half total line where the archive carried
one (2007-08 through early 2022-23). Built by scripts/build_nba_games.py from the Kaggle-format copy of the
sportsbookreviewsonline archive in github.com/manavgupta26012-code/nba-predictor (data/raw_data.csv); a
600-game sample checked exactly against the raw SBR 2018-19 file in github.com/davidbrodkey/nba_betting.
Needs numpy (not a watcher dependency; pip install numpy).

Sections A to H are the study: the game by season, overtime, fit windows, the model against the market's own
2H line, the spots Nick named, the final fit and its calibration, the value of one number in a middle, and the
reference table. The decisions they led to are written up in claude/nba-halftime.md.
"""
import csv, json, sys, math
import numpy as np

SRC = sys.argv[1]
rows = list(csv.DictReader(open(SRC)))
G = []
for r in rows:
    g = dict(date=r['date'], season=int(r['season']), playoffs=int(r['playoffs']), away=r['away'], home=r['home'],
             h1a=int(r['h1a']), h1h=int(r['h1h']), fa=int(r['fa']), fh=int(r['fh']), ota=int(r['ota']), oth=int(r['oth']),
             total=float(r['total']), home_spread=float(r['home_spread']),
             h2_total=float(r['h2_total']) if r['h2_total'] else None)
    g['h1'] = g['h1a'] + g['h1h']
    g['ft'] = g['fa'] + g['fh']
    g['h2'] = g['ft'] - g['h1']            # second-half points including overtime (what a full-game total settles on)
    g['ot'] = g['ota'] + g['oth']
    g['h2reg'] = g['h2'] - g['ot']
    home_fav_by = -g['home_spread']
    g['fav_by'] = abs(home_fav_by)
    m1 = g['h1h'] - g['h1a']
    g['favm'] = m1 if home_fav_by >= 0 else -m1   # favorite's halftime margin (home is the favorite on a pick)
    g['home_fav'] = home_fav_by > 0
    g['hm'] = m1                               # home halftime margin
    G.append(g)

def X_of(gs):
    return np.array([[1.0, g['total'], g['h1'], abs(g['favm']), g['favm'], (g['fav_by'] if g['favm'] < 0 else 0.0)] for g in gs])

def fit(gs):
    X = X_of(gs); y = np.array([g['h2'] for g in gs], float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    mu = np.maximum(8.0, X @ coef)
    res = y - mu
    k = math.sqrt(np.mean(res ** 2 / mu))
    z = res / (k * np.sqrt(mu))
    return coef, k, z, mu, res

def mu_of(coef, gs):
    return np.maximum(8.0, X_of(gs) @ coef)

def bucket(fb):
    return '0-3' if fb <= 3 else '3.5-7' if fb <= 7 else '7.5-10.5' if fb <= 10.5 else '11-14.5' if fb <= 14.5 else '15+'

P = print
P('=' * 78)
P('A. THE GAME, BY SEASON')
P('season  games  1H pts  2H pts  2H sd  2H/total  OT%  OT pts  total(line)')
by = {}
for g in G:
    by.setdefault(g['season'], []).append(g)
for s in sorted(by):
    gs = by[s]
    h1 = np.mean([g['h1'] for g in gs]); h2 = np.mean([g['h2'] for g in gs]); sd = np.std([g['h2'] for g in gs])
    ot = np.mean([g['ot'] > 0 for g in gs]); otp = np.mean([g['ot'] for g in gs if g['ot'] > 0]) if any(g['ot'] > 0 for g in gs) else 0
    tl = np.mean([g['total'] for g in gs])
    P(f"{s-1}-{str(s)[2:]}  {len(gs):5d}  {h1:6.1f}  {h2:6.1f}  {sd:5.1f}  {h2/(h1+h2):8.3f}  {100*ot:4.1f}  {otp:5.1f}  {tl:6.1f}")

P()
P('B. OVERTIME BY HALFTIME MARGIN (all seasons)')
P('|half margin|   n     OT%   mean OT pts when OT   2H pts (reg)  2H pts (with OT)')
for lo, hi in [(0, 0), (1, 3), (4, 6), (7, 9), (10, 14), (15, 19), (20, 99)]:
    gs = [g for g in G if lo <= abs(g['hm']) <= hi]
    ot = [g for g in gs if g['ot'] > 0]
    P(f"{lo:>2}-{hi:<4}        {len(gs):5d}  {100*len(ot)/len(gs):5.1f}  {np.mean([g['ot'] for g in ot]) if ot else 0:8.1f}            {np.mean([g['h2reg'] for g in gs]):6.1f}        {np.mean([g['h2'] for g in gs]):6.1f}")

P()
P('C. FIT WINDOWS (engine shape: 1, total, h1, |favm|, favm, fav_by if trailing). Test = 2024-25 and 2025-26.')
test = [g for g in G if g['season'] >= 2025]
for name, lo in [('all 2007-2024', 2008), ('2013-2024', 2013), ('2017-2024', 2017), ('2020-2024', 2020), ('2022-2024', 2022)]:
    train = [g for g in G if lo <= g['season'] <= 2024]
    coef, k, z, mu, res = fit(train)
    mt = mu_of(coef, test); yt = np.array([g['h2'] for g in test], float)
    P(f"{name:14s} n={len(train):5d}  coef={np.round(coef, 4).tolist()}  k={k:.3f}  train MAE {np.mean(np.abs(res)):.2f}  test MAE {np.mean(np.abs(yt - mt)):.2f}  test bias {np.mean(yt - mt):+.2f}")

P()
P('   Seasonal drift check for the 2017-2024 fit: mean residual by season')
coef, k, z, mu, res = fit([g for g in G if 2017 <= g['season'] <= 2024])
for s in sorted(by):
    gs = by[s]
    r = np.array([g['h2'] for g in gs]) - mu_of(coef, gs)
    P(f"   {s-1}-{str(s)[2:]}  {np.mean(r):+.2f}  (n {len(gs)})")

P()
P('D. THE MODEL VS THE MARKET 2H LINE (games with a 2H line, out of sample: fit on other seasons, score each season)')
P('   closer = share of games where the model fair is nearer the actual 2H points than the 2H line')
P('season   n    model MAE  market MAE  closer%  model bias  market bias   model-vs-line: over hit% when model>line+2 / under hit% when model<line-2')
allm = []
for s in sorted(by):
    gs = [g for g in by[s] if g['h2_total'] is not None]
    if len(gs) < 200:
        continue
    train = [g for g in G if g['season'] != s and abs(g['season'] - s) <= 6]
    c, kk, *_ = fit(train)
    m = mu_of(c, gs); y = np.array([g['h2'] for g in gs], float); L = np.array([g['h2_total'] for g in gs], float)
    em, el = np.abs(y - m), np.abs(y - L)
    closer = np.mean(em < el) + 0.5 * np.mean(em == el)
    ov = [(y[i] > L[i]) for i in range(len(gs)) if m[i] > L[i] + 2 and y[i] != L[i]]
    un = [(y[i] < L[i]) for i in range(len(gs)) if m[i] < L[i] - 2 and y[i] != L[i]]
    P(f"{s-1}-{str(s)[2:]} {len(gs):5d}  {np.mean(em):8.2f}  {np.mean(el):9.2f}  {100*closer:6.1f}  {np.mean(y-m):+9.2f}  {np.mean(y-L):+10.2f}    {100*np.mean(ov) if ov else 0:5.1f}% (n {len(ov)})  /  {100*np.mean(un) if un else 0:5.1f}% (n {len(un)})")
    allm += [(y[i], m[i], L[i], gs[i]) for i in range(len(gs))]
y = np.array([a[0] for a in allm]); m = np.array([a[1] for a in allm]); L = np.array([a[2] for a in allm])
P(f"pooled {len(allm)}: model MAE {np.mean(np.abs(y-m)):.2f}, market MAE {np.mean(np.abs(y-L)):.2f}, closer {100*(np.mean(np.abs(y-m)<np.abs(y-L))+0.5*np.mean(np.abs(y-m)==np.abs(y-L))):.1f}%")
P('   Blend test: fair = w*model + (1-w)*line')
for w in (0.0, 0.25, 0.5, 0.75, 1.0):
    f = w * m + (1 - w) * L
    P(f"   w={w:.2f}  MAE {np.mean(np.abs(y-f)):.3f}")
P('   Betting the model against the 2H line at -110 (needs 52.4%), by size of disagreement (model minus line):')
for lo, hi in [(1, 2), (2, 3), (3, 4), (4, 6), (6, 99)]:
    sel = [(y[i], L[i], m[i]) for i in range(len(y)) if lo <= abs(m[i] - L[i]) < hi and y[i] != L[i]]
    if not sel:
        continue
    wins = sum(1 for yy, ll, mm in sel if (yy > ll) == (mm > ll))
    P(f"   |diff| {lo}-{hi}: n {len(sel):5d}, model side hit {100*wins/len(sel):5.1f}%")

P()
P("E. NICK'S SPOTS vs the market 2H line (2007-2023) and the actual 2H points (all seasons)")
def spot(name, pred):
    gs = [g for g in G if pred(g)]
    gl = [g for g in gs if g['h2_total'] is not None]
    if not gs:
        P(f"{name:52s} n 0"); return
    h2 = np.mean([g['h2'] for g in gs])
    c, kk, *_ = fit([g for g in G if 2017 <= g['season'] <= 2024])
    resid = np.mean(np.array([g['h2'] for g in gs]) - mu_of(c, gs))
    if gl:
        d = np.array([g['h2'] - g['h2_total'] for g in gl])
        over = np.mean(d > 0) / max(1e-9, np.mean(d != 0))
        P(f"{name:52s} n {len(gs):5d}  2H pts {h2:6.1f}  model resid {resid:+5.2f} | vs 2H line: n {len(gl):5d} diff {np.mean(d):+5.2f} over {100*over:5.1f}%")
    else:
        P(f"{name:52s} n {len(gs):5d}  2H pts {h2:6.1f}  model resid {resid:+5.2f}")
P('--- home favorites (by spread) losing at the half')
for lo, hi in [(0.5, 3), (3.5, 7), (7.5, 10.5), (11, 14.5), (15, 99)]:
    spot(f"home fav by {lo}-{hi}, trailing at half", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and g['hm'] < 0)
    spot(f"   ... trailing by 1-5", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and -5 <= g['hm'] < 0)
    spot(f"   ... trailing by 6-10", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and -10 <= g['hm'] < -5)
    spot(f"   ... trailing by 11+", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and g['hm'] < -10)
P('--- home favorites winning at the half')
for lo, hi in [(0.5, 3), (3.5, 7), (7.5, 10.5), (11, 99)]:
    spot(f"home fav by {lo}-{hi}, leading at half", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and g['hm'] > 0)
    spot(f"   ... leading by 1-5", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and 0 < g['hm'] <= 5)
    spot(f"   ... leading by 6-12", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and 5 < g['hm'] <= 12)
    spot(f"   ... leading by 13+", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and g['hm'] > 12)
P('--- away favorites')
spot('away fav, trailing at half', lambda g: not g['home_fav'] and g['fav_by'] > 0 and g['hm'] > 0)
spot('away fav, leading at half', lambda g: not g['home_fav'] and g['fav_by'] > 0 and g['hm'] < 0)
P('--- home dogs')
spot('home dog, leading at half', lambda g: not g['home_fav'] and g['fav_by'] > 0 and g['hm'] > 0)
spot('home dog, trailing at half', lambda g: not g['home_fav'] and g['fav_by'] > 0 and g['hm'] < 0)
P('--- blowouts (either side), by halftime margin')
for lo, hi in [(15, 19), (20, 24), (25, 29), (30, 99)]:
    spot(f"half margin {lo}-{hi}", lambda g, lo=lo, hi=hi: lo <= abs(g['hm']) <= hi)
    spot(f"   ... favorite leading", lambda g, lo=lo, hi=hi: lo <= abs(g['hm']) <= hi and g['favm'] > 0)
    spot(f"   ... favorite trailing", lambda g, lo=lo, hi=hi: lo <= abs(g['hm']) <= hi and g['favm'] < 0)
P('--- close at the half')
spot('tied at half', lambda g: g['hm'] == 0)
spot('within 3 at half', lambda g: abs(g['hm']) <= 3)
P('--- first-half pace vs the pregame total (h1 minus total/2)')
for lo, hi in [(-99, -15), (-15, -8), (-8, -3), (-3, 3), (3, 8), (8, 15), (15, 99)]:
    spot(f"1H pts minus half the total in [{lo},{hi})", lambda g, lo=lo, hi=hi: lo <= g['h1'] - g['total'] / 2 < hi)
P('--- playoffs')
spot('playoff games', lambda g: g['playoffs'] == 1)
spot('regular season', lambda g: g['playoffs'] == 0)

P()
P('F. FINAL MODEL: fit on 2017-18 through 2025-26 (nine seasons)')
train = [g for g in G if g['season'] >= 2017]
coef, k, z, mu, res = fit(train)
P(f"n {len(train)} coef {np.round(coef, 4).tolist()} k {k:.4f} MAE {np.mean(np.abs(res)):.2f} sd of 2H {np.std([g['h2'] for g in train]):.2f} resid sd {np.std(res):.2f}")
zq = np.quantile(z, np.linspace(0, 1, 201))
P('z quantiles: min %.2f p5 %.2f p25 %.2f p50 %.2f p75 %.2f p95 %.2f max %.2f' % (zq[0], zq[10], zq[50], zq[100], zq[150], zq[190], zq[200]))
P('   calibration of P(2H points > line) at lines fair-9 ... fair+9 (in sample, by predicted-probability bin):')
def cdf(zq, zz):
    if zz <= zq[0]: return 0.0
    if zz >= zq[-1]: return 1.0
    hi = int(np.searchsorted(zq, zz, side='right')); lo = hi - 1
    f = (zz - zq[lo]) / ((zq[hi] - zq[lo]) or 1)
    return (lo + f) / (len(zq) - 1)
bins = {}
rng = np.random.default_rng(1)
for i, g in enumerate(train):
    for off in (-9, -6, -3, 0, 3, 6, 9):
        line = math.floor(mu[i]) + 0.5 + off
        p = 1 - cdf(zq, (math.floor(line) + 0.5 - mu[i]) / (k * math.sqrt(mu[i])))
        b = min(9, int(p * 10))
        bins.setdefault(b, []).append((p, g['h2'] > line))
for b in sorted(bins):
    v = bins[b]
    P(f"   pred {b/10:.1f}-{(b+1)/10:.1f}: n {len(v):6d}  mean pred {np.mean([x[0] for x in v]):.3f}  actual {np.mean([x[1] for x in v]):.3f}")
P('   calibration by spot (predicted vs actual over at the fair line +-3):')
for name, pred in [('favorite trailing', lambda g: g['favm'] < 0), ('favorite leading 1-9', lambda g: 0 < g['favm'] < 10),
                   ('favorite leading 10+', lambda g: g['favm'] >= 10), ('blowout 20+', lambda g: abs(g['hm']) >= 20), ('tied/within 2', lambda g: abs(g['hm']) <= 2),
                   ('playoffs', lambda g: g['playoffs'] == 1)]:
    pp, aa = [], []
    for i, g in enumerate(train):
        if not pred(g): continue
        for off in (-3, 0, 3):
            line = math.floor(mu[i]) + 0.5 + off
            pp.append(1 - cdf(zq, (math.floor(line) + 0.5 - mu[i]) / (k * math.sqrt(mu[i])))); aa.append(g['h2'] > line)
    P(f"   {name:22s} n {len(pp)//3:5d}  pred {np.mean(pp):.3f}  actual {np.mean(aa):.3f}  (diff {np.mean(aa)-np.mean(pp):+.3f})")

P()
P('G. VALUE OF ONE NUMBER IN A MIDDLE: P(2H points lands on a given number near fair)')
hits = []
for i, g in enumerate(train):
    hits.append(g['h2'] == round(mu[i]))
P(f"   P(2H points == round(fair)) = {100*np.mean(hits):.2f}%  (NFL rule 3.5c, CFB 2.4c)")
for off in (0, 3, 6, 9):
    h = [g['h2'] == round(mu[i]) + off for i, g in enumerate(train)]
    P(f"   number at fair{off:+d}: {100*np.mean(h):.2f}%")

# ref table like the football one: state|bucket -> n, diff (2H pts minus 2H line), rule (over share)
ref = {}
for g in G:
    if g['h2_total'] is None:
        continue
    st = 'trail' if g['favm'] < 0 else ('lead' if g['favm'] > 0 else 'tied')
    key = st + '|' + bucket(g['fav_by'])
    ref.setdefault(key, []).append(g['h2'] - g['h2_total'])
REF = {}
for key, d in ref.items():
    d = np.array(d)
    REF[key] = dict(n=int(len(d)), diff=round(float(np.mean(d)), 2), rule=round(float(np.mean(d > 0) / max(1e-9, np.mean(d != 0))), 3))
P()
P('H. REF TABLE (state|spread bucket: n, 2H pts minus 2H line, over share)')
for key in sorted(REF):
    P('  ', key, REF[key])

model = dict(coef=[round(float(c), 4) for c in coef], k=round(float(k), 4), z=[round(float(v), 4) for v in zq], n=len(train), ref=REF,
             fit='2017-18 to 2025-26 regular season and playoffs, second-half points including overtime, closing lines (SBR archive)')
if '--write' in sys.argv:
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model.json')
    full = json.load(open(path))
    full['nba'] = model
    with open(path, 'w') as f:
        json.dump(full, f, indent=0)
        f.write('\n')
    P('wrote the nba block of', path)
