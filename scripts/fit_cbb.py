"""Fit the college basketball second-half points model in the engine's shape and print the study behind it.

  python scripts/fit_cbb.py data/cbb_games.csv            # the report
  python scripts/fit_cbb.py data/cbb_games.csv --write    # also rewrite the "cbb" block of model.json

Data: data/cbb_games.csv, one row per lined game, 2007-08 through 2023-24 (63,329 games): the halftime score,
the final, the closing total and spread, and the market's second-half total where the SBR archive carried one
(2007-08 through 2010-11). Built by scripts/build_cbb_games.py (ESPN schedules and play by play from hoopR,
closing lines from covers.com via zachmayer/point_spreads, the SBR archive for the early years).
Needs numpy (not a watcher dependency; pip install numpy).

Sections A to H are the study: the game by season (the 30-second shot clock arrived in 2015-16), overtime, fit
windows, the model against the market's own 2H line, the spots, the final fit and its calibration, the value of
one number in a middle, and the reference table. The decisions they led to are written up in
claude/cbb-halftime.md.
"""
import csv, json, sys, math, collections
import numpy as np

SRC = sys.argv[1]
G = []
for r in csv.DictReader(open(SRC)):
    try:
        g = dict(date=r['date'], season=int(r['season']), post=1 if r.get('season_type') == '3' else 0, neutral=int(r['neutral'] or 0),
                 away=r['away'], home=r['home'], h1a=int(r['h1a']), h1h=int(r['h1h']), fa=int(r['fa']), fh=int(r['fh']),
                 ot=int(r['ot']) if r['ot'] not in ('', None) else None, total=float(r['total']),
                 home_spread=float(r['home_spread']) if r['home_spread'] not in ('', None) else None,
                 h2_total=float(r['h2_total']) if r['h2_total'] not in ('', None) else None, source=r['source'])
    except (ValueError, KeyError):
        continue
    if g['home_spread'] is None:
        continue
    g['h1'] = g['h1a'] + g['h1h']
    g['ft'] = g['fa'] + g['fh']
    g['h2'] = g['ft'] - g['h1']            # second-half points including overtime (what a full-game total settles on)
    if g['h2'] < 20 or g['h1'] < 20 or g['total'] < 100 or g['total'] > 200:
        continue
    home_fav_by = -g['home_spread']
    g['fav_by'] = abs(home_fav_by)
    m1 = g['h1h'] - g['h1a']
    g['favm'] = m1 if home_fav_by >= 0 else -m1   # favorite's halftime margin (home is the favorite on a pick)
    g['home_fav'] = home_fav_by > 0
    g['hm'] = m1
    G.append(g)
print(f'{len(G)} games with a total, a spread and a half score')


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
P('A. THE GAME, BY SEASON (season = the year it ends; 2016 is the first with the 30-second shot clock)')
P('season  games  1H pts  2H pts  2H sd  2H/total  OT%   total(line)  final-line  source')
by = {}
for g in G:
    by.setdefault(g['season'], []).append(g)
for s in sorted(by):
    gs = by[s]
    h1 = np.mean([g['h1'] for g in gs]); h2 = np.mean([g['h2'] for g in gs]); sd = np.std([g['h2'] for g in gs])
    ot = np.mean([(g['ot'] or 0) > 0 for g in gs if g['ot'] is not None]) if any(g['ot'] is not None for g in gs) else float('nan')
    tl = np.mean([g['total'] for g in gs]); d = np.mean([g['ft'] - g['total'] for g in gs])
    src = collections.Counter(g['source'] for g in gs).most_common(1)[0][0]
    P(f"{s-1}-{str(s)[2:]}  {len(gs):5d}  {h1:6.1f}  {h2:6.1f}  {sd:5.1f}  {h2/(h1+h2):8.3f}  {100*ot:4.1f}  {tl:9.1f}  {d:+9.2f}  {src}")

