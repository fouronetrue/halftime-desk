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

    def __init__(self, sport, total, home_spread, h1h, h1a, center=None, center_w=1.0, shift=0.0, width=1.0):
        """shift: points added to the model's own second-half mean before the blend (the NFL bad-weather
        haircut, -1 in rain, snow or 16+ mph wind outdoors; tail study, Oct 24). width: the ladder's spread as
        a multiple of the block's (0.87 in a 28+ point college mismatch, where the second half is more
        predictable than the block says; same study). Both default to no change."""
        m = MODEL.get(sport) or MODEL['nfl']
        self.sport = sport
        self.shift, self.width = float(shift or 0.0), float(width or 1.0)
        home_fav_by = -(home_spread or 0)
        self.fav_by = abs(home_fav_by)
        m1 = h1h - h1a
        self.favm = m1 if home_fav_by >= 0 else -m1
        self.h1 = h1h + h1a
        c = m['coef']
        mu = c[0] + c[1] * total + c[2] * self.h1 + c[3] * abs(self.favm) + c[4] * self.favm + c[5] * (self.fav_by if self.favm < 0 else 0)
        if len(c) > 6:
            # the running clock: past the knee (two scores) each point of halftime margin takes points off the
            # second half, over and above the linear margin terms (the CFB refit, scripts/fit_cfb.py)
            mu += c[6] * max(0.0, abs(self.favm) - m.get('knee', 14))
        self.mu_model = max(8.0, mu + self.shift)
        self.center = center
        self.center_w = 1.0 if center is None else max(0.0, min(1.0, center_w))
        self.q = m['z']
        if center is None:
            self.mu = self.mu_model
        else:
            # A market line is where the market puts 50-50: its median. The block's residual median sits below its
            # mean (q[100] is negative in every block), so the center is first turned into the mean that puts this
            # block's median on the line, then blended. Taking the line as the mean shifted every ladder down by
            # half a point to a point and under-said the over by 2 to 3 cents at every strike (trust study, Oct 22).
            cm = center
            for _ in range(5):
                cm = center - m['k'] * math.sqrt(max(8.0, cm)) * self.q[100]
            self.mu = max(8.0, self.center_w * self.mu_model + (1 - self.center_w) * cm)
        self.sd = m['k'] * math.sqrt(self.mu) * self.width
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
        self.q = m['z']
        self.n = m['n']
        self.k = m['k']
        if center is None:
            self.mu = self.mu_model
        else:
            # the center is the market's median of the points left (see HalfModel): find the mean whose mixture
            # median lands on it, then blend
            cm = center
            for _ in range(4):
                cm += center - self._median_for(cm)
            self.mu = max(6.0, self.center_w * self.mu_model + (1 - self.center_w) * cm)
        self._set_shape(self.mu)
        self.state = 'trail' if self.favm < 0 else ('lead' if self.favm > 0 else 'tied')
        self.bucket = 'q3'
        self.ref = None
        self.median = self._median()

    def _set_shape(self, mu):
        """The regulation and mixture spread for a mean of mu (points left, overtime chance included)."""
        self.mu = mu
        self.mu_reg = max(6.0, mu - self.p_ot * self.ot_pts)
        self.sd_reg = self.k * math.sqrt(self.mu_reg)
        var = (1 - self.p_ot) * self.sd_reg ** 2 + self.p_ot * self.sd_reg ** 2 + self.p_ot * (1 - self.p_ot) * self.ot_pts ** 2
        self.sd = math.sqrt(var)

    def _median_for(self, mu):
        """The mixture's median when its mean is mu."""
        self._set_shape(max(6.0, mu))
        return self._median()

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
                # a middle the loss cap cannot fit one pair of is not a play (the cap counts what you already
                # hold on the total, so a built middle at the cap leaves no room for another)
                ok = pairs >= 1
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
    sharp = f" Book 2H {inp['sharp']:.1f}." if inp.get('sharp') is not None else ''
    lines = [f"{away} {inp['h1a']}, {home} {inp['h1h']} at the half. Fair {what} {fl:.1f}. 2H expected {model.mu:.1f} points.{sharp} {model.spot().capitalize()}."]
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


