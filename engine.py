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
    """Game state at the half -> distribution of second-half points.

    center / center_w: an outside expected second-half total (the market's) and the weight the model's own
    number keeps against it. The football models keep their own center (center_w 1.0, the default). The NBA
    model's center is 2.4 points from the sharp line in the median game and never beats it, while its shape is
    calibrated to a cent, so the NBA desk centers on the market and keeps the model for the shape of the
    ladder (see claude/nba-halftime.md). mu_model is always the model's own number, for the log."""

    def __init__(self, sport, total, home_spread, h1h, h1a, center=None, center_w=1.0):
        m = MODEL.get(sport) or MODEL['nfl']
        self.sport = sport
        home_fav_by = -(home_spread or 0)
        self.fav_by = abs(home_fav_by)
        m1 = h1h - h1a
        self.favm = m1 if home_fav_by >= 0 else -m1
        self.h1 = h1h + h1a
        c = m['coef']
        mu = c[0] + c[1] * total + c[2] * self.h1 + c[3] * abs(self.favm) + c[4] * self.favm + c[5] * (self.fav_by if self.favm < 0 else 0)
        self.mu_model = max(8.0, mu)
        self.center = center
        self.center_w = 1.0 if center is None else max(0.0, min(1.0, center_w))
        self.mu = self.mu_model if center is None else max(8.0, self.center_w * self.mu_model + (1 - self.center_w) * center)
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
        if self.sport == 'nba':
            # 24,437 games: the NBA second half runs at the pregame pace whatever the half looks like. No spot
            # leans over or under against the market's 2H line (every cell 47 to 53 percent), blowouts included
            # (20+ at the half ran 52 percent over, garbage-time pace beats the running clock).
            if abs(fm) >= 20:
                return 'blowout: pace holds, no lean (not the football under spot)'
            if fm < 0:
                return 'favorite trailing: no lean in the NBA'
            return 'no lean: second half runs at the pregame pace'
        if fm >= 15:
            return 'blowout: second-half under spot'
        if fm < 0 and fm >= -14:
            if self.sport == 'nfl' and 3.5 <= fb <= 10.5:
                return 'favorite chasing: second-half over spot'
            return 'favorite trailing: mild over lean'
        if fm <= -15:
            return 'favorite buried: no lean'
        return 'no strong lean'


