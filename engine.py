"""Halftime Desk engine: second-half points model, fair prices for Kalshi total strikes,
single-leg and middle suggestions with sizing. Pure functions, no network."""
import json, math, os
from bisect import bisect_right

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, 'model.json')) as f:
    MODEL = json.load(f)
FEE_RATE = 0.07


def fee_per(p, order='taker'):
    return 0.0 if order == 'maker' else FEE_RATE * p * (1 - p)


def order_fee(n, p, order='taker'):
    return math.ceil(n * fee_per(p, order) * 100 - 1e-9) / 100


def max_quote(max_all_in, order='taker'):
    best = 0
    for c in range(1, 100):
        p = c / 100
        if p + fee_per(p, order) <= max_all_in + 1e-9:
            best = c
    return best


class HalfModel:
    """Game state at the half -> distribution of second-half points."""

    def __init__(self, sport, total, home_spread, h1h, h1a):
        m = MODEL.get(sport) or MODEL['nfl']
        self.sport = sport
        home_fav_by = -(home_spread or 0)
        self.fav_by = abs(home_fav_by)
        m1 = h1h - h1a
        self.favm = m1 if home_fav_by >= 0 else -m1
        self.h1 = h1h + h1a
        c = m['coef']
        mu = c[0] + c[1] * total + c[2] * self.h1 + c[3] * abs(self.favm) + c[4] * self.favm + c[5] * (self.fav_by if self.favm < 0 else 0)
        self.mu = max(8.0, mu)
        self.sd = m['k'] * math.sqrt(self.mu)
        self.q = m['z']
        self.n = m['n']
        self.state = 'trail' if self.favm < 0 else ('lead' if self.favm > 0 else 'tied')
        fb = self.fav_by
        self.bucket = '0-3' if fb <= 3 else '3.5-7' if fb <= 7 else '7.5-10.5' if fb <= 10.5 else '11-14.5' if fb <= 14.5 else '15+'
        self.ref = m['ref'].get(self.state + '|' + self.bucket)
        self.median = self.mu + self.sd * self.q[100]

    def cdf(self, x):
        z = (x - self.mu) / self.sd
        q = self.q
        if z <= q[0]:
            return 0.0
        if z >= q[-1]:
            return 1.0
        hi = bisect_right(q, z)
        lo = hi - 1
        f = (z - q[lo]) / ((q[hi] - q[lo]) or 1)
        return (lo + f) / (len(q) - 1)

    def p_over_2h(self, t):
        """P(second-half points > t); points are whole numbers."""
        return 1 - self.cdf(math.floor(t) + 0.5)

    def p_push_2h(self, t):
        if float(t).is_integer():
            return max(0.0, self.cdf(t + 0.5) - self.cdf(t - 0.5))
        return 0.0

    def spot(self):
        """Plain-language label for the game state, from the halftime study."""
        fm, fb = self.favm, self.fav_by
        if fm >= 15:
            return 'blowout: second-half under spot'
        if fm < 0 and fm >= -14:
            if self.sport == 'nfl' and 3.5 <= fb <= 10.5:
                return 'favorite chasing: second-half over spot'
            return 'favorite trailing: mild over lean'
        if fm <= -15:
            return 'favorite buried: no lean'
        return 'no strong lean'


def price_lines(model, lines, mode='fg', margin=0.03):
    """Fair over/under probability and max prices for each total line.
    mode 'fg' prices full-game lines (line - first-half points); '2h' prices second-half lines."""
    off = 0 if mode == '2h' else model.h1
    rows = []
    for line in sorted(set(lines)):
        t = line - off
        po = model.p_over_2h(t)
        pp = model.p_push_2h(t)
        pu = max(0.0, 1 - po - pp)
        rows.append(dict(line=line, t=t, p_over=po, p_push=pp, p_under=pu,
                         over_take=max_quote(po - margin, 'taker'), over_rest=max_quote(po - margin, 'maker'),
                         under_take=max_quote(pu - margin, 'taker'), under_rest=max_quote(pu - margin, 'maker')))
    return rows