def leg_basis(h):
    """What a held leg cost all in: shares at the price paid, plus the fee paid."""
    return int(h['shares']) * h['paid_c'] / 100 + float(h.get('fee') or 0)


def pnl_regions(legs, extra_strikes=()):
    """Dollars a set of legs on one total makes on every final, as regions between the strikes.
    legs: dicts with side ('yes' is Over, 'no' is Under), strike (x.5), shares, paid_c, fee. Each entry:
    lo, hi (the whole-number finals in the region, hi None above the top strike, lo None below the bottom one)
    and pnl. extra_strikes adds boundaries so a new leg at one of them can be priced per region."""
    strikes = sorted({float(h['strike']) for h in legs} | {float(k) for k in extra_strikes})
    if not strikes:
        return []
    bounds = [None] + strikes + [None]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        probe = (b - 10) if a is None else (a + 10 if b is None else (a + b) / 2)   # a final inside the region
        pnl = 0.0
        for h in legs:
            wins = probe > h['strike'] if h['side'] == 'yes' else probe < h['strike']
            pnl += (int(h['shares']) - leg_basis(h)) if wins else -leg_basis(h)
        out.append(dict(lo=None if a is None else a + 0.5, hi=None if b is None else b - 0.5, pnl=round(pnl, 2)))
    return out


def held_miss_loss(legs):
    """What a middle you already hold on this total loses on a miss, which counts against the middle loss cap
    before a new one is sized (Nick, Oct 22). The legs are a middle when an over sits on a lower strike than an
    under; then the position's worst final is its miss. A lone leg, two overs, or a reverse is not a middle and
    counts nothing: a single's downside is the single caps' business, not the middle cap's."""
    overs = [float(h['strike']) for h in legs if h['side'] == 'yes']
    unders = [float(h['strike']) for h in legs if h['side'] == 'no']
    if not overs or not unders or min(overs) >= max(unders):
        return 0.0
    regs = pnl_regions(legs)
    return round(max(0.0, -min(r['pnl'] for r in regs)), 2) if regs else 0.0


def region_prob(rows, lo, hi):
    """P(final in the region) from the ladder's blended fair (used_over per strike, set by suggest()); None when
    a strike the region needs was not priced."""
    by_line = {r['line']: r for r in rows}
    def p_over(k):
        r = by_line.get(k)
        return None if r is None else r.get('used_over', r['p_over'])
    lo_k = None if lo is None else lo - 0.5
    hi_k = None if hi is None else hi + 0.5
    a = 1.0 if lo_k is None else p_over(lo_k)
    b = 0.0 if hi_k is None else p_over(hi_k)
    if a is None or b is None:
        return None
    return max(0.0, a - b)