P()
P('B. OVERTIME BY HALFTIME MARGIN (seasons with the points by period)')
P('|half margin|   n     OT%   2H pts')
GO = [g for g in G if g['ot'] is not None]
for lo, hi in [(0, 0), (1, 3), (4, 6), (7, 9), (10, 14), (15, 19), (20, 99)]:
    gs = [g for g in GO if lo <= abs(g['hm']) <= hi]
    if not gs:
        continue
    P(f"{lo:>2}-{hi:<4}        {len(gs):5d}  {100*np.mean([g['ot'] > 0 for g in gs]):5.1f}  {np.mean([g['h2'] for g in gs]):6.1f}")

P()
P('C. FIT WINDOWS (engine shape: 1, total, h1, |favm|, favm, fav_by if trailing). Test = 2022-23 and 2023-24.')
test = [g for g in G if g['season'] >= 2023]
for name, lo in [('all 2008-2022', 2008), ('2012-2022', 2012), ('2016-2022', 2016), ('2019-2022', 2019)]:
    train = [g for g in G if lo <= g['season'] <= 2022]
    coef, k, z, mu, res = fit(train)
    mt = mu_of(coef, test); yt = np.array([g['h2'] for g in test], float)
    P(f"{name:14s} n={len(train):5d}  coef={np.round(coef, 4).tolist()}  k={k:.3f}  train MAE {np.mean(np.abs(res)):.2f}  test MAE {np.mean(np.abs(yt - mt)):.2f}  test bias {np.mean(yt - mt):+.2f}")
P('   naive (half the closing total, no game state): test MAE %.2f' % np.mean(np.abs(np.array([g['h2'] - g['total'] / 2 for g in test]))))
P('   the market line as the 2H number (total minus first-half points): test MAE %.2f, bias %+.2f' % (
    np.mean(np.abs(np.array([g['h2'] - (g['total'] - g['h1']) for g in test]))), np.mean(np.array([g['h2'] - (g['total'] - g['h1']) for g in test]))))

P()
P('   Seasonal drift check for the 2016-2022 fit: mean residual by season (SE)')
coef, k, z, mu, res = fit([g for g in G if 2016 <= g['season'] <= 2022])
for s in sorted(by):
    gs = by[s]
    r = np.array([g['h2'] for g in gs]) - mu_of(coef, gs)
    P(f"   {s-1}-{str(s)[2:]}  {np.mean(r):+.2f} ({np.std(r)/math.sqrt(len(r)):.2f})  (n {len(gs)})")

P()
P('D. THE MODEL VS THE MARKET 2H LINE (SBR seasons with a 2H line; fit on the other seasons of the same era)')
P('   closer = share of games where the model fair is nearer the actual 2H points than the 2H line')
P('season   n    model MAE  market MAE  closer%  model bias  market bias')
allm = []
for s in sorted(by):
    gs = [g for g in by[s] if g['h2_total'] is not None and abs(g['h2_total'] - g['total'] / 2) < 20]
    if len(gs) < 200:
        continue
    train = [g for g in G if g['season'] != s and g['season'] <= 2015]   # the same shot-clock era
    c, kk, *_ = fit(train)
    m = mu_of(c, gs); y = np.array([g['h2'] for g in gs], float); L = np.array([g['h2_total'] for g in gs], float)
    em, el = np.abs(y - m), np.abs(y - L)
    closer = np.mean(em < el) + 0.5 * np.mean(em == el)
    P(f"{s-1}-{str(s)[2:]} {len(gs):5d}  {np.mean(em):8.2f}  {np.mean(el):9.2f}  {100*closer:6.1f}  {np.mean(y-m):+9.2f}  {np.mean(y-L):+10.2f}")
    allm += [(y[i], m[i], L[i], gs[i]) for i in range(len(gs))]
if allm:
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
    P('   The market 2H line vs the naive one (closing total minus the first-half points): mean diff %+.2f, |diff| %.2f' % (
        np.mean(L - np.array([a[3]['total'] - a[3]['h1'] for a in allm])), np.mean(np.abs(L - np.array([a[3]['total'] - a[3]['h1'] for a in allm])))))