def fair_line(model, mode='fg'):
    off = 0 if mode == '2h' else model.h1
    x = off + model.median
    return math.floor(x) + 0.5


def suggest(rows, quotes, order='taker', margin=0.03, trust=0.5, bankroll=3000.0, max_risk=75.0, max_cost=225.0, price_band=(15, 85)):
    """quotes: {line: {'y': yes_ask_cents, 'n': no_ask_cents}} (None when missing).
    Legs priced outside price_band are ignored: the model's tails are its least trusted part, and a 3-cent edge
    on a 10-cent contract is a claim the data cannot back. Returns singles and middles sorted by edge."""
    fee = lambda p: fee_per(p, order)
    legs = []
    for r in rows:
        qq = quotes.get(r['line']) or {}
        lo, hi = price_band
        y = qq.get('y') if lo <= (qq.get('y') or 0) <= hi else None
        n = qq.get('n') if lo <= (qq.get('n') or 0) <= hi else None
        if y is not None and n is not None:
            mkt = (y + (100 - n)) / 200
        elif y is not None:
            mkt = (y - 1.5) / 100
        elif n is not None:
            mkt = (101.5 - n) / 100
        else:
            mkt = None
        r['mkt_over'] = mkt
        r['used_over'] = r['p_over'] if mkt is None else trust * r['p_over'] + (1 - trust) * mkt
        r['used_under'] = max(0.0, 1 - r['used_over'] - r['p_push'])
        if y is not None:
            p = y / 100; eff = p + fee(p)
            legs.append(dict(kind='over', line=r['line'], price_c=y, eff=eff, fair_model=r['p_over'], fair_mkt=mkt, fair_used=r['used_over'], edge=r['used_over'] - eff))
        if n is not None:
            p = n / 100; eff = p + fee(p)
            fm = None if mkt is None else max(0.0, 1 - mkt - r['p_push'])
            legs.append(dict(kind='under', line=r['line'], price_c=n, eff=eff, fair_model=r['p_under'], fair_mkt=fm, fair_used=r['used_under'], edge=r['used_under'] - eff))
    singles = []
    for l in legs:
        p = l['price_c'] / 100
        ok = l['edge'] >= margin - 1e-9
        f = max(0.0, 0.25 * (l['fair_used'] - l['eff']) / max(0.01, 1 - l['eff']))
        budget = min(f * bankroll, max_risk)
        contracts = int(budget / (p + fee(p)) + 1e-9) if ok else 0
        cost = round(contracts * p + order_fee(contracts, p, order), 2) if contracts else 0.0
        singles.append(dict(l, ok=ok, contracts=contracts, cost=cost, win=round(contracts - cost, 2)))
    singles.sort(key=lambda x: -x['edge'])
    by_line = {r['line']: r for r in rows}
    mids = []
    for a in legs:
        if a['kind'] != 'over':
            continue
        for b in legs:
            if b['kind'] != 'under' or not b['line'] > a['line']:
                continue
            ra, rb = by_line[a['line']], by_line[b['line']]
            p_mid_model = max(0.0, ra['p_over'] - rb['p_over'] - rb['p_push'])
            p_mid_mkt = None if (ra['mkt_over'] is None or rb['mkt_over'] is None) else max(0.0, ra['mkt_over'] - rb['mkt_over'])
            p_mid = p_mid_model if p_mid_mkt is None else trust * p_mid_model + (1 - trust) * p_mid_mkt
            c = a['eff'] + b['eff']
            ev = 1 - c + p_mid
            loss = c - 1
            ok = ev >= margin - 1e-9
            pairs = 0
            if ok:
                pairs = min(int(max_risk / loss + 1e-9), int(max_cost / c + 1e-9)) if loss > 0 else int(max_cost / c + 1e-9)
            pa, pb = a['price_c'] / 100, b['price_c'] / 100
            cost = round(pairs * (pa + pb) + order_fee(pairs, pa, order) + order_fee(pairs, pb, order), 2) if pairs else 0.0
            mids.append(dict(a=a, b=b, lo=a['line'] + 0.5, hi=b['line'] - 0.5, p_mid_model=p_mid_model, p_mid_mkt=p_mid_mkt, p_mid=p_mid,
                             c=c, ev=ev, loss=loss, ok=ok, pairs=pairs, cost=cost,
                             best=round(2 * pairs - cost, 2) if pairs else 0.0, worst=round(pairs - cost, 2) if pairs else 0.0))
    mids.sort(key=lambda x: -x['ev'])
    return dict(legs=legs, singles=singles, mids=mids)