def no_lose_hedge(legs, rows, quotes, order='taker', price_band=(15, 85)):
    """The cheapest leg that leaves no final losing once added to what you hold on this total: every strike on
    the ladder, either side, at its ask. It covers the net downside of the whole position, not one leg: the old
    FREE line sized the hedge to the held over's whole win and ignored the under held next to it (Patriots at
    Bears, Oct 22: it put the only loss on the likeliest final). None when nothing loses now or no leg does it.
    Returns dict(kind, strike, ask_c, shares, cost, edge_c, regions) with the dollars on each final after it."""
    base = pnl_regions(legs)
    if not base or min(r['pnl'] for r in base) >= -1e-9:
        return None
    by_line = {r['line']: r for r in rows}
    lo_c, hi_c = price_band
    mine = {float(h['strike']) for h in legs}
    best = None
    for k, q in quotes.items():
        r = by_line.get(k)
        if not r or float(k) in mine:
            continue   # the other side of a strike you hold is a partial sell; the sell verdict covers that
        for side, ask in (('yes', q.get('y')), ('no', q.get('n'))):
            if ask is None or not lo_c <= ask <= hi_c:
                continue
            p = ask / 100
            fp = fee_per(p, order)
            regs = pnl_regions(legs, [k])
            m_min, m_max = 1, 10**7
            feasible = True
            for g in regs:
                probe = (g['hi'] - 1) if g['lo'] is None else g['lo']
                wins = probe > k if side == 'yes' else probe < k
                if wins:
                    if g['pnl'] < 0:
                        m_min = max(m_min, math.ceil(-g['pnl'] / (1 - p - fp) - 1e-9))
                elif g['pnl'] < 0:
                    feasible = False
                    break
                else:
                    m_max = min(m_max, int(g['pnl'] / (p + fp) + 1e-9))
            if not feasible or m_min > m_max:
                continue
            new = dict(side=side, strike=k, shares=m_min, paid_c=ask, fee=0.0)
            def table(m):
                new['shares'], new['fee'] = m, order_fee(m, p, order)
                return pnl_regions(legs + [new])
            m = m_min
            while m <= m_max and min(g['pnl'] for g in table(m)) < -1e-9:
                m += 1   # fee rounding can leave a region a few cents short
            if m > m_max:
                continue
            t = table(m)
            cost = round(m * p + order_fee(m, p, order), 2)
            fair_k = r.get('used_over', r['p_over']) if side == 'yes' else r.get('used_under', r['p_under'])
            cand = dict(kind='over' if side == 'yes' else 'under', strike=k, ask_c=ask, shares=m, cost=cost,
                        edge_c=round(100 * (fair_k - p - fp), 1), regions=t, floor=round(min(g['pnl'] for g in t), 2))
            if best is None or (cand['cost'], -cand['edge_c']) < (best['cost'], -best['edge_c']):
                best = cand
    return best


def held_position(rows, quotes, legs, margin=0.03, order='taker', price_band=(15, 85)):
    """Everything you hold on one total, read as one position off the ladder the push used.
    rows: price_lines() rows after suggest() (used_over is the model-market blend). quotes: feeds.total_quotes().
    legs: dicts with side, strike, shares, paid_c, fee, ticker. Returns None when no leg sits on a priced strike.
      legs     each leg with fair_c (what it is worth now), hold_ev, and sell: the bid, what closing nets after
               the taker fee, and the verdict (SELL when the bid net of fee pays at least the margin over fair).
      regions  dollars on every final, with the chance of each from the blended ladder.
      miss_loss  the most the position loses on any final; window when the legs are one middle (an over on a
               lower strike and an under on a higher one), the finals that pay both.
      hedge    the cheapest leg that leaves no final losing, sized to the net downside (no_lose_hedge).
    Nothing here places an order."""
    by_line = {r['line']: r for r in rows}
    kept = []
    for h in legs:
        r0 = by_line.get(h['strike'])
        if not r0:
            continue
        yes = h['side'] == 'yes'
        n = int(h['shares'])
        fair = r0['used_over'] if yes else r0['used_under']
        basis = leg_basis(h)
        leg = dict(ticker=h.get('ticker'), side=h['side'], strike=h['strike'], shares=n, paid_c=h['paid_c'], fee=h.get('fee'),
                   fair_c=round(100 * fair, 1), hold_ev=round(n * fair - basis, 2), sell=None)
        q0 = quotes.get(h['strike']) or {}
        bid = q0.get('yb') if yes else q0.get('nb')
        if bid:
            pb = bid / 100
            leg['sell'] = dict(bid_c=bid, pnl=round(n * pb - order_fee(n, pb, 'taker') - basis, 2), hold=leg['hold_ev'],
                               verdict='SELL' if pb - fee_per(pb, 'taker') >= fair + margin - 1e-9 else 'HOLD')
        kept.append(leg)
    if not kept:
        return None
    regs = pnl_regions(kept)
    for g in regs:
        g['p'] = region_prob(rows, g['lo'], g['hi'])
    overs = [h for h in kept if h['side'] == 'yes']
    unders = [h for h in kept if h['side'] == 'no']
    window = None
    if len(overs) == 1 and len(unders) == 1 and overs[0]['strike'] < unders[0]['strike']:
        window = (overs[0]['strike'] + 0.5, unders[0]['strike'] - 0.5)
    return dict(legs=kept, regions=regs, miss_loss=held_miss_loss(kept), window=window,
                no_lose=min(g['pnl'] for g in regs) >= -1e-9,
                hedge=no_lose_hedge(kept, rows, quotes, order, price_band))


