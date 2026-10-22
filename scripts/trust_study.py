"""Model versus market at the half (Build Plan week 5, the trust and margin question), on real halftime lines.

Joins data/odds_h2_SPORT.csv (the market's second-half total posted during the break, scripts/odds_history.py)
to data/half_times_SPORT.csv (closing lines, halftime score, final) and asks, game by game:
  1. who is closer to the second-half points, the model's fair line or the market's 2H line, overall and by how
     far apart they were (the 6+ point question: when they disagree a lot, who has been right);
  2. the blend weight: the second-half line w x model + (1 - w) x market with the smallest miss, and the weight
     whose probability at the market line is best calibrated (Brier), against config trust_pct;
  3. calibration of the desk's number at the market line: when the blend says 58 percent over, how often over;
  4. what a 3-cent margin at the market line would have fired, and how those calls did, by edge size.
Every probability is the engine's own (HalfModel, empirical quantiles), so this is the desk as it runs.

Usage: python scripts/trust_study.py nfl [--trust 50]
"""
import os, sys, csv, json, argparse
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine


def vig_free(over_price, under_price):
    """Implied P(over) from American prices on both sides, the juice taken out. None without both."""
    def p(a):
        a = float(a)
        return 100 / (a + 100) if a > 0 else -a / (-a + 100)
    try:
        po, pu = p(over_price), p(under_price)
    except (TypeError, ValueError):
        return None
    return po / (po + pu)


class LosoModel:
    """HalfModel's interface on a block fit without the game's own season (leave one season out on the sport's
    game table), so a season the live block was fit on is scored honestly. Football only."""
    blocks = {}

    @classmethod
    def block(cls, sport, season):
        if (sport, season) not in cls.blocks:
            import numpy as np, pandas as pd
            sys.path.insert(0, os.path.join(ROOT, 'scripts'))
            import fit_cfb
            d = pd.read_csv(os.path.join(ROOT, 'data', f'{sport}_games.csv'))
            d = d[(d.total > 20) & (d.total < 100) & (d.home_spread.abs() < 60) & (d.season != season)].reset_index(drop=True)
            y = ((d.fh + d.fa) - (d.h1h + d.h1a)).values.astype(float)
            live = engine.MODEL[sport]
            knee = live.get('knee', 14) if len(live['coef']) > 6 else None
            X = fit_cfb.features(d, knee)
            coef = fit_cfb.fit(X, y)
            mu = fit_cfb.mu_of(coef, X)
            k = float(np.sqrt(np.mean((y - mu) ** 2 / mu)))
            z = np.quantile((y - mu) / (k * np.sqrt(mu)), np.linspace(0, 1, 201))
            cls.blocks[(sport, season)] = dict(live, coef=[float(c) for c in coef], k=k, z=[float(v) for v in z], n=int(len(d)))
        return cls.blocks[(sport, season)]

    def __init__(self, sport, season, total, home_spread, h1h, h1a):
        saved = engine.MODEL[sport]
        engine.MODEL[sport] = self.block(sport, season)
        try:
            self.m = engine.HalfModel(sport, total, home_spread, h1h, h1a)
        finally:
            engine.MODEL[sport] = saved
        self.median, self.mu, self.sd = self.m.median, self.m.mu, self.m.sd

    def p_over_2h(self, t):
        return self.m.p_over_2h(t)