def describe(model, inp, rows, sug, mode='fg', top=3, tickers=None):
    """Plain-language order sheet for a push notification or the terminal."""
    away, home = inp.get('away', 'Away'), inp.get('home', 'Home')
    tk = tickers or {}
    fl = fair_line(model, mode)
    what = '2nd-half total' if mode == '2h' else 'game total'
    def mk(line):
        t = tk.get(line)
        return f" ({t.split('-')[-1]})" if t else ''
    lines = [f"{away} {inp['h1a']}, {home} {inp['h1h']} at the half. Fair {what} {fl:.1f}. 2H expected {model.mu:.1f} points. {model.spot().capitalize()}."]
    n = 0
    mids = [m for m in sug['mids'] if m['ok']][:top]
    used = set()
    for i, m in enumerate(mids):
        n += 1
        a, b = m['a'], m['b']
        ca, cb = round(m['pairs'] * a['price_c'] / 100, 0), round(m['pairs'] * b['price_c'] / 100, 0)
        head = f"PLAY {n}, MIDDLE" if i == 0 else f"ALT {n}, same middle idea (place this OR play 1, not both)"
        lines.append(f"{head}: Buy YES on Over {a['line']:.1f}{mk(a['line'])}, {m['pairs']} shares at {a['price_c']}c (${ca:.0f}). "
                     f"Buy NO on Over {b['line']:.1f}{mk(b['line'])}, {m['pairs']} shares at {b['price_c']}c (${cb:.0f}). "
                     f"Total in: ${m['cost']:.0f}. Final {m['lo']:.0f} to {m['hi']:.0f} = both pay, +${m['best']:.0f}. Any other final = {m['worst']:+.0f}. Hits {100*m['p_mid']:.0f}%, edge +{100*m['ev']:.1f}c a pair.")
        if i == 0:
            used.update({('over', a['line']), ('under', b['line'])})
    seen = set()
    for s in [s for s in sug['singles'] if s['ok']]:
        if (s['kind'], s['line']) in used or s['line'] in seen:
            continue
        seen.add(s['line'])
        n += 1
        side = 'YES' if s['kind'] == 'over' else 'NO'
        wins_when = f"final {s['line'] + 0.5:.0f} or more" if s['kind'] == 'over' else f"final {s['line'] - 0.5:.0f} or less"
        lines.append(f"PLAY {n}, SINGLE: Buy {side} on Over {s['line']:.1f}{mk(s['line'])}, {s['contracts']} shares at {s['price_c']}c = ${s['cost']:.0f}. Wins ${s['win']:.0f} on a {wins_when}. Fair {100*s['fair_used']:.0f}c, edge +{100*s['edge']:.1f}c.")
        if len(seen) >= top:
            break
    if n == 0:
        wide = [m for m in sug['mids'] if m['hi'] - m['lo'] >= 2]
        best = (wide[:1] or sug['mids'][:1] or [None])[0]
        msg = 'NO BET at these prices.'
        if best:
            msg += f" Closest: YES Over {best['a']['line']:.1f} at {best['a']['price_c']}c + NO Over {best['b']['line']:.1f} at {best['b']['price_c']}c is ${best['c']:.2f} a pair, hits {100*best['p_mid']:.0f}%, edge {100*best['ev']:+.1f}c (needs +3)."
        lines.append(msg)
    rest = []
    for r in rows:
        if abs(r['line'] - fl) <= 3.5:
            rest.append(f"Over {r['line']:.1f}: YES at {r['over_rest']}c or less, NO at {r['under_rest']}c or less")
    if rest:
        lines.append('Resting limit orders worth posting: ' + '; '.join(rest) + '.')
    return '\n'.join(lines)
