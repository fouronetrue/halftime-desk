"""Drift monitor (Roadmap v2, study S1): is each block still right season by season, and when would a recency
window beat all seasons?

For every sport with a game table, the model block in model.json is scored on every season it has: the mean
miss (actual second-half points minus the model), its standard error, and the z-score. A season past 2 SE is
flagged. The standing rule for recency: when the latest two seasons both sit past 2 SE on the same side, the
windows (the last 3, 5 and 8 seasons) are fit without the latest season and scored on it against the fit on all
earlier seasons, at the rungs the desk prices (the plain refit median and -4, -2, +2, +4). A window is adopted
only when it beats all-seasons on that held-out season; otherwise all seasons stays. Nothing is written without
--write, and a model change is on Nick's ask-before list anyway: this script prints the case.

Rule changes are annotated beside the seasons they start, so the tables read right:
  NFL 2024 dynamic kickoff, NFL 2025 regular-season overtime (both teams possess);
  CFB 2023 running clock after first downs, CFB 2024 two-minute timeout;
  NBA 2023-24 in-season tournament (the 2024 season key).

Usage: python scripts/drift.py [nfl|cfb|nba|all] [--windows]   (--windows runs the window test whatever the flags say)
"""
import sys, os, json, argparse
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from fit_cfb import features, fit, mu_of

TABLES = {'nfl': 'data/nfl_games.csv', 'cfb': 'data/cfb_games.csv', 'nba': 'data/nba_games.csv'}
RULES = {'nfl': {2024: 'dynamic kickoff', 2025: 'regular-season OT, both possess'},
         'cfb': {2023: 'running clock after first downs', 2024: 'two-minute timeout'},
         'nba': {2024: 'in-season tournament'}}
WINDOWS = (3, 5, 8)


def load(sport):
    d = pd.read_csv(os.path.join(ROOT, TABLES[sport]))
    if sport == 'nfl':
        d = d[(d.season >= 2006) & (d.total > 20) & (d.total < 80) & (d.home_spread.abs() < 30)]
    elif sport == 'cfb':
        d = d[(d.total > 20) & (d.total < 100) & (d.home_spread.abs() < 60)]
    else:
        d = d[(d.season >= 2018)]   # the block's own era (2017-18 on; the season key is the year it ends)
    d = d.reset_index(drop=True)
    y = ((d['fh'] + d['fa']) - (d['h1h'] + d['h1a'])).values.astype(float)
    return d, y


def X_of(sport, d):
    """The block's regressors: the football fitter's (knee when the block has one), the NBA's six terms."""
    m = engine.MODEL[sport]
    if sport == 'nba':
        home_fav_by = -d['home_spread']
        fav_by = home_fav_by.abs()
        m1 = d['h1h'] - d['h1a']
        favm = np.where(home_fav_by >= 0, m1, -m1)
        h1 = d['h1h'] + d['h1a']
        return np.column_stack([np.ones(len(d)), d['total'].values, h1.values, np.abs(favm), favm, np.where(favm < 0, fav_by, 0)])
    return features(d, m.get('knee', 14) if len(m['coef']) > 6 else None)


def model_mu(sport, d):
    m = engine.MODEL[sport]
    return mu_of(np.array(m['coef']), X_of(sport, d))


def by_season(sport, d, y, mu):
    resid = y - mu
    out = []
    for s in sorted(d.season.unique()):
        msk = (d.season == s).values
        r = resid[msk]
        n = int(msk.sum())
        se = r.std(ddof=1) / np.sqrt(n) if n > 1 else float('nan')
        z = r.mean() / se if se and se == se else float('nan')
        out.append(dict(season=int(s), n=n, miss=float(r.mean()), se=float(se), z=float(z), rule=RULES.get(sport, {}).get(int(s))))
    return out


def brier_at_rungs(mu_te, sd_te, zq, y_te, med_te):
    """Brier of P(over) at the market stand-in rungs (median and -4, -2, +2, +4), pushes left out."""
    tot = n = 0.0
    for off in (0, -4, -2, 2, 4):
        t = med_te + off
        m = y_te != t
        p = 1 - np.searchsorted(zq, (t[m] - mu_te[m]) / sd_te[m], side='right') / len(zq)
        tot += ((p - (y_te[m] > t[m]).astype(float)) ** 2).sum()
        n += m.sum()
    return tot / n


