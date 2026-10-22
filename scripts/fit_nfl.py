"""The NFL second-half fit, the same study as scripts/fit_cfb.py on data/nfl_games.csv (scripts/build_nfl_games.py).

Prints how model.json's nfl block misses by first-half points, halftime margin, total, spread and season; refits
the engine's shape leave-one-season-out with and without the running-clock term max(0, |halftime margin| - knee);
prices P(over) out of sample at the closing total and at market-like lines. With --write, the refit goes into
model.json's nfl block (Nick's call: model changes are on the ask-before list).

Usage: python scripts/fit_nfl.py data/nfl_games.csv [--write] [--knee 14] [--since 2006]
"""
import sys, os, json, argparse
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_cfb import features, fit, mu_of, Loso, pricing
MODEL_PATH = os.path.join(ROOT, 'model.json')


def buckets(d, resid, label):
    h1 = d['h1h'] + d['h1a']
    am = (d['h1h'] - d['h1a']).abs()
    print(f'\n{label}: mean miss (actual second-half points minus the model)')
    print('  by first-half points')
    for lo, hi in [(0, 13), (14, 20), (21, 27), (28, 34), (35, 44), (45, 200)]:
        m = (h1 >= lo) & (h1 <= hi)
        if m.sum():
            print(f'    {lo:>3}-{hi if hi < 200 else "":<3} n {m.sum():>5}  miss {resid[m].mean():+5.2f}  mae {np.abs(resid[m]).mean():5.2f}')
    print('  by halftime margin')
    for lo, hi in [(0, 3), (4, 7), (8, 10), (11, 14), (15, 21), (22, 28), (29, 200)]:
        m = (am >= lo) & (am <= hi)
        if m.sum():
            print(f'    {lo:>3}-{hi if hi < 200 else "":<3} n {m.sum():>5}  miss {resid[m].mean():+5.2f}  mae {np.abs(resid[m]).mean():5.2f}')
    print('  by closing total')
    for lo, hi in [(0, 39.5), (40, 44.5), (45, 49.5), (50, 54.5), (55, 99)]:
        m = (d.total >= lo) & (d.total <= hi)
        if m.sum():
            print(f'    {lo:>4}-{hi:<4} n {m.sum():>5}  miss {resid[m].mean():+5.2f}  mae {np.abs(resid[m]).mean():5.2f}')
    print('  by spread')
    for lo, hi in [(0, 3), (3.5, 6.5), (7, 10), (10.5, 30)]:
        m = (d.home_spread.abs() >= lo) & (d.home_spread.abs() <= hi)
        if m.sum():
            print(f'    {lo:>4}-{hi:<4} n {m.sum():>5}  miss {resid[m].mean():+5.2f}  mae {np.abs(resid[m]).mean():5.2f}')
    fav = -d.home_spread
    m1 = d.h1h - d.h1a
    favm = np.where(fav >= 0, m1, -m1)
    print('  favorite trailing at the half')
    for lo, hi in [(-99, -11), (-10, -4), (-3, -1)]:
        m = (favm >= lo) & (favm <= hi)
        if m.sum():
            print(f'    favm {lo:>3}..{hi:<3} n {m.sum():>5}  miss {resid[m].mean():+5.2f}  mae {np.abs(resid[m]).mean():5.2f}')
    big = am >= 15
    print(f'  blowout (margin 15+) n {big.sum()} miss {resid[big].mean():+.2f} mae {np.abs(resid[big]).mean():.2f}; the rest n {(~big).sum()} '
          f'miss {resid[~big].mean():+.2f} mae {np.abs(resid[~big]).mean():.2f}; all mae {np.abs(resid).mean():.2f} sd {resid.std():.2f}')


def by_season(d, resid, label):
    print(f'\n{label} by season:')
    for s in sorted(d.season.unique()):
        m = (d.season == s).values
        print(f'  {s} n {m.sum():>3} miss {resid[m].mean():+5.2f}', end='')
        if s % 4 == 1:
            print()
    print()


