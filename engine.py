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


def rest_plan(model, rows, mode='fg', margin=0.03, bankroll=3000.0, max_risk=75.0, max_cost=225.0, rest_scale=0.5):
    """Resting limit orders near fair: a quarter-Kelly size at the limit price (where the edge equals the margin),
    scaled by rest_scale because a resting order fills when the market moves through it. Also the best resting
    middle: YES on a lower line plus NO on a higher one, both at their limits."""
    fl = fair_line(model, mode)
    near = [r for r in rows if abs(r['line'] - fl) <= 3.5 and r['over_rest'] >= 1 and r['under_rest'] >= 1]
    def size(price_c):
        p = price_c / 100
        f = 0.25 * margin / max(0.05, 1 - p) * rest_scale
        budget = min(f * bankroll, max_risk)
        n = int(budget / p + 1e-9)
        return n, round(n * p, 2)
    legs = []
    for r in near:
        ny, cy = size(r['over_rest'])
        nn, cn = size(r['under_rest'])
        legs.append(dict(line=r['line'], y_c=r['over_rest'], y_n=ny, y_cost=cy, n_c=r['under_rest'], n_n=nn, n_cost=cn))
    best = None
    for a in near:
        for b in near:
            if b['line'] - a['line'] < 3:
                continue
            p_mid = max(0.0, a['p_over'] - b['p_over'] - b['p_push'])
            c = (a['over_rest'] + b['under_rest']) / 100
            ev = 1 - c + p_mid
            if ev <= 0:
                continue
            loss = c - 1
            pairs = min(int(max_risk / loss + 1e-9) if loss > 0 else 10**6, int(max_cost / c + 1e-9))
            pairs = int(pairs * rest_scale)
            if pairs < 1:
                continue
            cand = dict(a=a, b=b, p_mid=p_mid, c=c, ev=ev, pairs=pairs, cost=round(pairs * c, 2), best=round(pairs * (2 - c), 2), worst=round(pairs * (1 - c), 2))
            if best is None or cand['ev'] > best['ev']:
                best = cand
    return dict(legs=legs, middle=best)


def describe(model, inp, rows, sug, mode='fg', top=3, tickers=None, sizing=None):
    """Plain-language order sheet for a push notification or the terminal.
    sizing: dict(bankroll, max_risk, max_cost, margin) enables share counts on the resting orders."""
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
    if sizing:
        rp = rest_plan(model, rows, mode, sizing.get('margin', 0.03), sizing.get('bankroll', 3000.0), sizing.get('max_risk', 75.0), sizing.get('max_cost', 225.0))
        if rp['middle']:
            m = rp['middle']
            lines.append(f"RESTING MIDDLE: post YES on Over {m['a']['line']:.1f}{mk(m['a']['line'])} at {m['a']['over_rest']}c and NO on Over {m['b']['line']:.1f}{mk(m['b']['line'])} at {m['b']['under_rest']}c, {m['pairs']} shares each (${m['cost']:.0f} if both fill). "
                         f"Both filled: final {m['a']['line'] + 0.5:.0f} to {m['b']['line'] - 0.5:.0f} pays +${m['best']:.0f}, hits {100*m['p_mid']:.0f}%; any other final {m['worst']:+.0f}. One side alone is a fair single. Cancel what has not filled by the 4th quarter.")
        if rp['legs']:
            parts = [f"Over {l['line']:.1f}: YES {l['y_n']} sh at {l['y_c']}c (${l['y_cost']:.0f}) or NO {l['n_n']} sh at {l['n_c']}c (${l['n_cost']:.0f})" for l in rp['legs']]
            lines.append('Resting singles, pick a side per line: ' + '; '.join(parts) + '.')
    else:
        rest = [f"Over {r['line']:.1f}: YES at {r['over_rest']}c or less, NO at {r['under_rest']}c or less" for r in rows if abs(r['line'] - fl) <= 3.5]
        if rest:
            lines.append('Resting limit orders worth posting: ' + '; '.join(rest) + '.')
    return '\n'.join(lines)