class LateModel:
    """Game state at the end of the third quarter (NBA) -> distribution of the points left to play: the fourth
    quarter plus overtime. Same interface as HalfModel (h1 is the points so far, mu the expected points left,
    p_over_2h / p_push_2h on the points left), so price_lines, suggest, rest_plan and order_sheet run unchanged.

    Regulation Q4 points come from the model block (total, points through three, |margin after three| and
    min(|margin|, 5)); overtime is a mixture on top: P(OT) from a table by |margin after three| (9 percent in a
    game within 7, 0.3 percent at 18+), adding ot_pts when it happens. Pooled quantiles were 2 to 4 cents off
    in the tails here (section 15 of claude/nba-halftime.md); the mixture is within 1.5 cents."""

    def __init__(self, sport, total, home_spread, home_pts, away_pts, center=None, center_w=1.0):
        m = MODEL[sport + '_q3']
        self.sport = sport
        self.stage = 'q3'
        home_fav_by = -(home_spread or 0)
        self.fav_by = abs(home_fav_by)
        m3 = home_pts - away_pts
        self.favm = m3 if home_fav_by >= 0 else -m3
        self.m3 = m3
        self.h1 = home_pts + away_pts               # points so far (through three), the offset for full-game lines
        c = m['coef']
        a = abs(m3)
        reg = c[0] + c[1] * total + c[2] * self.h1 + c[3] * a + c[4] * min(a, 5.0)
        self.p_ot = next(p for lim, p in m['ot'] if a <= lim)
        self.ot_pts = m['ot_pts']
        self.mu_reg_model = max(6.0, reg)
        self.mu_model = self.mu_reg_model + self.p_ot * self.ot_pts
        self.center = center
        self.center_w = 1.0 if center is None else max(0.0, min(1.0, center_w))
        self.mu = self.mu_model if center is None else max(6.0, self.center_w * self.mu_model + (1 - self.center_w) * center)
        self.mu_reg = max(6.0, self.mu - self.p_ot * self.ot_pts)
        self.sd_reg = m['k'] * math.sqrt(self.mu_reg)
        self.q = m['z']
        self.n = m['n']
        var = (1 - self.p_ot) * self.sd_reg ** 2 + self.p_ot * self.sd_reg ** 2 + self.p_ot * (1 - self.p_ot) * self.ot_pts ** 2
        self.sd = math.sqrt(var)
        self.state = 'trail' if self.favm < 0 else ('lead' if self.favm > 0 else 'tied')
        self.bucket = 'q3'
        self.ref = None
        self.median = self._median()

    def _cdf_reg(self, z):
        q = self.q
        if z <= q[0]:
            return 0.0
        if z >= q[-1]:
            return 1.0
        hi = bisect_right(q, z)
        lo = hi - 1
        f = (z - q[lo]) / ((q[hi] - q[lo]) or 1)
        return (lo + f) / (len(q) - 1)

    def cdf(self, x):
        return (1 - self.p_ot) * self._cdf_reg((x - self.mu_reg) / self.sd_reg) + self.p_ot * self._cdf_reg((x - self.ot_pts - self.mu_reg) / self.sd_reg)

    def _median(self):
        lo, hi = self.mu_reg - 40, self.mu_reg + 60
        for _ in range(40):
            mid = (lo + hi) / 2
            if self.cdf(mid) < 0.5:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def p_over_2h(self, t):
        """P(points left > t); points are whole numbers."""
        return 1 - self.cdf(math.floor(t) + 0.5)

    def p_push_2h(self, t):
        if float(t).is_integer():
            return max(0.0, self.cdf(t + 0.5) - self.cdf(t - 0.5))
        return 0.0

    def spot(self):
        a = abs(self.m3)
        if a <= 7:
            return f'end of 3rd, close game: 4th scores a point less, overtime {100*self.p_ot:.0f}% (the tail the ladder has to carry)'
        if a >= 18:
            return 'end of 3rd, blowout: no overtime tail, tight ladder, the leader gives back a sixth of the lead'
        return f'end of 3rd, {a}-point game: overtime {100*self.p_ot:.0f}%, no lean on the total'


# Second-half margin for the pregame favorite, NBA: the halftime lead shrinks. Fit on 14,691 games 2008-09 through
# 2019-20 with the market's sided 2H spread (claude/nba-halftime.md, section 13): a favorite down 15 at the half wins
# the second half by 7, a favorite up 15 loses it by 1. Ties the market's own 2H spread out of sample (MAE 7.88 vs
# 7.89); the naive line (half the spread, no shrink) is 3+ points off in 44 percent of games and loses 66 percent of
# them. Logged against Kalshi's spread ladder at the half; nothing prices off it until that log is graded.
MARGIN_2H = {'nba': (-0.52, 0.614, -0.268)}


def expected_margin(sport, home_spread, h1h, h1a):
    """(model_home_margin, naive_home_margin) expected at the final, from the half. Home margin: plus = home wins
    by that much. The naive number is the half margin plus half the pregame spread, the shrink left out."""
    c = MARGIN_2H.get(sport)
    if c is None:
        return None, None
    home_fav_by = -(home_spread or 0)
    fav_by = abs(home_fav_by)
    m1 = h1h - h1a
    favm = m1 if home_fav_by >= 0 else -m1
    fav2 = c[0] + c[1] * fav_by + c[2] * max(-22.0, min(22.0, favm))   # past 22 the shrink flattens (n 303: actual -1.5, linear -3.0)
    fav_final = favm + fav2
    naive_fav = favm + fav_by / 2
    sign = 1 if home_fav_by >= 0 else -1
    return round(sign * fav_final, 2), round(sign * naive_fav, 2)


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


