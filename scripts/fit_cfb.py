"""The FBS second-half fit, and the blowout refit (Build Plan week 3).

Reads data/cfb_games.csv (scripts/build_cfb_games.py) and prints:
  1. how the model in model.json misses by first-half points and by halftime margin (the blowout question:
     the desk said 32 second-half points for Texas State where history says about 20),
  2. the current shape refit on this data, and the refit with a running-clock term, each scored out of
     sample by season (leave one season out): mean miss by bucket, MAE, and the residual sd,
  3. with --write, the refit coefficients, k and residual quantiles into model.json's cfb block.

The running-clock term: once a game is out of hand the clock runs (the leading team sits on the ball, the
substitutes play, both sides run), so second-half points fall below what the pregame total and the first-half
pace say. The term is max(0, |halftime margin| - M) with M chosen on the data, on top of the shape the engine
already has (intercept, total, first-half points, |favorite margin|, favorite margin, spread when the favorite
trails). Nothing about the engine's shape changes; it gains one coefficient.

Usage: python scripts/fit_cfb.py data/cfb_games.csv [--write] [--knee 21]
"""
import sys, os, json, math, argparse
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
MODEL_PATH = os.path.join(ROOT, 'model.json')


def features(d, knee=None, pace=False):
    """The engine's regressors from a game table, plus the running-clock term when knee is given and a
    first-half pace term (points past 50) when pace is set."""
    home_fav_by = -d['home_spread']                  # minus spread = home favored by that much
    fav_by = home_fav_by.abs()
    m1 = d['h1h'] - d['h1a']
    favm = np.where(home_fav_by >= 0, m1, -m1)       # halftime margin from the favorite's side
    h1 = d['h1h'] + d['h1a']
    X = [np.ones(len(d)), d['total'].values, h1.values, np.abs(favm), favm, np.where(favm < 0, fav_by, 0)]
    if knee is not None:
        X.append(np.maximum(0, np.abs(m1.values) - knee))
    if pace:
        X.append(np.maximum(0, h1.values - 50))
    return np.column_stack(X)


def fit(X, y):
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return coef


def mu_of(coef, X):
    return np.maximum(8.0, X @ coef)


def buckets(d, resid, label):
    h1 = d['h1h'] + d['h1a']
    am = (d['h1h'] - d['h1a']).abs()
    print(f'\n{label}: mean miss (actual second-half points minus the model), by first-half points')
    for lo, hi in [(0, 20), (21, 34), (35, 48), (49, 59), (60, 69), (70, 200)]:
        m = (h1 >= lo) & (h1 <= hi)
        if m.sum():
            print(f'  {lo:>3}-{hi if hi < 200 else "":<3} n {m.sum():>5}  miss {resid[m].mean():+5.2f}  mae {np.abs(resid[m]).mean():5.2f}')
    print(f'{label}: by halftime margin')
    for lo, hi in [(0, 7), (8, 14), (15, 21), (22, 28), (29, 35), (36, 200)]:
        m = (am >= lo) & (am <= hi)
        if m.sum():
            print(f'  {lo:>3}-{hi if hi < 200 else "":<3} n {m.sum():>5}  miss {resid[m].mean():+5.2f}  mae {np.abs(resid[m]).mean():5.2f}')
    big = (am >= 22) | (h1 >= 60)
    print(f'{label}: blowout bucket (margin 22+ or 60+ first-half points) n {big.sum()} miss {resid[big].mean():+.2f} mae {np.abs(resid[big]).mean():.2f}; '
          f'the rest n {(~big).sum()} miss {resid[~big].mean():+.2f} mae {np.abs(resid[~big]).mean():.2f}; all mae {np.abs(resid).mean():.2f} sd {resid.std():.2f}')


class Loso:
    """A shape fit leave-one-season-out: residuals, mu and sd per game, and the training seasons' residual
    quantiles, so any threshold can be priced the way the engine prices a game (empirical z, not normal)."""

    def __init__(self, d, y, knee, pace=False):
        self.d, self.y = d, y
        self.resid = np.zeros(len(d))
        self.mu = np.zeros(len(d))
        self.sd = np.zeros(len(d))
        self.z = {}
        X = features(d, knee, pace)
        for s in sorted(d.season.unique()):
            tr, te = (d.season != s).values, (d.season == s).values
            coef = fit(X[tr], y[tr])
            mu_tr = mu_of(coef, X[tr])
            k = float(np.sqrt(np.mean((y[tr] - mu_tr) ** 2 / mu_tr)))
            self.z[s] = np.sort((y[tr] - mu_tr) / (k * np.sqrt(mu_tr)))
            self.mu[te] = mu_of(coef, X[te])
            self.sd[te] = k * np.sqrt(self.mu[te])
            self.resid[te] = y[te] - self.mu[te]

    def p_more(self, t):
        """P(second-half points > t) per game, t an array."""
        out = np.zeros(len(self.d))
        for s, z in self.z.items():
            te = (self.d.season == s).values
            out[te] = 1 - np.searchsorted(z, (t[te] - self.mu[te]) / self.sd[te], side='right') / len(z)
        return out

    def median(self):
        out = np.zeros(len(self.d))
        for s, z in self.z.items():
            te = (self.d.season == s).values
            out[te] = self.mu[te] + self.sd[te] * np.quantile(z, 0.5)
        return out


