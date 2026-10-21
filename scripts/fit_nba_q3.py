"""python scripts/fit_nba_q3.py (needs numpy). Fit the end-of-third-quarter model: points left to play (Q4 plus overtime) from the pregame total, the points
through three and the margin after three. Pooled quantiles vs an overtime mixture, calibrated by margin."""
import csv, math, json, sys, os
import numpy as np
rows = list(csv.DictReader(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'nba_games.csv'))))
G = []
for r in rows:
    g = dict(season=int(r['season']), total=float(r['total']), hs=float(r['home_spread']))
    q = {k: int(r[k]) for k in ('h1a', 'h1h', 'q3a', 'q3h', 'q4a', 'q4h', 'ota', 'oth')}
    g['thru3'] = q['h1a'] + q['h1h'] + q['q3a'] + q['q3h']; g['m3'] = (q['h1h'] + q['q3h']) - (q['h1a'] + q['q3a'])
    g['q4'] = q['q4a'] + q['q4h']; g['ot'] = q['ota'] + q['oth']; g['rem'] = g['q4'] + g['ot']
    G.append(g)
train = [g for g in G if g['season'] >= 2017]
def X(gs):
    return np.array([[1.0, g['total'], g['thru3'], abs(g['m3']), min(abs(g['m3']), 5.0)] for g in gs])
y = np.array([g['rem'] for g in train], float)
c, *_ = np.linalg.lstsq(X(train), y, rcond=None); mu = np.maximum(8.0, X(train) @ c); res = y - mu
k = math.sqrt(np.mean(res ** 2 / mu)); z = res / (k * np.sqrt(mu)); zq = np.quantile(z, np.linspace(0, 1, 201))
print('pooled: coef', np.round(c, 4).tolist(), 'k', round(k, 4), 'MAE', round(float(np.mean(np.abs(res))), 2), 'resid sd', round(float(res.std()), 2), 'n', len(train))
def cdf_q(q, zz):
    if zz <= q[0]: return 0.0
    if zz >= q[-1]: return 1.0
    hi = int(np.searchsorted(q, zz, side='right')); lo = hi - 1
    return (lo + (zz - q[lo]) / ((q[hi] - q[lo]) or 1)) / (len(q) - 1)
# regulation model + P(OT | margin after 3) + OT points
yr = np.array([g['q4'] for g in train], float)
cr, *_ = np.linalg.lstsq(X(train), yr, rcond=None); mur = np.maximum(8.0, X(train) @ cr); rr = yr - mur
kr = math.sqrt(np.mean(rr ** 2 / mur)); zr = rr / (kr * np.sqrt(mur)); zqr = np.quantile(zr, np.linspace(0, 1, 201))
m3 = np.array([abs(g['m3']) for g in train], float); isot = np.array([g['ot'] > 0 for g in train], float)
a, b = -2.0, -0.2
for _ in range(60):
    p = 1 / (1 + np.exp(-(a + b * m3))); w = p * (1 - p)
    g1 = np.array([np.sum(isot - p), np.sum((isot - p) * m3)]); H = np.array([[np.sum(w), np.sum(w * m3)], [np.sum(w * m3), np.sum(w * m3 * m3)]])
    da, db = np.linalg.solve(H, g1); a += da; b += db
otp = np.array([g['ot'] for g in train if g['ot'] > 0], float)
print(f"regulation Q4: coef {np.round(cr, 4).tolist()} k {kr:.4f}; P(OT) = logistic({a:.3f} + {b:.4f} x |margin after 3|); OT points mean {otp.mean():.1f} sd {otp.std():.1f}")
for m in (0, 2, 5, 8, 12, 16):
    print(f"   |margin| {m:2d}: P(OT) {100/(1+math.exp(-(a + b*m))):.1f}%  actual {100*np.mean([g['ot']>0 for g in train if abs(g['m3'])==m or (m==16 and abs(g['m3'])>=16)]):.1f}%")
