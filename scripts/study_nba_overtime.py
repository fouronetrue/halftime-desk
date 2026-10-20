"""An overtime mixture for the NBA: regulation second-half model + P(OT | halftime margin) + OT points.
Does it price middle windows better than the pooled model in close games and blowouts?"""
import csv, math, json, os
import numpy as np
rows = list(csv.DictReader(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'nba_games.csv'))))
G = []
for r in rows:
    g = dict(season=int(r['season']), h1a=int(r['h1a']), h1h=int(r['h1h']), fa=int(r['fa']), fh=int(r['fh']),
             ot=int(r['ota']) + int(r['oth']), total=float(r['total']), home_spread=float(r['home_spread']))
    g['h1'] = g['h1a'] + g['h1h']; g['h2'] = g['fa'] + g['fh'] - g['h1']; g['h2reg'] = g['h2'] - g['ot']
    g['hm'] = abs(g['h1h'] - g['h1a'])
    hfb = -g['home_spread']; g['fav_by'] = abs(hfb); m1 = g['h1h'] - g['h1a']; g['favm'] = m1 if hfb >= 0 else -m1
    G.append(g)
train = [g for g in G if g['season'] >= 2017]
X = lambda gs: np.array([[1.0, g['total'], g['h1'], abs(g['favm']), g['favm'], (g['fav_by'] if g['favm'] < 0 else 0.0)] for g in gs])

# 1. regulation model
y = np.array([g['h2reg'] for g in train], float)
cr, *_ = np.linalg.lstsq(X(train), y, rcond=None)
mur = np.maximum(8.0, X(train) @ cr); res = y - mur
kr = math.sqrt(np.mean(res ** 2 / mur)); zr = res / (kr * np.sqrt(mur)); zq = np.quantile(zr, np.linspace(0, 1, 201))
print('regulation 2H: coef', np.round(cr, 4).tolist(), 'k', round(kr, 4), 'MAE', round(float(np.mean(np.abs(res))), 2))

# 2. P(OT) as a logistic in |halftime margin| (2013 on; by-bucket check)
OT = [g for g in G if g['season'] >= 2013]
hm = np.array([g['hm'] for g in OT], float); isot = np.array([g['ot'] > 0 for g in OT], float)
# fit by Newton on a,b
a, b = -2.5, -0.05
for _ in range(50):
    p = 1 / (1 + np.exp(-(a + b * hm)))
    g1 = np.array([np.sum(isot - p), np.sum((isot - p) * hm)])
    w = p * (1 - p)
    H = np.array([[np.sum(w), np.sum(w * hm)], [np.sum(w * hm), np.sum(w * hm * hm)]])
    da, db = np.linalg.solve(H, g1); a += da; b += db
print(f"P(OT) = 1/(1+exp(-({a:.3f} + {b:.4f} x |margin|)))")
for lo, hi in [(0, 2), (3, 5), (6, 9), (10, 14), (15, 19), (20, 24), (25, 99)]:
    sel = (hm >= lo) & (hm <= hi)
    print(f"   |margin| {lo}-{hi}: n {int(sel.sum()):5d}  actual {100*isot[sel].mean():4.1f}%  fitted {100*(1/(1+np.exp(-(a + b*hm[sel])))).mean():4.1f}%")
otp = np.array([g['ot'] for g in OT if g['ot'] > 0], float)
print(f"OT points when OT: mean {otp.mean():.1f} sd {otp.std():.1f}  (double OT and more: {100*np.mean(otp > 36):.1f}%)")
ot_pts = float(otp.mean())

# 3. the mixture vs the pooled model: calibration at fair+k and window hit rates by spot
pooled = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model.json')))['nba']
def cdf_q(q, zz):
    if zz <= q[0]: return 0.0
    if zz >= q[-1]: return 1.0
    hi = int(np.searchsorted(q, zz, side='right')); lo = hi - 1
    f = (zz - q[lo]) / ((q[hi] - q[lo]) or 1)
    return (lo + f) / (len(q) - 1)