P()
P("E. SPOTS vs the model (2016-2022 fit) and vs the 2H line where there is one")
c16, kk16, *_ = fit([g for g in G if 2016 <= g['season'] <= 2022])


def spot(name, pred, era=None):
    gs = [g for g in G if pred(g) and (era is None or g['season'] >= era)]
    gl = [g for g in gs if g['h2_total'] is not None]
    if not gs:
        P(f"{name:52s} n 0"); return
    h2 = np.mean([g['h2'] for g in gs])
    resid = np.mean(np.array([g['h2'] for g in gs]) - mu_of(c16, gs))
    se = np.std(np.array([g['h2'] for g in gs]) - mu_of(c16, gs)) / math.sqrt(len(gs))
    line = ''
    if gl:
        d = np.array([g['h2'] - g['h2_total'] for g in gl])
        over = np.mean(d > 0) / max(1e-9, np.mean(d != 0))
        line = f" | vs 2H line: n {len(gl):5d} diff {np.mean(d):+5.2f} over {100*over:5.1f}%"
    P(f"{name:52s} n {len(gs):5d}  2H pts {h2:6.1f}  model resid {resid:+5.2f} ({se:.2f}){line}")


P('--- home favorites (by spread) losing at the half')
for lo, hi in [(0.5, 3), (3.5, 7), (7.5, 10.5), (11, 14.5), (15, 99)]:
    spot(f"home fav by {lo}-{hi}, trailing at half", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and g['hm'] < 0)
P('--- home favorites winning at the half')
for lo, hi in [(0.5, 3), (3.5, 7), (7.5, 10.5), (11, 99)]:
    spot(f"home fav by {lo}-{hi}, leading at half", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and g['hm'] > 0)
P('--- away favorites and home dogs')
spot('away fav, trailing at half', lambda g: not g['home_fav'] and g['fav_by'] > 0 and g['hm'] > 0)
spot('away fav, leading at half', lambda g: not g['home_fav'] and g['fav_by'] > 0 and g['hm'] < 0)
P('--- blowouts (either side), by halftime margin')
for lo, hi in [(15, 19), (20, 24), (25, 29), (30, 99)]:
    spot(f"half margin {lo}-{hi}", lambda g, lo=lo, hi=hi: lo <= abs(g['hm']) <= hi)
    spot(f"   ... favorite leading", lambda g, lo=lo, hi=hi: lo <= abs(g['hm']) <= hi and g['favm'] > 0)
    spot(f"   ... favorite trailing", lambda g, lo=lo, hi=hi: lo <= abs(g['hm']) <= hi and g['favm'] < 0)
P('--- close at the half')
spot('tied at half', lambda g: g['hm'] == 0)
spot('within 3 at half', lambda g: abs(g['hm']) <= 3)
P('--- first-half pace vs the pregame total (h1 minus total/2)')
for lo, hi in [(-99, -12), (-12, -6), (-6, -2), (-2, 2), (2, 6), (6, 12), (12, 99)]:
    spot(f"1H pts minus half the total in [{lo},{hi})", lambda g, lo=lo, hi=hi: lo <= g['h1'] - g['total'] / 2 < hi)
P('--- site, post season, big spreads')
spot('neutral site', lambda g: g['neutral'] == 1)
spot('home site', lambda g: g['neutral'] == 0)
spot('postseason', lambda g: g['post'] == 1)
spot('spread 20+ (mismatch)', lambda g: g['fav_by'] >= 20)
spot('spread 20+, favorite up 20+ at the half', lambda g: g['fav_by'] >= 20 and g['favm'] >= 20)
spot('spread 20+, favorite up under 10 at the half', lambda g: g['fav_by'] >= 20 and g['favm'] < 10)