def suggest(rows, quotes, order='taker', margin=0.03, trust=0.5, bankroll=3000.0, max_risk=75.0, max_cost=225.0, price_band=(15, 85), mid_loss=None):
    """quotes: {line: {'y': yes_ask_cents, 'n': no_ask_cents}} (None when missing).
    Legs priced outside price_band are ignored: the model's tails are its least trusted part, and a 3-cent edge
    on a 10-cent contract is a claim the data cannot back. Returns singles and middles sorted by edge.
    mid_loss: dollars a middle may lose on a miss (Nick's $15 cap); None sizes middles by max_risk alone."""
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
                risk = max_risk if mid_loss is None else min(max_risk, mid_loss)
                pairs = min(int(risk / loss + 1e-9), int(max_cost / c + 1e-9)) if loss > 0 else int(max_cost / c + 1e-9)
            pa, pb = a['price_c'] / 100, b['price_c'] / 100
            cost = round(pairs * (pa + pb) + order_fee(pairs, pa, order) + order_fee(pairs, pb, order), 2) if pairs else 0.0
            mids.append(dict(a=a, b=b, lo=a['line'] + 0.5, hi=b['line'] - 0.5, p_mid_model=p_mid_model, p_mid_mkt=p_mid_mkt, p_mid=p_mid,
                             c=c, ev=ev, loss=loss, ok=ok, pairs=pairs, cost=cost,
                             best=round(2 * pairs - cost, 2) if pairs else 0.0, worst=round(pairs - cost, 2) if pairs else 0.0))
    mids.sort(key=lambda x: -x['ev'])
    # Reverse middles (the "Polish middle"): NO on a lower strike plus YES on a higher one. One leg pays on any
    # final outside the hole, both lose on a final inside it, so the pair sells the window the middle buys:
    # EV a pair = 1 - cost - P(hole), the hole being the same numbers the middle wins on. It clears when the
    # ladder prices those numbers 3c too dear, the mirror of the middle's condition. Its EV equals the two
    # legs' single edges added together, so a pair that clears is two cheap wings; what the pair adds is far
    # less variance than either single alone, which is why it is sized as one bet (quarter Kelly on the pair,
    # the hole loss being the risk) under the single caps, never the middle's loss cap.
    revs = []
    for a in legs:
        if a['kind'] != 'under':
            continue
        for b in legs:
            if b['kind'] != 'over' or not b['line'] > a['line'] or b['line'] - a['line'] > 10:
                continue
            ra, rb = by_line[a['line']], by_line[b['line']]
            p_hole_model = max(0.0, ra['p_over'] - rb['p_over'] - rb['p_push'])
            p_hole_mkt = None if (ra['mkt_over'] is None or rb['mkt_over'] is None) else max(0.0, ra['mkt_over'] - rb['mkt_over'])
            p_hole = p_hole_model if p_hole_mkt is None else trust * p_hole_model + (1 - trust) * p_hole_mkt
            c = a['eff'] + b['eff']
            ev = 1 - c - p_hole
            pairs = 0
            if ev >= margin - 1e-9 and c < 1:
                f = max(0.0, 0.25 * ev / (1 - c))
                budget = min(f * bankroll, max_risk)
                pairs = min(int(budget / c + 1e-9), int(max_cost / c + 1e-9))
            ok = pairs >= 1
            pa, pb = a['price_c'] / 100, b['price_c'] / 100
            cost = round(pairs * (pa + pb) + order_fee(pairs, pa, order) + order_fee(pairs, pb, order), 2) if pairs else 0.0
            revs.append(dict(a=a, b=b, lo=a['line'] + 0.5, hi=b['line'] - 0.5, p_hole_model=p_hole_model, p_hole_mkt=p_hole_mkt, p_hole=p_hole,
                             c=c, ev=ev, ok=ok, pairs=pairs, cost=cost,
                             win=round(pairs - cost, 2) if pairs else 0.0, lose=round(-cost, 2) if pairs else 0.0))
    revs.sort(key=lambda x: -x['ev'])
    return dict(legs=legs, singles=singles, mids=mids, revs=revs)