def finals_text(regions):
    """A region list as words: '50 or less -$93 (17%), 51 to 57 +$186 (25%), 58 or more +$46'."""
    parts = []
    for g in regions:
        if g['lo'] is None:
            span = f"{g['hi']:.0f} or less"
        elif g['hi'] is None:
            span = f"{g['lo']:.0f} or more"
        elif g['lo'] == g['hi']:
            span = f"{g['lo']:.0f}"
        else:
            span = f"{g['lo']:.0f} to {g['hi']:.0f}"
        p = g.get('p')
        parts.append(f"{span} {signed(g['pnl'])}" + (f" ({100 * p:.0f}%)" if p is not None else ''))
    return ', '.join(parts)


def held_block(pos):
    """The YOU HOLD lines of a push, one position per total: a line a leg with one verdict and one number, the
    finals together when there is more than one leg, and the no-lose hedge when one exists."""
    out = []
    for h in pos['legs']:
        side = 'Over' if h['side'] == 'yes' else 'Under'
        s = h.get('sell')
        if s and s['verdict'] == 'SELL':
            verdict = f"Worth {h['fair_c']:.0f}c. Bid {s['bid_c']}c: SELL for {signed(s['pnl'])}."
        else:
            verdict = f"Worth {h['fair_c']:.0f}c. Hold."
        out.append(f"YOU HOLD {side} {h['strike']:.1f}, {h['shares']} sh at {h['paid_c']:.0f}c. {verdict}")
    if len(pos['legs']) > 1:
        lead = f"Together it's a {pos['window'][0]:.0f} to {pos['window'][1]:.0f} middle: " if pos.get('window') else 'Together: '
        out.append(lead + finals_text(pos['regions']) + '.' + (' No final loses.' if pos['no_lose'] else ''))
    hd = pos.get('hedge')
    if hd:
        side = 'Over' if hd['kind'] == 'over' else 'Under'
        e = hd['edge_c']
        tail = f" The leg is {abs(e):.1f}c {'under' if e < 0 else 'over'} fair." if abs(e) >= 0.05 else ''
        out.append(f"NO-LOSE HEDGE: buy {side} {hd['strike']:.1f} at {hd['ask_c']}c, {hd['shares']} sh (${hd['cost']:.0f}). "
                   f"Then {finals_text(hd['regions'])}.{tail}")
    return out


def signed(x):
    """Dollars with a sign for a table of finals: +$20, -$5, $0."""
    return '$0' if abs(x) < 0.5 else f"{'+' if x > 0 else '-'}${abs(x):.0f}"


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
    """The miss of a middle, in dollars: '-$5', or '+$2 (free roll)' when no final loses."""
    return signed(x) + ('' if x < 0 else ' (free roll)')


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


def mid_lines(a_line, a_c, b_line, b_c, pairs, best, worst, p_mid, tail=''):
    """A middle as three lines: both legs with shares and dollars, then the finals in dollars."""
    return [f"Over {a_line:.1f} at {a_c}c, {pairs} sh (${pairs * a_c / 100:.0f})",
            f"Under {b_line:.1f} at {b_c}c, {pairs} sh (${pairs * b_c / 100:.0f})",
            f"{a_line + 0.5:.0f} to {b_line - 0.5:.0f} pays +${best:.0f} ({100 * p_mid:.0f}%). Any other final {miss_text(worst)}.{tail}"]