P()
P('F. FINAL MODEL: fit on 2015-16 through 2023-24 (the 30-second shot clock seasons)')
train = [g for g in G if g['season'] >= 2016]
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
                   ('neutral site', lambda g: g['neutral'] == 1), ('spread 20+', lambda g: g['fav_by'] >= 20), ('high total 160+', lambda g: g['total'] >= 160),
                   ('low total under 130', lambda g: g['total'] < 130)]:
    pp, aa = [], []
    for i, g in enumerate(train):
        if not pred(g): continue
        for off in (-3, 0, 3):
            line = math.floor(mu[i]) + 0.5 + off
            pp.append(1 - cdf(zq, (math.floor(line) + 0.5 - mu[i]) / (k * math.sqrt(mu[i])))); aa.append(g['h2'] > line)
    P(f"   {name:22s} n {len(pp)//3:5d}  pred {np.mean(pp):.3f}  actual {np.mean(aa):.3f}  (diff {np.mean(aa)-np.mean(pp):+.3f})")

P()
P('G. VALUE OF ONE NUMBER IN A MIDDLE: P(2H points lands on a given number near fair)')
hits = [g['h2'] == round(mu[i]) for i, g in enumerate(train)]
P(f"   P(2H points == round(fair)) = {100*np.mean(hits):.2f}%  (NFL rule 3.5c, CFB 2.4c, NBA 2.9c)")
for off in (0, 3, 6, 9):
    h = [g['h2'] == round(mu[i]) + off for i, g in enumerate(train)]
    P(f"   number at fair{off:+d}: {100*np.mean(h):.2f}%")

# ref table like the football one: state|bucket -> n, diff (2H pts minus the model's fair), rule (over share);
# the SBR 2H lines are too old (35-second clock) to anchor the table, so the model's own fair is the reference
ref = {}
for i, g in enumerate(train):
    st = 'trail' if g['favm'] < 0 else ('lead' if g['favm'] > 0 else 'tied')
    key = st + '|' + bucket(g['fav_by'])
    ref.setdefault(key, []).append(g['h2'] - round(mu[i]))
REF = {}
for key, d in ref.items():
    d = np.array(d)
    REF[key] = dict(n=int(len(d)), diff=round(float(np.mean(d)), 2), rule=round(float(np.mean(d > 0) / max(1e-9, np.mean(d != 0))), 3))
P()
P("H. REF TABLE (state|spread bucket: n, 2H pts minus the model's fair, over share)")
for key in sorted(REF):
    P('  ', key, REF[key])

model = dict(coef=[round(float(c), 4) for c in coef], k=round(float(k), 4), z=[round(float(v), 4) for v in zq], n=len(train), ref=REF,
             fit='men\'s college basketball 2015-16 to 2023-24 (the 30-second shot clock seasons), second-half points including overtime, '
                 'closing lines from covers.com (and the SBR archive); scripts/build_cbb_games.py, study in claude/cbb-halftime.md')
def dump(obj, f, level=0):
    """model.json's layout: one key a line, indented a space a level, every list on one line, a dict of plain
    numbers (a ref table row) on one line."""
    pad = ' ' * level
    if isinstance(obj, dict) and all(not isinstance(v, (dict, list)) for v in obj.values()) and level > 0:
        f.write('{' + ', '.join(f'{json.dumps(k)}: {json.dumps(v)}' for k, v in obj.items()) + '}')
    elif isinstance(obj, dict):
        f.write('{\n')
        items = list(obj.items())
        for i, (k, v) in enumerate(items):
            f.write(f'{pad} {json.dumps(k)}: ')
            dump(v, f, level + 1)
            f.write(',\n' if i < len(items) - 1 else '\n')
        f.write(pad + '}')
    else:
        f.write(json.dumps(obj))


if '--write' in sys.argv:
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model.json')
    full = json.load(open(path))
    full['cbb'] = model
    with open(path, 'w') as f:
        dump(full, f)
        f.write('\n')
    P('wrote the cbb block of', path)