def rest_plan(model, rows, mode='fg', margin=0.03, bankroll=3000.0, max_risk=75.0, max_cost=225.0, rest_scale=0.5, mid_loss=None, near_pts=3.5):
    """Resting limit orders near fair: a quarter-Kelly size at the limit price (where the edge equals the margin),
    scaled by rest_scale because a resting order fills when the market moves through it. Also the best resting
    middle: YES on a lower line plus NO on a higher one, both at their limits ('middle'), and 'middles': that one
    plus the best wide one (strikes 6+ apart) when it is a different pair, so a push can offer a tight window and
    a wide one. near_pts is how far from fair a strike may sit: 3.5 for football, wider for the NBA ladder."""
    fl = fair_line(model, mode)
    near = [r for r in rows if abs(r['line'] - fl) <= near_pts and r['over_rest'] >= 1 and r['under_rest'] >= 1]
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
    best, best_tight, best_wide = None, None, None
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
            risk = max_risk if mid_loss is None else min(max_risk, mid_loss)
            pairs = min(int(risk / loss + 1e-9) if loss > 0 else 10**6, int(max_cost / c + 1e-9))
            pairs = int(pairs * rest_scale)
            if pairs < 1:
                continue
            cand = dict(a=a, b=b, p_mid=p_mid, c=c, ev=ev, pairs=pairs, cost=round(pairs * c, 2), best=round(pairs * (2 - c), 2), worst=round(pairs * (1 - c), 2))
            if best is None or cand['ev'] > best['ev']:
                best = cand
            if b['line'] - a['line'] < 6 and (best_tight is None or cand['ev'] > best_tight['ev']):
                best_tight = cand
            if b['line'] - a['line'] >= 6 and (best_wide is None or cand['ev'] > best_wide['ev']):
                best_wide = cand
    return dict(legs=legs, middle=best, middles=[m for m in (best_tight, best_wide) if m])


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
        rp = rest_plan(model, rows, mode, sizing.get('margin', 0.03), sizing.get('bankroll', 3000.0), sizing.get('max_risk', 75.0), sizing.get('max_cost', 225.0), mid_loss=sizing.get('mid_loss'))
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