def mix_cdf(x, mu_r, sd_r, p):
    return (1 - p) * cdf_q(zq, (x - mu_r) / sd_r) + p * cdf_q(zq, (x - ot_pts - mu_r) / sd_r)
Xp = X(train)
mup = np.maximum(8.0, Xp @ np.array(pooled['coef'])); sdp = pooled['k'] * np.sqrt(mup); zp = np.array(pooled['z'])
sdr = kr * np.sqrt(mur)
pot = 1 / (1 + np.exp(-(a + b * np.array([g['hm'] for g in train], float))))
def median_mix(mu_r, sd_r, p):
    lo, hi = mu_r - 40, mu_r + 60
    for _ in range(40):
        mid = (lo + hi) / 2
        if mix_cdf(mid, mu_r, sd_r, p) < 0.5: lo = mid
        else: hi = mid
    return (lo + hi) / 2
print('\nwindow hit rates: predicted (pooled / mixture) vs actual, numbers strictly inside two strikes w apart centered at each model\'s median')
spots = [('close 0-5', lambda g: g['hm'] <= 5), ('mid 6-14', lambda g: 6 <= g['hm'] <= 14), ('blowout 15+', lambda g: g['hm'] >= 15), ('blowout 20+', lambda g: g['hm'] >= 20)]
for name, pred in spots:
    idx = [i for i, g in enumerate(train) if pred(g)]
    out = []
    for w in (4, 6, 8):
        pp, pm, aa_p, aa_m = [], [], [], []
        for i in idx:
            h2 = train[i]['h2']
            medp = mup[i] + sdp[i] * zp[100]; lo_p = math.floor(medp) + 0.5 - w / 2; hi_p = lo_p + w
            pp.append(cdf_q(zp, (hi_p - mup[i]) / sdp[i]) - cdf_q(zp, (lo_p - mup[i]) / sdp[i])); aa_p.append(lo_p < h2 < hi_p)
            medm = median_mix(mur[i], sdr[i], pot[i]); lo_m = math.floor(medm) + 0.5 - w / 2; hi_m = lo_m + w
            pm.append(mix_cdf(hi_m, mur[i], sdr[i], pot[i]) - mix_cdf(lo_m, mur[i], sdr[i], pot[i])); aa_m.append(lo_m < h2 < hi_m)
        out.append(f"{w}-wide pooled {100*np.mean(pp):4.1f}/{100*np.mean(aa_p):4.1f}  mix {100*np.mean(pm):4.1f}/{100*np.mean(aa_m):4.1f}")
    print(f"   {name:12s} n {len(idx):5d}  " + '   '.join(out))
print('\nupper tail by spot: P(2H > median + 15) and +20, predicted pooled / mixture vs actual')
for name, pred in spots:
    idx = [i for i, g in enumerate(train) if pred(g)]
    out = []
    for off in (10, 15, 20):
        pp, pm, aa_p, aa_m = [], [], [], []
        for i in idx:
            h2 = train[i]['h2']
            medp = mup[i] + sdp[i] * zp[100]; L = math.floor(medp) + 0.5 + off
            pp.append(1 - cdf_q(zp, (L - mup[i]) / sdp[i])); aa_p.append(h2 > L)
            medm = median_mix(mur[i], sdr[i], pot[i]); Lm = math.floor(medm) + 0.5 + off
            pm.append(1 - mix_cdf(Lm, mur[i], sdr[i], pot[i])); aa_m.append(h2 > Lm)
        out.append(f"+{off}: pooled {100*np.mean(pp):4.1f}/{100*np.mean(aa_p):4.1f}  mix {100*np.mean(pm):4.1f}/{100*np.mean(aa_m):4.1f}")
    print(f"   {name:12s} " + '   '.join(out))