def load(sport, loso=False):
    tt = {r['game_id']: r for r in csv.DictReader(open(os.path.join(ROOT, 'data', f'half_times_{sport}.csv')))}
    rows = []
    for r in csv.DictReader(open(os.path.join(ROOT, 'data', f'odds_h2_{sport}.csv'))):
        g = tt.get(r['game_id'])
        if not g or not r['line_med']:
            continue
        books = json.loads(r['books'] or '{}')
        line = float(r['line_med'])
        # the market's own probability at its line: the vig-free price of the book that set the median line
        pm = None
        for b, (ln, o, u) in sorted(books.items(), key=lambda kv: (kv[0] != 'pinnacle', kv[0] != 'draftkings')):
            if ln == line and o is not None and u is not None:
                pm = vig_free(o, u)
                break
        if loso:
            m = LosoModel(sport, int(g['season']), float(g['total']), float(g['home_spread']), int(g['h1h']), int(g['h1a']))
        else:
            m = engine.HalfModel(sport, float(g['total']), float(g['home_spread']), int(g['h1h']), int(g['h1a']))
        y = (int(g['fh']) + int(g['fa'])) - (int(g['h1h']) + int(g['h1a']))
        rows.append(dict(game=r['game_id'], date=r['date'], season=int(g['season']), mkt=line, p_mkt=pm, model=m, fair=m.median, y=y,
                         p_model=m.p_over_2h(line), push=float(y) == line, h1=int(g['h1h']) + int(g['h1a']), margin=abs(int(g['h1h']) - int(g['h1a']))))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sport')
    ap.add_argument('--trust', type=float, default=None, help='config trust_pct to score (default: config.json)')
    ap.add_argument('--loso', action='store_true', help='score each season with a block fit without it (honest on seasons the live block was fit on)')
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(ROOT, 'config.json')))
    trust = (a.trust if a.trust is not None else float(cfg.get('trust_pct', 50))) / 100
    rows = load(a.sport, a.loso)
    n = len(rows)
    print(f'{a.sport}: {n} halftimes with a market 2H line, {min(r["season"] for r in rows)}-{max(r["season"] for r in rows)}; config trust_pct {trust * 100:.0f}'
          + ('; each season scored with a block fit without it' if a.loso else '; the live block (in sample on seasons it was fit on)'))
    y = np.array([r['y'] for r in rows], float)
    fair = np.array([r['fair'] for r in rows])
    mkt = np.array([r['mkt'] for r in rows])
    gap = fair - mkt
    print(f'  model fair line minus market 2H line: mean {gap.mean():+.2f}, sd {gap.std():.2f}, |gap| 3+ in {100 * np.mean(np.abs(gap) >= 3):.0f}% of games, '
          f'6+ in {100 * np.mean(np.abs(gap) >= 6):.1f}%')

    # 1. who is closer, by gap
    print('\n1. who is closer to the second-half points (ties left out), by how far apart they were')
    print(f'   {"gap":>8} {"n":>5} {"model":>6} {"market":>7} {"model side hit":>15}  mae model / market')
    for lo, hi in [(0, 1.5), (2, 3.5), (4, 5.5), (6, 99)]:
        m = (np.abs(gap) >= lo) & (np.abs(gap) <= hi)
        if not m.sum():
            continue
        em, ek = np.abs(y[m] - fair[m]), np.abs(y[m] - mkt[m])
        side = np.sign(gap[m]) * np.sign(y[m] - mkt[m])     # the final on the model's side of the market line
        dec = side != 0
        print(f'   {f"{lo}-{hi}" if hi < 99 else f"{lo}+":>8} {m.sum():>5} {int((em < ek).sum()):>6} {int((ek < em).sum()):>7} '
              f'{100 * np.mean(side[dec] > 0) if dec.sum() else float("nan"):>14.0f}%  {em.mean():.2f} / {ek.mean():.2f}')
    all_em, all_ek = np.abs(y - fair), np.abs(y - mkt)
    print(f'   all games: model closer {int((all_em < all_ek).sum())}, market closer {int((all_ek < all_em).sum())}; mae model {all_em.mean():.2f}, market {all_ek.mean():.2f}')

    # 2. the blend weight, by miss and by Brier at the market line
    print('\n2. the blend w x model + (1 - w) x market')
    print(f'   {"w":>5} {"mae":>6} {"brier at mkt line":>18}')
    over = np.array([r['y'] > r['mkt'] for r in rows], float)
    dec = np.array([not r['push'] for r in rows])
    pm = np.array([r['p_model'] for r in rows])
    pk = np.array([r['p_mkt'] if r['p_mkt'] is not None else 0.5 for r in rows])
    best = None
    for w in np.arange(0, 1.01, 0.1):
        blend = w * fair + (1 - w) * mkt
        mae = np.abs(y - blend).mean()
        p = w * pm + (1 - w) * pk
        brier = np.mean((p[dec] - over[dec]) ** 2)
        print(f'   {w:>5.1f} {mae:>6.2f} {brier:>18.4f}' + ('   <- config' if abs(w - trust) < 0.05 else ''))
        if best is None or brier < best[1]:
            best = (w, brier)
    print(f'   best Brier at w {best[0]:.1f}; market alone {np.mean((pk[dec] - over[dec]) ** 2):.4f}, model alone {np.mean((pm[dec] - over[dec]) ** 2):.4f}')

    # 3. calibration of the desk's number (config trust) at the market line
    p_used = trust * pm + (1 - trust) * pk
    print(f'\n3. the desk at trust {trust * 100:.0f}: when it says P(over the market line) is ..., how often over (pushes out)')
    for lo, hi in [(0, 0.40), (0.40, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 1.01)]:
        m = dec & (p_used >= lo) & (p_used < hi)
        if m.sum():
            print(f'   {100 * lo:>3.0f}-{100 * min(hi, 1):<3.0f}%  n {m.sum():>4}  said {100 * p_used[m].mean():.1f}  actual {100 * over[m].mean():.1f}')

    # 4. a 3-cent margin at the market line: what fires and how it does, by edge
    margin = float(cfg.get('margin_c', 3)) / 100
    edge = p_used - pk
    print(f'\n4. calls at the market line with a {100 * margin:.0f}-cent margin (edge = desk minus market, at the line), by edge size')
    print(f'   {"edge":>8} {"n":>5} {"hit":>6}  {"ROI at -110":>11}')
    for lo, hi in [(margin, 0.05), (0.05, 0.07), (0.07, 0.10), (0.10, 1)]:
        m = dec & (np.abs(edge) >= lo) & (np.abs(edge) < hi)
        if not m.sum():
            continue
        hit = (np.sign(edge[m]) == np.sign(over[m] - 0.5))
        roi = (hit.mean() * (100 / 110) - (1 - hit.mean()))
        print(f'   {f"{100 * lo:.0f}-{100 * hi:.0f}c" if hi < 1 else f"{100 * lo:.0f}c+":>8} {m.sum():>5} {100 * hit.mean():>5.1f}%  {100 * roi:>+10.1f}%')
    m = dec & (np.abs(edge) >= margin)
    if not m.sum():
        print('   no calls at this margin')
        return
    hit = (np.sign(edge[m]) == np.sign(over[m] - 0.5))
    print(f'   all calls: n {m.sum()}, hit {100 * hit.mean():.1f}%, break-even at -110 is 52.4%')
    # the same calls with the gap capped: no call when the lines are 6+ apart
    m2 = m & (np.abs(gap) < 6)
    if m2.sum():
        hit2 = (np.sign(edge[m2]) == np.sign(over[m2] - 0.5))
        print(f'   without 6+ gap games: n {m2.sum()}, hit {100 * hit2.mean():.1f}%')


if __name__ == '__main__':
    main()