def held_options(rows, quotes, h, margin=0.03, order='taker', price_band=(15, 85)):
    """What to do at the half with a total you already own, priced off the same ladder the push used.
    rows: price_lines() rows after suggest() (they carry used_over/used_under, the model-market blend).
    quotes: feeds.total_quotes(). h: dict(side 'yes'|'no', strike, shares, paid_c, fee).
    Returns dict(fair_c, sell, pair, layoff, free), each None when it does not apply:
      sell    the bid now, what closing nets after the taker fee, what holding is worth at fair, and the verdict:
              SELL when the bid net of fee pays at least the margin over fair, HOLD otherwise.
      pair    the other side on a strike beyond yours that clears as a single (edge at least the margin), your
              share count, so a final between the strikes pays both: the middle completion.
      layoff  the other side on a strike short of yours that clears as a single: a final past your strike pays
              your leg, a final short of the other pays that one, the numbers between lose both (the reverse).
      free    the other side beyond yours at a size your leg pays for, so no final loses, when its ask allows
              it; shown with the leg's own edge, which can be negative (that is the price of the insurance).
    Every number is dollars after fees. Nothing here places an order."""
    by_line = {r['line']: r for r in rows}
    r0 = by_line.get(h['strike'])
    if not r0:
        return None
    yes = h['side'] == 'yes'
    n, pa = int(h['shares']), h['paid_c'] / 100
    paid_fee = float(h.get('fee') or 0)
    fair = r0['used_over'] if yes else r0['used_under']
    basis = n * pa + paid_fee
    out = dict(fair_c=round(100 * fair, 1), sell=None, pair=None, layoff=None, free=None, hold_ev=round(n * fair - basis, 2))
    q0 = quotes.get(h['strike']) or {}
    bid = q0.get('yb') if yes else q0.get('nb')
    if bid:
        pb = bid / 100
        net = n * pb - order_fee(n, pb, 'taker') - basis
        out['sell'] = dict(bid_c=bid, pnl=round(net, 2), hold=out['hold_ev'],
                           verdict='SELL' if pb - fee_per(pb, 'taker') >= fair + margin - 1e-9 else 'HOLD')
    # the other side's legs, with their single edge at the asks (the model-market blend against the ask, fees in)
    lo, hi = price_band
    cands = []
    for k, q in quotes.items():
        if k == h['strike'] or k not in by_line:
            continue
        ask = q.get('n') if yes else q.get('y')
        if ask is None or not lo <= ask <= hi:
            continue
        r = by_line[k]
        p = ask / 100
        eff = p + fee_per(p, order)
        fair_k = r['used_under'] if yes else r['used_over']
        cands.append(dict(strike=k, ask_c=ask, edge=fair_k - eff, p=p, beyond=(k > h['strike']) if yes else (k < h['strike'])))
    def table(c, m):
        """Dollars on each final once m shares of the other side are bought at c['ask_c']: your leg alone, the
        other alone, both (a completion) or neither (a lay-off's hole)."""
        p = c['p']
        fee_b = order_fee(m, p, order)
        new_cost = m * p + fee_b
        mine = n - basis                      # your leg pays
        other = m - new_cost                  # the other leg pays
        return dict(shares=m, cost=round(new_cost, 2), mine_alone=round(mine - new_cost, 2), other_alone=round(other - basis, 2),
                    both=round(mine + other, 2), neither=round(-basis - new_cost, 2))
    def window(c):
        a, b = sorted([h['strike'], c['strike']])
        return a + 0.5, b - 0.5
    best_pair = max((c for c in cands if c['beyond'] and c['edge'] >= margin - 1e-9), key=lambda c: c['edge'], default=None)
    if best_pair:
        t = table(best_pair, n)
        w = window(best_pair)
        out['pair'] = dict(kind='under' if yes else 'over', strike=best_pair['strike'], ask_c=best_pair['ask_c'], edge_c=round(100 * best_pair['edge'], 1),
                           lo=w[0], hi=w[1], shares=n, cost=t['cost'], both=t['both'], mine_alone=t['mine_alone'], other_alone=t['other_alone'])
    best_lay = max((c for c in cands if not c['beyond'] and c['edge'] >= margin - 1e-9), key=lambda c: c['edge'], default=None)
    if best_lay:
        t = table(best_lay, n)
        w = window(best_lay)
        out['layoff'] = dict(kind='under' if yes else 'over', strike=best_lay['strike'], ask_c=best_lay['ask_c'], edge_c=round(100 * best_lay['edge'], 1),
                             lo=w[0], hi=w[1], shares=n, cost=t['cost'], mine_alone=t['mine_alone'], other_alone=t['other_alone'], neither=t['neither'])
    # a free completion: the most shares of the other side your leg's win pays for, where the other side alone
    # also nets zero or better; the closest strike beyond yours whose ask allows it
    free = None
    for c in sorted((c for c in cands if c['beyond']), key=lambda c: abs(c['strike'] - h['strike'])):
        p = c['p']
        win = n - basis
        m = int(win / (p + fee_per(p, order)) + 1e-9)
        while m > 0 and table(c, m)['mine_alone'] < -1e-9:
            m -= 1
        if m >= 1 and table(c, m)['other_alone'] >= -1e-9:
            t = table(c, m)
            w = window(c)
            free = dict(kind='under' if yes else 'over', strike=c['strike'], ask_c=c['ask_c'], edge_c=round(100 * c['edge'], 1),
                        lo=w[0], hi=w[1], shares=m, cost=t['cost'], both=t['both'], mine_alone=t['mine_alone'], other_alone=t['other_alone'])
            break
    out['free'] = free
    return out


def signed(x):
    """Dollars with a sign for a table of finals: +$20, -$5, $0."""
    return '$0' if abs(x) < 0.5 else f"{'+' if x > 0 else '-'}${abs(x):.0f}"