def pricing(d, y, fits, thresholds, label):
    """How each fit's out-of-sample P(over) at the given second-half thresholds lines up with what happened,
    overall and in blowouts. Pushes are left out, the way a market refunds them."""
    am = (d['h1h'] - d['h1a']).abs().values
    big = (am >= 22) | ((d.h1h + d.h1a).values >= 60)
    print(f'\n{label}')
    for name, m0 in [('all', np.ones(len(d), bool)), ('blowout', big), ('margin 29+', am >= 29), ('margin 36+', am >= 36)]:
        row = f'  {name:<11} n {m0.sum():>5}'
        for fname, f in fits.items():
            said = hit = brier = n = 0
            for t in thresholds:
                m = m0 & (y != t)
                over = (y[m] > t[m]).astype(float)
                p = f.p_more(t)[m]
                said += p.sum(); hit += over.sum(); brier += ((p - over) ** 2).sum(); n += m.sum()
            row += f'   {fname}: said {said / n:.3f} actual {hit / n:.3f} brier {brier / n:.4f}'
        print(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--knee', type=float, default=None, help='fix the running-clock knee instead of searching')
    a = ap.parse_args()
    d = pd.read_csv(a.path)
    d = d[(d.total > 20) & (d.total < 100) & (d.home_spread.abs() < 60)].reset_index(drop=True)
    y = ((d['fh'] + d['fa']) - (d['h1h'] + d['h1a'])).values.astype(float)   # second-half points, overtime included
    print(f'{len(d)} FBS games, {d.season.min()}-{d.season.max()}; second-half points mean {y.mean():.1f} sd {y.std():.1f}; '
          f'first-half mean {(d.h1h + d.h1a).mean():.1f}; overtime in {100 * d.ot.mean():.1f}%')

    # 1. the model as it stands (scored through the fitter's regressors, which engine_check holds to the engine)
    m = json.load(open(MODEL_PATH))['cfb']
    gap = engine_check(d)
    print(f'fitter against engine.HalfModel on 400 games: largest mu gap {gap:.6f}')
    assert gap < 1e-6, 'the fitter and the engine disagree; fix that before reading anything below'
    X0 = features(d, m.get('knee', 14) if len(m['coef']) > 6 else None)
    resid0 = y - mu_of(np.array(m['coef']), X0)
    buckets(d, resid0, 'model.json today')
    big = ((d['h1h'] - d['h1a']).abs() >= 22) | ((d.h1h + d.h1a) >= 60)
    print(f'  60+ first-half points (n {(d.h1h + d.h1a >= 60).sum()}): actual second half {y[(d.h1h + d.h1a >= 60).values].mean():.1f}, '
          f'model {mu_of(np.array(m["coef"]), X0)[(d.h1h + d.h1a >= 60).values].mean():.1f}')

    # 2. the same shape refit on this data, out of sample by season
    same = Loso(d, y, None)
    buckets(d, same.resid, 'same shape, refit (leave one season out)')

    # 3. the running-clock term: search the knee
    print('\nrunning-clock knee search (leave one season out):')
    runs = {}
    for knee in ([a.knee] if a.knee is not None else [7, 10, 14, 17, 21, 28]):
        runs[knee] = Loso(d, y, knee)
        r = runs[knee].resid
        print(f'  knee {knee:>4}: blowout mae {np.abs(r[big]).mean():.3f} miss {r[big].mean():+.2f}; all mae {np.abs(r).mean():.3f}')
    # two scores (14) is the plain reading of "out of hand"; another knee has to beat it by more than noise
    knee = a.knee if a.knee is not None else 14
    for k2, f in runs.items():
        if np.abs(f.resid).mean() < np.abs(runs[knee].resid).mean() - 0.01:
            knee = k2
    new = runs[knee]
    buckets(d, new.resid, f'with the running-clock term, knee {knee} (leave one season out)')

    # 4. a first-half pace term on top: does 60+ first-half points need its own term?
    pace = Loso(d, y, knee, pace=True)
    h1 = (d['h1h'] + d['h1a']).values
    print(f'\npace term max(0, h1 - 50) on top of the knee: 60+ bucket miss {pace.resid[h1 >= 60].mean():+.2f} '
          f'(knee alone {new.resid[h1 >= 60].mean():+.2f}); all mae {np.abs(pace.resid).mean():.3f} (knee alone {np.abs(new.resid).mean():.3f})')

    # 5. the gate that matters for money: out-of-sample P(over) at thresholds like the ones the desk prices.
    # model.json today is scored with its own quantiles (not out of sample: its 6,506 games overlap this table).
    class Today:
        def __init__(self):
            self.mu = mu_of(np.array(m['coef']), X0)
            self.sd = m['k'] * np.sqrt(self.mu)
            self.zq = np.array(m['z'])

        def p_more(self, t):
            return 1 - np.searchsorted(self.zq, (t - self.mu) / self.sd, side='right') / len(self.zq)

    fits = {'today': Today(), 'same shape': same, f'knee {knee}': new}
    need = (d['total'] - (d['h1h'] + d['h1a'])).values
    pricing(d, y, fits, [need], 'P(over the closing total) at the half (need = total - first-half points)')
    mkt = np.round(same.median() * 2) / 2                 # the market stand-in: a line at the plain model's median
    pricing(d, y, fits, [mkt], 'P(over a line at the plain refit median), the market stand-in')
    pricing(d, y, fits, [mkt - 4, mkt - 2, mkt + 2, mkt + 4], 'P(over) at that line -4, -2, +2, +4 (the rungs the desk prices)')

    # the in-sample fit for the file
    Xn = features(d, knee)
    coef = fit(Xn, y)
    mu = mu_of(coef, Xn)
    resid = y - mu
    z = resid / np.sqrt(mu)
    k = float(np.sqrt(np.mean(z ** 2)))
    zs = resid / (k * np.sqrt(mu))
    q = np.quantile(zs, np.linspace(0, 1, 201))
    names = ['intercept', 'total', 'h1', '|favm|', 'favm', 'fav_by if trailing', f'max(0, |margin|-{knee:g})']
    print('\nrefit coefficients:')
    for n, c in zip(names, coef):
        print(f'  {n:<24} {c:+.4f}')
    print(f'  k {k:.4f} (was {m["k"]}), n {len(d)}')
    ex = dict(total=55.5, h1h=38, h1a=24, home_spread=-7)          # Texas State-shaped: 62 first-half points, up 14
    for name, row in [('62 first-half points, favorite up 14', ex), ('a 45-10 half, favorite up 35', dict(total=55.5, h1h=45, h1a=10, home_spread=-7)),
                      ('a 14-10 half', dict(total=55.5, h1h=14, h1a=10, home_spread=-7))]:
        Xe = features(pd.DataFrame([row]), knee)
        old = mu_of(np.array(m['coef']), features(pd.DataFrame([row])))[0]
        print(f'  {name}: model today {old:.1f}, refit {mu_of(coef, Xe)[0]:.1f} second-half points')

    if a.write:
        full = json.load(open(MODEL_PATH))
        # ref (second-half points against the market's halftime line by state and spread bucket) stays: this
        # table has no halftime lines, and the engine only prints it
        full['cfb'].update(coef=[round(float(c), 4) for c in coef], k=round(k, 4), z=[round(float(v), 4) for v in q], n=int(len(d)), knee=knee,
                           fit=f'FBS {d.season.min()}-{d.season.max()} ({len(d)} games, cfbfastR play by play with finals checked against the '
                               f'schedules, CFBD closing lines, Pinnacle first); second-half points including overtime; running-clock term '
                               f'max(0, |halftime margin| - {knee:g}); study in claude/cfb-blowout-refit.md')
        json.dump(full, open(MODEL_PATH, 'w'), indent=1)
        print('model.json cfb block written')


def engine_check(d, n=400):
    """The fitter's regressors against the engine's own mu on games from the table: the two must agree, or the
    study is about a model the desk does not run (the bug class this guards against is a silent feature drift)."""
    import engine
    m = engine.MODEL['cfb']
    X = features(d, m.get('knee', 14) if len(m['coef']) > 6 else None)
    mu = mu_of(np.array(m['coef']), X)
    rows = d.sample(min(n, len(d)), random_state=1)
    worst = 0.0
    for i, r in rows.iterrows():
        e = engine.HalfModel('cfb', r.total, r.home_spread, int(r.h1h), int(r.h1a))
        worst = max(worst, abs(e.mu_model - mu[i]))
    return worst


if __name__ == '__main__':
    main()