def mix_cdf(x, mu_r, sd_r, p):
    return (1 - p) * cdf_q(zqr, (x - mu_r) / sd_r) + p * cdf_q(zqr, (x - otp.mean() - mu_r) / sd_r)
def mix_median(mu_r, sd_r, p):
    lo, hi = mu_r - 40, mu_r + 60
    for _ in range(40):
        mid = (lo + hi) / 2
        if mix_cdf(mid, mu_r, sd_r, p) < 0.5: lo = mid
        else: hi = mid
    return (lo + hi) / 2
print('\ncalibration P(remaining > line) at the model median + off, predicted / actual, pooled vs mixture:')
spots = [('close 0-5', lambda g: abs(g['m3']) <= 5), ('mid 6-14', lambda g: 6 <= abs(g['m3']) <= 14), ('blowout 15+', lambda g: abs(g['m3']) >= 15)]
sdp = k * np.sqrt(mu); sdr = kr * np.sqrt(mur); pot = 1 / (1 + np.exp(-(a + b * m3)))
for name, pred in spots:
    idx = [i for i, g in enumerate(train) if pred(g)]
    line = []
    for off in (-10, -5, 0, 5, 10, 15, 20):
        pp, ap, pm, am = [], [], [], []
        for i in idx:
            medp = mu[i] + sdp[i] * zq[100]; L = math.floor(medp) + 0.5 + off
            pp.append(1 - cdf_q(zq, (L - mu[i]) / sdp[i])); ap.append(train[i]['rem'] > L)
            medm = mix_median(mur[i], sdr[i], pot[i]); Lm = math.floor(medm) + 0.5 + off
            pm.append(1 - mix_cdf(Lm, mur[i], sdr[i], pot[i])); am.append(train[i]['rem'] > Lm)
        line.append(f"{off:+d}: {100*np.mean(pp):4.1f}/{100*np.mean(ap):4.1f} | {100*np.mean(pm):4.1f}/{100*np.mean(am):4.1f}")
    print(f"   {name:12s} n {len(idx):5d}  " + '  '.join(line))
print('\nwindow hit rates (numbers strictly inside two strikes w apart centered on the median), predicted/actual, pooled vs mixture:')
for name, pred in spots:
    idx = [i for i, g in enumerate(train) if pred(g)]
    out = []
    for w in (4, 6, 8):
        pp, ap, pm, am = [], [], [], []
        for i in idx:
            medp = mu[i] + sdp[i] * zq[100]; lo = math.floor(medp) + 0.5 - w / 2; hi = lo + w
            pp.append(cdf_q(zq, (hi - mu[i]) / sdp[i]) - cdf_q(zq, (lo - mu[i]) / sdp[i])); ap.append(lo < train[i]['rem'] < hi)
            medm = mix_median(mur[i], sdr[i], pot[i]); lo2 = math.floor(medm) + 0.5 - w / 2; hi2 = lo2 + w
            pm.append(mix_cdf(hi2, mur[i], sdr[i], pot[i]) - mix_cdf(lo2, mur[i], sdr[i], pot[i])); am.append(lo2 < train[i]['rem'] < hi2)
        out.append(f"{w}-wide {100*np.mean(pp):4.1f}/{100*np.mean(ap):4.1f} | {100*np.mean(pm):4.1f}/{100*np.mean(am):4.1f}")
    print(f"   {name:12s} " + '   '.join(out))
json.dump(dict(pooled=dict(coef=[round(float(v), 4) for v in c], k=round(k, 4), z=[round(float(v), 4) for v in zq], n=len(train)),
               mix=dict(coef=[round(float(v), 4) for v in cr], k=round(kr, 4), z=[round(float(v), 4) for v in zqr], ot_a=round(a, 4), ot_b=round(b, 4), ot_pts=round(float(otp.mean()), 1), n=len(train))),
          open(sys.argv[1] if len(sys.argv) > 1 else 'q3_models.json', 'w'))
print('the nba_q3 block in model.json uses the mix fit with an empirical P(OT) table by |margin after three| (see claude/nba-halftime.md, section 15)')