def held_lines(h, o):
    """The YOU HOLD block of a push for one held leg, from held_options()."""
    side = 'Over' if h['side'] == 'yes' else 'Under'
    other = 'UNDER' if h['side'] == 'yes' else 'OVER'
    out = [f"YOU HOLD {side} {h['strike']:.1f}, {int(h['shares'])} sh at {h['paid_c']:.0f}c. Fair now {o['fair_c']:.0f}c."]
    s = o.get('sell')
    if s:
        out.append(f"Bid {s['bid_c']}c: {s['verdict']}. Sell now {signed(s['pnl'])}; holding is worth {signed(s['hold'])} at fair."
                   if s['verdict'] == 'SELL' else f"Bid {s['bid_c']}c: HOLD. Sell now {signed(s['pnl'])}; holding is worth {signed(s['hold'])} at fair.")
    p = o.get('pair')
    if p:
        out.append(f"PAIR IT: Buy {other} {p['strike']:.1f} at {p['ask_c']}c, {p['shares']} sh (${p['cost']:.0f}). Final {p['lo']:.0f} to {p['hi']:.0f} pays both ({signed(p['both'])}); "
                   f"{side.lower()} alone {signed(p['mine_alone'])}; {other.lower()} alone {signed(p['other_alone'])}. Edge +{p['edge_c']:.1f}c a share.")
    f = o.get('free')
    if f and not (p and p['strike'] == f['strike'] and p['shares'] <= f['shares']):
        out.append(f"FREE: Buy {other} {f['strike']:.1f} at {f['ask_c']}c, {f['shares']} sh (${f['cost']:.0f}): no final loses. Final {f['lo']:.0f} to {f['hi']:.0f} pays {signed(f['both'])}; "
                   f"{side.lower()} alone {signed(f['mine_alone'])}; {other.lower()} alone {signed(f['other_alone'])}. That leg is {f['edge_c']:+.1f}c of fair.")
    l = o.get('layoff')
    if l:
        mine_when = f"{h['strike'] + 0.5:.0f} or more" if h['side'] == 'yes' else f"{h['strike'] - 0.5:.0f} or less"
        other_when = f"{l['strike'] - 0.5:.0f} or less" if h['side'] == 'yes' else f"{l['strike'] + 0.5:.0f} or more"
        out.append(f"LAY OFF: Buy {other} {l['strike']:.1f} at {l['ask_c']}c, {l['shares']} sh (${l['cost']:.0f}). Final {mine_when} pays your {side.lower()} ({signed(l['mine_alone'])}); "
                   f"{other_when} pays the {other.lower()} ({signed(l['other_alone'])}); {l['lo']:.0f} to {l['hi']:.0f} loses both ({signed(l['neither'])}). Edge +{l['edge_c']:.1f}c a share.")
    if not (s or p or f or l):
        out.append('No bid, and nothing on the other side clears. Hold.')
    return out


def american(c):
    """Kalshi cents -> American odds string."""
    p = c / 100
    if p >= 0.5:
        return f"{-round(100 * p / (1 - p)):d}"
    return f"+{round(100 * (1 - p) / p):d}"


def money(x):
    """-5 -> 'loses $5', 12 -> 'wins $12', 0.4 -> 'even'. A middle whose miss wins or breaks even is a free roll,
    and the push says so where this is used for the miss."""
    if abs(x) < 1:
        return 'even'
    return f"loses ${-x:.0f}" if x < 0 else f"wins ${x:.0f}"


def miss_text(x):
    """The miss line of a middle: 'loses $5', or 'even (free roll)' / 'wins $3 (free roll)' when no final loses."""
    return money(x) + ('' if x < 0 else ' (free roll)')


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


def chosen_rev(sug):
    """The reverse middle a push names: the best one that clears, or None."""
    return next((r for r in sug.get('revs') or [] if r['ok']), None)