def rest_block(model, rows, sizing, mode='fg', head='REST A MIDDLE:', both=False):
    """The resting-middle lines of a push: the best resting middle for football, a tight one and a wide one
    (both=True, the NBA) for a sport that sets near_pts wide enough to hold both. When what you already hold on
    the total has used up the middle loss cap (sizing['held_miss'] against sizing['mid_loss_cap']), one line
    says so instead. (lines, plan)"""
    rp = rest_plan(model, rows, mode, sizing.get('margin', 0.03), sizing.get('bankroll', 3000.0), sizing.get('max_risk', 75.0), sizing.get('max_cost', 225.0),
                   mid_loss=sizing.get('mid_loss'), near_pts=sizing.get('near_pts', 3.5))
    out = []
    mids = (rp.get('middles') or []) if both else [m for m in [rp.get('middle')] if m]
    for i, m in enumerate(mids):
        a, b = m['a'], m['b']
        out.append(head if i == 0 else 'WIDER MIDDLE (this OR the one above, not both):')
        out += mid_lines(a['line'], a['over_rest'], b['line'], b['under_rest'], m['pairs'], m['best'], m['worst'], m['p_mid'], ' One leg alone is a fair single.')
        if i == 0 and len(mids) > 1:
            out.append('')
    if not out:
        note = cap_note(sizing)
        if note:
            out.append(note)
    return out, rp


def cap_note(sizing):
    """One line when the middle loss cap is already spent by what you hold on this total, else None."""
    cap, held = sizing.get('mid_loss_cap'), sizing.get('held_miss') or 0
    if cap is None or not held:
        return None
    room = max(0.0, cap - held)
    if room >= 1:
        return None
    return f"Nothing new to post: what you hold already risks ${held:.0f} on a miss, the ${cap:.0f} middle cap."


def closest_middle_line(sug, margin=0.03):
    """One line on the best middle at the asks when nothing clears: how far it sits from the margin. Windows of
    4 to 8 numbers (the ones worth posting) first; anything else only if no such window has a quote."""
    sized = [m for m in sug['mids'] if 3 <= m['b']['line'] - m['a']['line'] <= 8]
    best = (sized[:1] or sug['mids'][:1] or [None])[0]
    if not best:
        return None
    return (f"Closest middle at the asks: OVER {best['a']['line']:.1f} at {best['a']['price_c']}c + UNDER {best['b']['line']:.1f} at {best['b']['price_c']}c "
            f"= ${best['c']:.2f} a pair, hits {100*best['p_mid']:.0f}%, edge {100*best['ev']:+.1f}c (needs +{100*margin:.0f}).")


def shot_lines(shot):
    """The SHOT line for the push (the mismatch lane in shadow): the narrowed ladder's best high-probability side,
    its price and fair, the size at the cap, and that it is logged, not a play. None when nothing clears."""
    picks = (shot or {}).get('picks') or []
    if not picks:
        return None
    x = picks[0]
    side = 'OVER' if x['kind'] == 'over' else 'UNDER'
    return [f"SHOT (shadow, {shot['spread']:g}-point spread): {side} {x['line']:.1f} at {x['price_c']}c, fair {100 * x['fair_used']:.0f}c "
            f"(desk says {100 * x['fair_live']:.0f}c). {x['contracts']} sh for ${x['cost']:.0f} wins ${x['win']:.0f}. Logged, not a play."]


