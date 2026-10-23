"""Shared pieces for the halftime studies (S2 season phase and weather, S3 NFL schedule): the model residual per
game, a bucket line with its standard error, the all-features regression with t-stats, and the gate (leave one
season out, MAE and Brier at the rungs the desk prices, with and without a candidate term)."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
from fit_cfb import features, fit, mu_of

RUNGS = {'nfl': (0, -3, -1.5, 1.5, 3), 'cfb': (0, -4, -2, 2, 4)}


def load_games(sport):
    d = pd.read_csv(os.path.join(ROOT, 'data', f'{sport}_games.csv'))
    if sport == 'nfl':
        d = d[(d.season >= 2006) & (d.total > 20) & (d.total < 80) & (d.home_spread.abs() < 30)]
    else:
        d = d[(d.total > 20) & (d.total < 100) & (d.home_spread.abs() < 60)]
    d = d.reset_index(drop=True)
    d['y'] = (d.fh + d.fa) - (d.h1h + d.h1a)
    m = engine.MODEL[sport]
    d['mu'] = mu_of(np.array(m['coef']), features(d, m.get('knee', 14) if len(m['coef']) > 6 else None))
    d['resid'] = d.y - d.mu
    return d


def add_book(d, sport):
    """The book's halftime line (data/odds_h2_<sport>.csv) joined on game_id: vs_book and the over rate."""
    p = os.path.join(ROOT, 'data', f'odds_h2_{sport}.csv')
    o = pd.read_csv(p, usecols=['game_id', 'line_med'])
    o['game_id'] = o.game_id.astype(str)
    d['game_id'] = d.game_id.astype(str)
    d = d.merge(o, on='game_id', how='left')
    d['vs_book'] = d.y - d.line_med
    d['over'] = np.where(d.line_med.notna(), (d.y > d.line_med).astype(float), np.nan)
    d.loc[d.y == d.line_med, 'over'] = np.nan
    return d


def cell(d, mask, label, min_n=20):
    mask = mask.fillna(False) if hasattr(mask, 'fillna') else mask
    r = d.resid[mask]
    n = int(mask.sum())
    if n < min_n:
        return None
    se = r.std(ddof=1) / np.sqrt(n)
    z = r.mean() / se if se else 0.0
    book = ''
    if 'line_med' in d:
        b = d.vs_book[mask & d.line_med.notna()]
        ov = d.over[mask & d.over.notna()]
        if len(ov) >= 20:
            book = f"  vs book {b.mean():+5.2f} over {100 * ov.mean():4.1f}% (n {len(ov)})"
    flag = '  <-- past 2 SE' if abs(z) >= 2 else ''
    print(f"  {label:<46} n {n:>5}  total {d.total[mask].mean():5.1f}  resid {r.mean():+5.2f}  se {se:4.2f}  z {z:+5.2f}{book}{flag}")
    return z


def regress(d, cols):
    """The model residual on every feature at once; returns the names past t 2."""
    Xr = np.column_stack([np.ones(len(d))] + [np.nan_to_num(c.astype(float).values) for c in cols.values()])
    y = d.resid.values
    coef, *_ = np.linalg.lstsq(Xr, y, rcond=None)
    res = y - Xr @ coef
    s2 = (res ** 2).sum() / (len(y) - Xr.shape[1])
    cov = s2 * np.linalg.pinv(Xr.T @ Xr)
    flagged = []
    for name, c, v in zip(['intercept'] + list(cols), coef, np.sqrt(np.diag(cov))):
        t = c / v if v else 0.0
        print(f"  {name:<22} {c:+6.3f}  t {t:+5.2f}{'  <--' if abs(t) >= 2 and name != 'intercept' else ''}")
        if abs(t) >= 2 and name != 'intercept':
            flagged.append(name)
    return flagged


def loso_with(d, sport, extra, label):
    """Leave-one-season-out MAE and Brier at the rungs with and without the extra column. The bar for a term:
    0.0005 of Brier and no worse MAE."""
    m = engine.MODEL[sport]
    knee = m.get('knee', 14) if len(m['coef']) > 6 else None
    X0 = features(d, knee)
    X1 = np.column_stack([X0, np.nan_to_num(extra.astype(float).values)])
    y = d.y.values.astype(float)
    out = {}
    for name, X in (('block', X0), (label, X1)):
        resid = np.zeros(len(d)); brier = n = 0.0
        for s in sorted(d.season.unique()):
            tr, te = (d.season != s).values, (d.season == s).values
            coef = fit(X[tr], y[tr])
            mu_tr = mu_of(coef, X[tr])
            k = float(np.sqrt(np.mean((y[tr] - mu_tr) ** 2 / mu_tr)))
            zq = np.sort((y[tr] - mu_tr) / (k * np.sqrt(mu_tr)))
            mu_te = mu_of(coef, X[te]); sd_te = k * np.sqrt(mu_te)
            resid[te] = y[te] - mu_te
            med = np.round((mu_te + sd_te * np.quantile(zq, 0.5)) * 2) / 2
            for off in RUNGS[sport]:
                t = med + off
                msk = y[te] != t
                p = 1 - np.searchsorted(zq, (t[msk] - mu_te[msk]) / sd_te[msk], side='right') / len(zq)
                brier += ((p - (y[te][msk] > t[msk]).astype(float)) ** 2).sum(); n += msk.sum()
        out[name] = (float(np.abs(resid).mean()), brier / n)
    b0, b1 = out['block'], out[label]
    ok = b1[1] < b0[1] - 0.0005 and b1[0] <= b0[0]
    print(f"  gate {label}: MAE {b0[0]:.4f} -> {b1[0]:.4f}, Brier {b0[1]:.5f} -> {b1[1]:.5f} ({'passes' if ok else 'fails'})")
    return ok