def rev_lines(r, alone):
    """The reverse-middle lines of a push: both legs with shares and dollars, then what each final does."""
    a, b = r['a'], r['b']
    head = 'REVERSE MIDDLE:' if alone else 'REVERSE MIDDLE (instead of the above, not on top):'
    return [head,
            f"Buy UNDER {a['line']:.1f} at {a['price_c']}c ({r['pairs']} shares for ${r['pairs'] * a['price_c'] / 100:.0f})",
            f"Buy OVER {b['line']:.1f} at {b['price_c']}c ({r['pairs']} shares for ${r['pairs'] * b['price_c'] / 100:.0f})",
            f"Final {r['lo'] - 1:.0f} or less, or {r['hi'] + 1:.0f} or more, pays one leg (+${r['win']:.0f}, {100 * (1 - r['p_hole']):.0f}%); "
            f"final {r['lo']:.0f} to {r['hi']:.0f} loses both (-${-r['lose']:.0f}). Edge +{100 * r['ev']:.1f}c a pair."]


def cancel_by(model):
    return 'by the first timeout of the 4th' if getattr(model, 'stage', None) == 'q3' else 'by the 4th'


def rest_block(model, rows, sizing, mode='fg', head='POSSIBLE MIDDLE (post as limit orders):'):
    """The resting-middle lines of a push: one middle for football, a tight one and a wide one for a sport that
    sets near_pts wide enough to hold both. (lines, plan)"""
    rp = rest_plan(model, rows, mode, sizing.get('margin', 0.03), sizing.get('bankroll', 3000.0), sizing.get('max_risk', 75.0), sizing.get('max_cost', 225.0),
                   mid_loss=sizing.get('mid_loss'), near_pts=sizing.get('near_pts', 3.5))
    out = []
    for i, m in enumerate(rp.get('middles') or []):
        a, b = m['a'], m['b']
        label = head if i == 0 else 'WIDER MIDDLE (place this OR the one above, not both):'
        out += [label,
                f"Buy OVER {a['line']:.1f} at {a['over_rest']}c ({m['pairs']} shares for ${m['pairs'] * a['over_rest'] / 100:.0f})",
                f"Buy UNDER {b['line']:.1f} at {b['under_rest']}c ({m['pairs']} shares for ${m['pairs'] * b['under_rest'] / 100:.0f})",
                f"Both filled: final {a['line'] + 0.5:.0f} to {b['line'] - 0.5:.0f} wins both (+${m['best']:.0f}, hits {100*m['p_mid']:.0f}%); any other final {miss_text(m['worst'])}. One side alone is a fair single."]
        if i == 0 and len(rp['middles']) > 1:
            out.append('')
    return out, rp


def closest_middle_line(sug, margin=0.03):
    """One line on the best middle at the asks when nothing clears: how far it sits from the margin. Windows of
    4 to 8 numbers (the ones worth posting) first; anything else only if no such window has a quote."""
    sized = [m for m in sug['mids'] if 3 <= m['b']['line'] - m['a']['line'] <= 8]
    best = (sized[:1] or sug['mids'][:1] or [None])[0]
    if not best:
        return None
    return (f"Closest middle at the asks: OVER {best['a']['line']:.1f} at {best['a']['price_c']}c + UNDER {best['b']['line']:.1f} at {best['b']['price_c']}c "
            f"= ${best['c']:.2f} a pair, hits {100*best['p_mid']:.0f}%, edge {100*best['ev']:+.1f}c (needs +{100*margin:.0f}).")