def american(c):
    """Kalshi cents -> American odds string."""
    p = c / 100
    if p >= 0.5:
        return f"{-round(100 * p / (1 - p)):d}"
    return f"+{round(100 * (1 - p) / p):d}"


def money(x):
    """-5 -> 'loses $5', 12 -> 'wins $12'"""
    return f"loses ${-x:.0f}" if x < 0 else f"wins ${x:.0f}"


def chosen(sug, top=3):
    """The plays a push names: up to `top` cleared singles (one per line, best edge first) and the best cleared middle."""
    mids = [m for m in sug['mids'] if m['ok']]
    singles, seen = [], set()
    for s in [s for s in sug['singles'] if s['ok']]:
        if s['line'] in seen:
            continue
        seen.add(s['line'])
        singles.append(s)
        if len(singles) >= top:
            break
    return singles, (mids[0] if mids else None)


def order_sheet(model, inp, rows, sug, sizing, mode='fg', tickers=None, top=3):
    """The push text Nick asked for: PLAY when something clears, UPDATE otherwise.
    Returns (kind, title, body): title is 'PLAY: Away 21, Home 45', body is the order lines.
    Names come from inp['away_name'] / inp['home_name'] when given."""
    away = inp.get('away_name') or inp.get('away', 'Away')
    home = inp.get('home_name') or inp.get('home', 'Home')
    score = f"{away} {inp['h1a']}, {home} {inp['h1h']}"
    fl = fair_line(model, mode)
    ctx = f"Fair total {fl:.1f}. {model.spot().capitalize()}."
    singles, mid = chosen(sug, top)
    if mid or singles:
        out = [ctx, '']
        if singles:
            for s in singles:
                side = 'OVER' if s['kind'] == 'over' else 'UNDER'
                out.append(f"Buy {side} {s['line']:.1f} for ${s['cost']:.0f} at {s['price_c']}c ({american(s['price_c'])})")
            if len(singles) > 1:
                out.append('Best first. The others are backups if that price is gone, not a stack.')
            out.append('')
        if mid:
            m = mid
            a, b = m['a'], m['b']
            out += ['MIDDLE' + (' (instead of a single, not on top of one):' if singles else ':'),
                    f"Buy OVER {a['line']:.1f} at {a['price_c']}c ({m['pairs']} shares for ${m['pairs'] * a['price_c'] / 100:.0f})",
                    f"Buy UNDER {b['line']:.1f} at {b['price_c']}c ({m['pairs']} shares for ${m['pairs'] * b['price_c'] / 100:.0f})",
                    f"Final {m['lo']:.0f} to {m['hi']:.0f} wins both (+${m['best']:.0f}, hits {100*m['p_mid']:.0f}%); any other final {money(m['worst'])}."]
        return 'PLAY', f'PLAY: {score}', '\n'.join(out).rstrip()
    out = [ctx, '']
    rp = rest_plan(model, rows, mode, sizing.get('margin', 0.03), sizing.get('bankroll', 3000.0), sizing.get('max_risk', 75.0), sizing.get('max_cost', 225.0))
    m = rp['middle']
    if m:
        a, b = m['a'], m['b']
        out += ['POSSIBLE MIDDLE (post as limit orders):',
                f"Buy OVER {a['line']:.1f} at {a['over_rest']}c ({m['pairs']} shares for ${m['pairs'] * a['over_rest'] / 100:.0f})",
                f"Buy UNDER {b['line']:.1f} at {b['under_rest']}c ({m['pairs']} shares for ${m['pairs'] * b['under_rest'] / 100:.0f})",
                f"Both filled: final {a['line'] + 0.5:.0f} to {b['line'] - 0.5:.0f} wins both (+${m['best']:.0f}, hits {100*m['p_mid']:.0f}%); any other final {money(m['worst'])}. One side alone is a fair single."]
    else:
        near = sorted(rows, key=lambda r: abs(r['line'] - fl))[:2]
        out.append('No middle to post. Fair prices: ' + '; '.join(f"OVER {r['line']:.1f} {r['over_rest']}c / UNDER {r['line']:.1f} {r['under_rest']}c" for r in near) + '.')
    return 'UPDATE', f'UPDATE: {score}', '\n'.join(out).rstrip()