def order_sheet(model, inp, rows, sug, sizing, mode='fg', tickers=None, top=3, focus=None, held=None, shot=None):
    """The push text: PLAY when something clears, UPDATE otherwise. Returns (kind, title, body).
    The order never changes (Nick, Oct 22): the score and fair against the book, then what to do (singles,
    the middle, the reverse), then what you hold (held: the YOU HOLD lines from held_block), then the resting
    middle. Names come from inp['away_name'] / inp['home_name'] when given.
    focus='middles' (the NBA): the middle leads the PLAY, singles follow, every push ends with the resting
    middles (a tight one and a wide one) and, on an UPDATE, the closest middle at the asks."""
    away = inp.get('away_name') or inp.get('away', 'Away')
    home = inp.get('home_name') or inp.get('home', 'Home')
    score = f"{away} {inp['h1a']}, {home} {inp['h1h']}"
    fl = fair_line(model, mode)
    # the book's full-game number: the points so far plus the sharp second-half line, when one was read
    book = None if inp.get('sharp') is None else (0 if mode == '2h' else inp['h1a'] + inp['h1h']) + inp['sharp']
    ctx = f"Fair {fl:.1f}." + (f" Book {book:.1f}." if book is not None else '') + (f" {inp['weather']}" if inp.get('weather') else '')
    singles, mid = chosen(sug, top)
    rev = chosen_rev(sug)
    held = [l for l in (held or []) if l]
    shot = [l for l in (shot or []) if l]
    out = [ctx, '']
    if focus == 'middles':
        if mid:
            m = mid
            out += ['MIDDLE (clears at the asks):'] + mid_lines(m['a']['line'], m['a']['price_c'], m['b']['line'], m['b']['price_c'], m['pairs'], m['best'], m['worst'], m['p_mid']) + ['']
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
        if held:
            out += held + ['']
        rest, rp = rest_block(model, rows, sizing, mode, head=f'REST A MIDDLE (cancel what has not filled {cancel_by(model)}):', both=True)
        if rest:
            out += rest
        elif not (mid or singles or rev):
            near = sorted(rows, key=lambda r: abs(r['line'] - fl))[:2]
            out.append('No middle to post. Fair prices: ' + '; '.join(f"OVER {r['line']:.1f} {r['over_rest']}c / UNDER {r['line']:.1f} {r['under_rest']}c" for r in near) + '.')
        kind = 'PLAY' if (mid or singles or rev) else 'UPDATE'
        return kind, f'{kind}: {score}', '\n'.join(out).rstrip()
    if mid or singles or rev:
        if singles:
            for s in singles:
                side = 'OVER' if s['kind'] == 'over' else 'UNDER'
                out.append(f"Buy {side} {s['line']:.1f} for ${s['cost']:.0f} at {s['price_c']}c ({american(s['price_c'])})")
            if len(singles) > 1:
                out.append('Best first. The others are backups if that price is gone, not a stack.')
            out.append('')
        if mid:
            m = mid
            out += ['MIDDLE' + (' (instead of a single, not on top of one):' if singles else ':')] + \
                   mid_lines(m['a']['line'], m['a']['price_c'], m['b']['line'], m['b']['price_c'], m['pairs'], m['best'], m['worst'], m['p_mid']) + ['']
        if rev:
            out += rev_lines(rev, not (mid or singles)) + ['']
        if shot:
            out += shot + ['']
        if held:
            out += held + ['']
        return 'PLAY', f'PLAY: {score}', '\n'.join(out).rstrip()
    if shot:
        out += shot + ['']
    if held:
        out += held + ['']
    rest, rp = rest_block(model, rows, sizing, mode)
    if rest:
        out += rest
    else:
        near = sorted(rows, key=lambda r: abs(r['line'] - fl))[:2]
        out.append('No middle to post. Fair prices: ' + '; '.join(f"OVER {r['line']:.1f} {r['over_rest']}c / UNDER {r['line']:.1f} {r['under_rest']}c" for r in near) + '.')
    return 'UPDATE', f'UPDATE: {score}', '\n'.join(out).rstrip()