def order_sheet(model, inp, rows, sug, sizing, mode='fg', tickers=None, top=3, focus=None):
    """The push text Nick asked for: PLAY when something clears, UPDATE otherwise.
    Returns (kind, title, body): title is 'PLAY: Away 21, Home 45', body is the order lines.
    Names come from inp['away_name'] / inp['home_name'] when given.
    focus='middles' (the NBA): the middle leads the PLAY, singles follow, and every push ends with the resting
    middles (a tight one and a wide one) and, on an UPDATE, the closest middle at the asks."""
    away = inp.get('away_name') or inp.get('away', 'Away')
    home = inp.get('home_name') or inp.get('home', 'Home')
    score = f"{away} {inp['h1a']}, {home} {inp['h1h']}"
    fl = fair_line(model, mode)
    ctx = f"Fair total {fl:.1f}. {model.spot().capitalize()}."
    singles, mid = chosen(sug, top)
    rev = chosen_rev(sug)
    if focus == 'middles':
        out = [ctx, '']
        if mid:
            m = mid
            a, b = m['a'], m['b']
            out += ['MIDDLE (clears the edge at the asks):',
                    f"Buy OVER {a['line']:.1f} at {a['price_c']}c ({m['pairs']} shares for ${m['pairs'] * a['price_c'] / 100:.0f})",
                    f"Buy UNDER {b['line']:.1f} at {b['price_c']}c ({m['pairs']} shares for ${m['pairs'] * b['price_c'] / 100:.0f})",
                    f"Final {m['lo']:.0f} to {m['hi']:.0f} wins both (+${m['best']:.0f}, hits {100*m['p_mid']:.0f}%); any other final {miss_text(m['worst'])}.", '']
        if singles:
            out.append('SINGLE' + ('S' if len(singles) > 1 else '') + (' (instead of the middle, not on top of it):' if mid else ':'))
            for s in singles:
                side = 'OVER' if s['kind'] == 'over' else 'UNDER'
                out.append(f"Buy {side} {s['line']:.1f} for ${s['cost']:.0f} at {s['price_c']}c ({american(s['price_c'])})")
            if len(singles) > 1:
                out.append('Best first. The others are backups if that price is gone, not a stack.')
            out.append('')
        if rev:
            out += rev_lines(rev, not (mid or singles)) + ['']
        if not (mid or singles or rev):
            out.append('No single or middle clears at the asks.')
            cl = closest_middle_line(sug, sizing.get('margin', 0.03))
            if cl:
                out.append(cl)
            out.append('')
        rest, rp = rest_block(model, rows, sizing, mode, head=f'RESTING MIDDLE (post as limit orders, cancel what has not filled {cancel_by(model)}):')
        if rest:
            out += rest
        elif not (mid or singles or rev):
            near = sorted(rows, key=lambda r: abs(r['line'] - fl))[:2]
            out.append('No middle to post. Fair prices: ' + '; '.join(f"OVER {r['line']:.1f} {r['over_rest']}c / UNDER {r['line']:.1f} {r['under_rest']}c" for r in near) + '.')
        kind = 'PLAY' if (mid or singles or rev) else 'UPDATE'
        return kind, f'{kind}: {score}', '\n'.join(out).rstrip()
    if mid or singles or rev:
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
                    f"Final {m['lo']:.0f} to {m['hi']:.0f} wins both (+${m['best']:.0f}, hits {100*m['p_mid']:.0f}%); any other final {miss_text(m['worst'])}."]
        if rev:
            if mid:
                out.append('')
            out += rev_lines(rev, not (mid or singles))
        return 'PLAY', f'PLAY: {score}', '\n'.join(out).rstrip()
    out = [ctx, '']
    rp = rest_plan(model, rows, mode, sizing.get('margin', 0.03), sizing.get('bankroll', 3000.0), sizing.get('max_risk', 75.0), sizing.get('max_cost', 225.0), mid_loss=sizing.get('mid_loss'), near_pts=sizing.get('near_pts', 3.5))
    m = rp['middle']
    if m:
        a, b = m['a'], m['b']
        out += ['POSSIBLE MIDDLE (post as limit orders):',
                f"Buy OVER {a['line']:.1f} at {a['over_rest']}c ({m['pairs']} shares for ${m['pairs'] * a['over_rest'] / 100:.0f})",
                f"Buy UNDER {b['line']:.1f} at {b['under_rest']}c ({m['pairs']} shares for ${m['pairs'] * b['under_rest'] / 100:.0f})",
                f"Both filled: final {a['line'] + 0.5:.0f} to {b['line'] - 0.5:.0f} wins both (+${m['best']:.0f}, hits {100*m['p_mid']:.0f}%); any other final {miss_text(m['worst'])}. One side alone is a fair single."]
    else:
        near = sorted(rows, key=lambda r: abs(r['line'] - fl))[:2]
        out.append('No middle to post. Fair prices: ' + '; '.join(f"OVER {r['line']:.1f} {r['over_rest']}c / UNDER {r['line']:.1f} {r['under_rest']}c" for r in near) + '.')
    return 'UPDATE', f'UPDATE: {score}', '\n'.join(out).rstrip()