def engine_check(d, n=400):
    import engine
    m = engine.MODEL['nfl']
    X = features(d, m.get('knee', 14) if len(m['coef']) > 6 else None)
    mu = mu_of(np.array(m['coef']), X)
    rows = d.sample(min(n, len(d)), random_state=1)
    worst = 0.0
    for i, r in rows.iterrows():
        e = engine.HalfModel('nfl', r.total, r.home_spread, int(r.h1h), int(r.h1a))
        worst = max(worst, abs(e.mu_model - mu[i]))
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--knee', type=float, default=None)
    ap.add_argument('--since', type=int, default=2006, help='first season in the fit')
    a = ap.parse_args()
    d = pd.read_csv(a.path)
    d = d[(d.season >= a.since) & (d.total > 20) & (d.total < 80) & (d.home_spread.abs() < 30)].reset_index(drop=True)
    y = ((d['fh'] + d['fa']) - (d['h1h'] + d['h1a'])).values.astype(float)
    print(f'{len(d)} NFL games, {d.season.min()}-{d.season.max()}; second-half points mean {y.mean():.1f} sd {y.std():.1f}; '
          f'first-half mean {(d.h1h + d.h1a).mean():.1f}; overtime in {100 * d.ot.mean():.1f}%')

    m = json.load(open(MODEL_PATH))['nfl']
    gap = engine_check(d)
    print(f'fitter against engine.HalfModel on 400 games: largest mu gap {gap:.6f}')
    assert gap < 1e-6, 'the fitter and the engine disagree; fix that before reading anything below'
    X0 = features(d, m.get('knee', 14) if len(m['coef']) > 6 else None)
    mu0 = mu_of(np.array(m['coef']), X0)
    resid0 = y - mu0
    buckets(d, resid0, 'model.json today')
    by_season(d, resid0, 'model.json today')
    big = ((d['h1h'] - d['h1a']).abs() >= 15).values

    same = Loso(d, y, None)
    buckets(d, same.resid, 'same shape, refit (leave one season out)')

    print('\nrunning-clock knee search (leave one season out):')
    runs = {}
    for knee in ([a.knee] if a.knee is not None else [7, 10, 14, 17, 21]):
        runs[knee] = Loso(d, y, knee)
        r = runs[knee].resid
        print(f'  knee {knee:>4}: blowout (15+) mae {np.abs(r[big]).mean():.3f} miss {r[big].mean():+.2f}; all mae {np.abs(r).mean():.3f}')
    knee = a.knee if a.knee is not None else 14
    for k2, f in runs.items():
        if np.abs(f.resid).mean() < np.abs(runs[knee].resid).mean() - 0.01:
            knee = k2
    new = runs[knee]
    buckets(d, new.resid, f'with the running-clock term, knee {knee} (leave one season out)')
    by_season(d, new.resid, f'knee {knee}')

    class Today:
        def __init__(self):
            self.mu = mu0
            self.sd = m['k'] * np.sqrt(self.mu)
            self.zq = np.array(m['z'])

        def p_more(self, t):
            return 1 - np.searchsorted(self.zq, (t - self.mu) / self.sd, side='right') / len(self.zq)

    fits = {'today': Today(), 'same shape': same, f'knee {knee}': new}
    need = (d['total'] - (d['h1h'] + d['h1a'])).values
    print('\n(blowout below means a halftime margin of 15 or more; margin 29+ and 36+ are as labeled)')
    pricing(d, y, fits, [need], 'P(over the closing total) at the half (need = total - first-half points)')
    mkt = np.round(same.median() * 2) / 2
    pricing(d, y, fits, [mkt], 'P(over a line at the plain refit median), the market stand-in')
    pricing(d, y, fits, [mkt - 3, mkt - 1.5, mkt + 1.5, mkt + 3], 'P(over) at that line -3, -1.5, +1.5, +3 (the rungs the desk prices)')

    Xn = features(d, knee)
    coef = fit(Xn, y)
    mu = mu_of(coef, Xn)
    resid = y - mu
    k = float(np.sqrt(np.mean(resid ** 2 / mu)))
    zs = resid / (k * np.sqrt(mu))
    q = np.quantile(zs, np.linspace(0, 1, 201))
    names = ['intercept', 'total', 'h1', '|favm|', 'favm', 'fav_by if trailing', f'max(0, |margin|-{knee:g})']
    print('\nrefit coefficients (in sample, for the file):')
    for nm, c in zip(names, coef):
        print(f'  {nm:<24} {c:+.4f}   (today {m["coef"][names.index(nm)]:+.4f})' if names.index(nm) < len(m['coef']) else f'  {nm:<24} {c:+.4f}')
    print(f'  k {k:.4f} (today {m["k"]}), n {len(d)} (today {m["n"]})')
    for name, row in [('a 17-14 half on 47.5', dict(total=47.5, h1h=17, h1a=14, home_spread=-3)),
                      ('a 31-7 half on 47.5, favorite up 24', dict(total=47.5, h1h=31, h1a=7, home_spread=-3)),
                      ('a 7-3 half on 41.5', dict(total=41.5, h1h=7, h1a=3, home_spread=-3)),
                      ('favorite by 7 down 17-3', dict(total=47.5, h1h=3, h1a=17, home_spread=-7))]:
        Xe = features(pd.DataFrame([row]), knee)
        old = mu_of(np.array(m['coef']), features(pd.DataFrame([row]), m.get('knee', 14) if len(m['coef']) > 6 else None))[0]
        print(f'  {name}: model today {old:.1f}, refit {mu_of(coef, Xe)[0]:.1f} second-half points')

    if a.write:
        full = json.load(open(MODEL_PATH))
        full['nfl'].update(coef=[round(float(c), 4) for c in coef], k=round(k, 4), z=[round(float(v), 4) for v in q], n=int(len(d)), knee=knee,
                           fit=f'NFL {d.season.min()}-{d.season.max()} ({len(d)} games, nflverse play by play, closing spread and total); '
                               f'second-half points including overtime; running-clock term max(0, |halftime margin| - {knee:g}); '
                               f'study in claude/nfl-refit.md')
        json.dump(full, open(MODEL_PATH, 'w'), indent=1)
        print('model.json nfl block written')


if __name__ == '__main__':
    main()