def fit_block(X, y):
    coef = fit(X, y)
    mu = mu_of(coef, X)
    k = float(np.sqrt(np.mean((y - mu) ** 2 / mu)))
    zq = np.sort((y - mu) / (k * np.sqrt(mu)))
    return coef, k, zq


def window_test(sport, d, y):
    """Fit on the last W seasons before the latest, score on the latest, against the fit on all earlier seasons."""
    X = X_of(sport, d)
    seasons = sorted(d.season.unique())
    latest = seasons[-1]
    te = (d.season == latest).values
    rows = []
    for name, lo in [('all seasons', None)] + [(f'last {w}', seasons[-1 - w] if len(seasons) > w else None) for w in WINDOWS]:
        if name != 'all seasons' and lo is None:
            continue
        tr = (d.season < latest).values if lo is None else ((d.season < latest) & (d.season >= lo)).values
        if tr.sum() < 500:
            continue
        coef, k, zq = fit_block(X[tr], y[tr])
        mu_te = mu_of(coef, X[te])
        sd_te = k * np.sqrt(mu_te)
        med = np.round((mu_te + sd_te * np.quantile(zq, 0.5)) * 2) / 2
        b = brier_at_rungs(mu_te, sd_te, zq, y[te], med)
        rows.append(dict(name=name, n_train=int(tr.sum()), brier=b, miss=float((y[te] - mu_te).mean()), mae=float(np.abs(y[te] - mu_te).mean())))
    return latest, int(te.sum()), rows


def report(sport, windows=False):
    d, y = load(sport)
    mu = model_mu(sport, d)
    seas = by_season(sport, d, y, mu)
    print(f'\n{sport.upper()}: model.json block on {len(d)} games, {d.season.min()}-{d.season.max()}; '
          f'mean miss {float((y - mu).mean()):+.2f}, sd {float((y - mu).std()):.2f}')
    print('  season    n   miss    se     z   note')
    flagged = []
    for r in seas:
        flag = ' <-- past 2 SE' if abs(r['z']) >= 2 else ''
        note = (r['rule'] or '')
        print(f"  {r['season']}  {r['n']:>5}  {r['miss']:+5.2f}  {r['se']:4.2f}  {r['z']:+5.2f}   {note}{flag}")
        if abs(r['z']) >= 2:
            flagged.append(r)
    last2 = seas[-2:]
    trigger = len(last2) == 2 and all(abs(r['z']) >= 2 for r in last2) and (last2[0]['z'] > 0) == (last2[1]['z'] > 0)
    if trigger:
        print(f"  RULE: the latest two seasons sit past 2 SE on the same side ({last2[0]['season']} {last2[0]['z']:+.1f}, {last2[1]['season']} {last2[1]['z']:+.1f}); the window test runs.")
    elif flagged:
        print(f"  {len(flagged)} season(s) past 2 SE, not the latest two together: watch, do not act.")
    else:
        print('  no season past 2 SE.')
    if trigger or windows:
        latest, n_te, rows = window_test(sport, d, y)
        print(f'  window test, held out {latest} ({n_te} games), Brier at the rungs the desk prices (lower is better):')
        for r in rows:
            print(f"    {r['name']:<12} train {r['n_train']:>6}  brier {r['brier']:.4f}  miss on {latest} {r['miss']:+.2f}  mae {r['mae']:.2f}")
        best = min(rows, key=lambda r: r['brier'])
        base = next(r for r in rows if r['name'] == 'all seasons')
        # 0.002 of Brier is the size of a real difference at these counts (the trust study's model-vs-book gaps ran
        # 0.002 to 0.003); less than that is a coin that came up heads, and all seasons stays
        if best['name'] != 'all seasons' and best['brier'] < base['brier'] - 0.002:
            print(f"    -> {best['name']} beats all seasons by {base['brier'] - best['brier']:.4f} Brier on the held-out season: the case for a window. Ask before changing model.json.")
        else:
            gap = base['brier'] - best['brier']
            print(f"    -> all seasons holds{f' (best window inside noise, {gap:.4f} Brier)' if best['name'] != 'all seasons' else ''}. More games beat fresher games.")
    return seas


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('sport', nargs='?', default='all')
    ap.add_argument('--windows', action='store_true', help='run the window test even when no season is flagged')
    a = ap.parse_args()
    for s in (['nfl', 'cfb', 'nba'] if a.sport == 'all' else [a.sport]):
        report(s, a.windows)
