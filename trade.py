"""Order executor: the one module in Halftime Desk that may send an order to Kalshi.

Shadow by default. In shadow mode the worker writes every order it would have sent to the orders table in
Supabase (price, size, window, reason) and watches the ladder to say whether it would have filled; nothing
goes to Kalshi. Live mode sends the same orders, and only when all of these hold at the moment of sending:
  1. config.json has "auto": {"mode": "live", ...}
  2. the environment has TRADE_ENABLED=1
  3. the trade key is in the environment: KALSHI_TRADE_KEY_ID and KALSHI_TRADE_PRIVATE_KEY (a second Kalshi
     key, kept in the Railway worker's variables only, never in GitHub secrets, so the Actions backup can never
     trade; portfolio.py keeps using the read-only pair and still signs GET requests only)
  4. the control row in Supabase (id 'trade') does not say kill
Every order is a limit order at a price the engine set (the resting limit, or the ask the engine priced), for a
count the engine sized, with a client_order_id built from the game, window, strike, side and price (a restart
cannot post the same order twice) and an expiration at the window's end (a dead worker leaves nothing resting).
tests/trade_guard.py pins all of it.

What gets planned at each break (the first look at the half, and the NBA's end of the third):
  rest   the resting middle legs: 'pair' mode posts the push's resting middle(s) (the tight and wide pair for the
         NBA), 'ladder' mode posts YES on every strike at or below fair and NO on every strike at or above it
         within rest_near_pts, each at the resting limit (fair minus the margin, maker, no fee). Sized by the
         auto cap: if every order filled, the worst final loses at most pair_miss_pct of bankroll (pair_miss_max
         dollars when set, the phase 1 number), less what you already hold on the total.
  take   with "singles": true (phase 3), the push's first single and the cleared middle at the asks as
         immediate-or-cancel limit orders at the price the push named. Shadow mode plans them too, so the
         readout says how often the ask was still there.
Budgets: open resting orders at once under rest_capital_pct of bankroll; once the night's graded auto orders
have lost night_loss_pct of bankroll (night_loss_max dollars when set), nothing new is posted that night;
max_orders_per_game and max_orders_per_night as hard stops.

Shadow fill model: a resting YES bid at P counts as touched when a later quote shows the YES ask at or under P
(someone sold through our price), a NO bid the same way on the NO ask; a take counts when the ask it was
priced at is still at or under the price on the next quote. The worker keeps reading the ladder for a game with
open orders through the third quarter (rest_until 'q4'), so the readout can split fills at the break from fills
in play, which is the question the live phase answers: a fill in play is a fill because the game moved against
the leg, and only the live week says what that is worth.

Nothing here runs unless config.json carries an "auto" block.
"""
import os, re, json, time, uuid, base64, datetime as dt
import engine, feeds, store

try:
    import requests
except ImportError:
    requests = None

ORDERS = 'orders'
CONTROL = 'control'
# The only lines in the repo that name an order endpoint (tests/readonly.py allows them here and nowhere else).
ORDER_PATH = '/portfolio/orders'
BASE = os.environ.get('KALSHI_API_BASE') or feeds.KALSHI
NS = uuid.UUID('6f1b2a3c-4d5e-4f60-8a71-9b82c3d4e5f6')   # client_order_id namespace

DEFAULTS = dict(mode='shadow', sports=['nba'], rest_mode='pair', rest_until='q4',
                pair_miss_pct=0.5, pair_miss_max=None, night_loss_pct=5.0, night_loss_max=None, rest_capital_pct=40.0,
                singles=False, max_orders_per_game=12, max_orders_per_night=200)
# Minutes from the first look at a break to the end of that break, and to the start of the fourth quarter.
BREAK_MIN = {'half': {'nfl': 14, 'cfb': 21, 'nba': 16}, 'q3': {'nba': 4}}
Q4_MIN = {'half': {'nfl': 60, 'cfb': 70, 'nba': 50}, 'q3': {'nba': 10}}   # q3: until about the first timeout of the 4th


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_ts(s):
    try:
        t = dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def order_id(game_id, stage, side, strike, price_c, kind, reason=''):
    """Deterministic: the same intent on a restart gets the same id, so the orders table (and Kalshi) see one order."""
    return str(uuid.uuid5(NS, f'{game_id}|{stage}|{side}|{float(strike):g}|{int(price_c)}|{kind}|{reason}'))


# ---------- the trade key (separate from the read-only pair in portfolio.py) ----------
def key_present():
    return bool(os.environ.get('KALSHI_TRADE_KEY_ID') and os.environ.get('KALSHI_TRADE_PRIVATE_KEY'))


def load_trade_key():
    pem = os.environ.get('KALSHI_TRADE_PRIVATE_KEY') or ''
    if '\\n' in pem and '\n' not in pem:
        pem = pem.replace('\\n', '\n')
    if not pem.strip():
        return None
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(pem.strip().encode() + b'\n', password=None)


def sign(key, ts_ms, method, path):
    """Kalshi's request signature: base64(sign(timestamp + METHOD + path)), path with the /trade-api/v2 prefix and
    no query string. This signer takes POST and DELETE; portfolio.py's takes GET only, and keeps its own test."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, ed25519, rsa
    msg = f'{ts_ms}{method}{path}'.encode()
    if isinstance(key, ed25519.Ed25519PrivateKey):
        sig = key.sign(msg)
    elif isinstance(key, rsa.RSAPrivateKey):
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size), hashes.SHA256())
    else:
        raise ValueError(f'unsupported key type {type(key).__name__}')
    return base64.b64encode(sig).decode()


def api(method, path, body=None, params=None, key=None, tries=2):
    """A signed call with the trade key. path is relative to BASE (e.g. ORDER_PATH)."""
    if requests is None:
        raise RuntimeError('requests is not installed')
    key = key or load_trade_key()
    if key is None:
        raise RuntimeError('no trade key in the environment')
    full = BASE.split('://', 1)[1]
    sign_path = full[full.index('/'):] + path
    last = None
    for i in range(tries):
        ts = str(int(time.time() * 1000))
        headers = {'KALSHI-ACCESS-KEY': os.environ['KALSHI_TRADE_KEY_ID'], 'KALSHI-ACCESS-TIMESTAMP': ts,
                   'KALSHI-ACCESS-SIGNATURE': sign(key, ts, method, sign_path), 'User-Agent': 'halftime-desk/1.0', 'Content-Type': 'application/json'}
        try:
            r = requests.request(method, BASE + path, params=params, data=None if body is None else json.dumps(body), headers=headers, timeout=15)
            if r.status_code < 300:
                return r.json() if r.text else {}
            last = f'HTTP {r.status_code} {r.text[:240]}'
            if 400 <= r.status_code < 500 and r.status_code != 429:
                break   # a rejected order or a bad key will not get better on retry
        except Exception as e:
            last = str(e)
        time.sleep(1.0 * (i + 1))
    raise RuntimeError(f'{method} {path} failed: {last}')


class Trader:
    """Plans, records and (when armed) sends orders for one Desk. One per process; the worker owns it."""

    def __init__(self, config, bankroll):
        auto = config.get('auto') if isinstance(config, dict) else None
        self.on = isinstance(auto, dict)
        self.cfg = {**DEFAULTS, **(auto or {})}
        self.bank = float(bankroll)
        self.db_ok = True          # set False once the orders table says it is not there yet (one line, then quiet)
        self._kill = (None, 0.0)   # (value, read time)
        self.night = {}            # date_et -> dict(open_cost, orders, pnl) cache, refreshed from the table per plan
        self.sent = []             # (game, side, strike, price, count) this process sent live, for the log line

    # ---- switches ----
    def mode(self):
        return 'live' if self.cfg.get('mode') == 'live' else 'shadow'

    def kill(self):
        """The control row's kill flag, read at most every 5 seconds; True when it cannot be read in live mode
        (no read, no send)."""
        if time.time() - self._kill[1] < 5:
            return self._kill[0]
        val = True
        if store.enabled():
            rows = store.read(CONTROL, {'select': 'kill', 'id': 'eq.trade'})
            if rows:
                val = bool(rows[0].get('kill'))
        self._kill = (val, time.time())
        return val

    def armed(self):
        """Live sending allowed right now: every switch on, nothing else counts."""
        return bool(self.on and self.mode() == 'live' and os.environ.get('TRADE_ENABLED') == '1' and key_present() and requests is not None
                    and not self.kill())

    def wants(self, sport):
        return self.on and sport in (self.cfg.get('sports') or [])

    # ---- caps ----
    def cap_game(self):
        cap = self.bank * float(self.cfg['pair_miss_pct']) / 100
        mx = self.cfg.get('pair_miss_max')
        return min(cap, float(mx)) if mx is not None else cap

    def cap_night(self):
        cap = self.bank * float(self.cfg['night_loss_pct']) / 100
        mx = self.cfg.get('night_loss_max')
        return min(cap, float(mx)) if mx is not None else cap

    def cap_capital(self):
        return self.bank * float(self.cfg['rest_capital_pct']) / 100

    def night_state(self, date_et):
        """What tonight's auto orders have done so far: open resting cost, orders planned, graded P&L."""
        st = dict(open_cost=0.0, orders=0, pnl=0.0)
        if store.enabled() and self.db_ok:
            rows = store.read(ORDERS, {'select': 'status,cost,pnl,expire_at,mode', 'date_et': f'eq.{date_et}', 'mode': f'eq.{self.mode()}', 'limit': 5000})
            now = now_iso()
            for r in rows:
                st['orders'] += 1
                if r.get('status') in ('planned', 'sent', 'resting') and (r.get('expire_at') or '') > now:
                    st['open_cost'] += float(r.get('cost') or 0)
                if r.get('pnl') is not None:
                    st['pnl'] += float(r['pnl'])
        self.night[date_et] = st
        return st

    # ---- planning ----
    def expiries(self, sport, stage, start_iso):
        start = parse_ts(start_iso) or dt.datetime.now(dt.timezone.utc)
        brk = start + dt.timedelta(minutes=BREAK_MIN.get(stage, {}).get(sport, 16))
        q4 = start + dt.timedelta(minutes=Q4_MIN.get(stage, {}).get(sport, 50))
        return brk, q4

    def plan(self, g, rec, stage, m, rows, sug, quotes, ev, sizing, ts, held_legs=None):
        """The orders for this break, sized under the caps. Returns the list (possibly empty) and a note."""
        sport = g['sport']
        if not self.wants(sport):
            return [], None
        focus = sport in ('nba',)
        held_legs = held_legs or []
        held_miss = engine.held_miss_loss(held_legs) if held_legs else 0.0
        cap = max(0.0, self.cap_game() - held_miss)
        night = self.night_state(g['date_et'])
        if night['pnl'] <= -self.cap_night():
            return [], f"night budget spent ({night['pnl']:+.0f} on ${self.cap_night():.0f})"
        if night['orders'] >= int(self.cfg['max_orders_per_night']):
            return [], f"{night['orders']} orders tonight, the max"
        if cap < 1:
            return [], f"what you hold already risks ${held_miss:.0f} on a miss, the ${self.cap_game():.0f} auto cap"
        brk, q4 = self.expiries(sport, stage, ts)
        expire = q4 if self.cfg.get('rest_until') == 'q4' else brk
        margin = sizing.get('margin', 0.03)
        near_pts = sizing.get('near_pts', 3.5)
        rp = engine.rest_plan(m, rows, 'fg', margin, self.bank, sizing['max_risk'], sizing['max_cost'], mid_loss=cap, near_pts=near_pts)
        legs = {}   # (side, strike) -> dict
        def add(side, strike, price_c, n, reason, pair=None):
            if n < 1 or not price_c or price_c < 1:
                return
            k = (side, float(strike))
            cur = legs.get(k)
            if cur is None or n > cur['count']:
                legs[k] = dict(side=side, strike=float(strike), price_c=int(price_c), count=int(n), reason=reason, pair=pair, kind='rest')
        if self.cfg.get('rest_mode') == 'ladder':
            fl = engine.fair_line(m)
            by_line = {l['line']: l for l in rp['legs']}
            for line, l in sorted(by_line.items()):
                if line <= fl:
                    add('yes', line, l['y_c'], l['y_n'], 'ladder')
                if line >= fl:
                    add('no', line, l['n_c'], l['n_n'], 'ladder')
        else:
            mids = (rp.get('middles') or []) if focus else [x for x in [rp.get('middle')] if x]
            for i, md in enumerate(mids):
                a, b = md['a'], md['b']
                pair = f"{a['line']:g}/{b['line']:g}"
                reason = 'rest_mid wide' if (focus and i > 0) else 'rest_mid'
                add('yes', a['line'], a['over_rest'], md['pairs'], reason, pair)
                add('no', b['line'], b['under_rest'], md['pairs'], reason, pair)
        # the cap counts every leg at once: if all fill, the worst final may not lose more than cap (fees: maker, none)
        legs = self.fit_cap(list(legs.values()), held_legs, cap)
        # takes: what the push led with, at the asks it named (the middle in a middle-focus sport when one cleared,
        # else the first single; the backups are not a stack). Phase 3 sends them; shadow records them.
        takes = []
        if self.cfg.get('singles') or self.mode() == 'shadow':
            singles, mid = engine.chosen(sug, 1)
            if mid and (focus or not singles):
                pair = f"{mid['a']['line']:g}/{mid['b']['line']:g}"
                takes.append(dict(side='yes', strike=float(mid['a']['line']), price_c=int(mid['a']['price_c']), count=int(mid['pairs']), reason='play_mid', pair=pair, kind='take'))
                takes.append(dict(side='no', strike=float(mid['b']['line']), price_c=int(mid['b']['price_c']), count=int(mid['pairs']), reason='play_mid', pair=pair, kind='take'))
            elif singles:
                s = singles[0]
                takes.append(dict(side='yes' if s['kind'] == 'over' else 'no', strike=float(s['line']), price_c=int(s['price_c']), count=int(s['contracts']),
                                  reason='single', pair=None, kind='take'))
        out = []
        budget = self.cap_capital() - night['open_cost']
        for o in legs + [t for t in takes if t['count'] >= 1]:
            q = quotes.get(o['strike']) or {}
            tk = q.get('ticker')
            if not tk:
                continue
            cost = round(o['count'] * o['price_c'] / 100, 2)
            if o['kind'] == 'rest':
                if cost > budget:
                    o['count'] = int(budget * 100 / o['price_c'])
                    cost = round(o['count'] * o['price_c'] / 100, 2)
                    if o['count'] < 1:
                        continue
                budget -= cost
            exp = expire if o['kind'] == 'rest' else brk
            out.append(dict(client_order_id=order_id(g['id'], stage, o['side'], o['strike'], o['price_c'], o['kind'], o['reason']), created_at=ts,
                            game_id=g['id'], sport=sport, game=g['short'], date_et=g['date_et'], event_ticker=ev.get('event_ticker'), market_ticker=tk,
                            strike=o['strike'], side=o['side'], action='buy', kind=o['kind'], stage=stage, price_c=o['price_c'], count=o['count'], cost=cost,
                            expire_at=exp.isoformat(), reason=o['reason'], pair=o['pair'], mode=self.mode(), status='planned',
                            kalshi_order_id=None, sent_at=None, filled_count=None, fill_price_c=None, filled_at=None, touched_at=None, touch_phase=None,
                            touch_s=None, pnl=None, graded_at=None, final_total=None, note=None))
            if len(out) >= int(self.cfg['max_orders_per_game']):
                break
        return out, None

    @staticmethod
    def fit_cap(legs, held_legs, cap):
        """Scale a set of resting legs down until the worst final (every leg filled, plus what is already held)
        loses no more than cap. The held legs' own miss was already taken off the cap; they are in the table so a
        new leg that deepens their worst final counts."""
        if not legs:
            return []
        def worst(scale):
            tbl = [dict(side=h['side'], strike=h['strike'], shares=int(h['shares']), paid_c=h['paid_c'], fee=h.get('fee') or 0) for h in held_legs]
            tbl += [dict(side=l['side'], strike=l['strike'], shares=max(0, int(l['count'] * scale)), paid_c=l['price_c'], fee=0) for l in legs]
            regs = engine.pnl_regions(tbl)
            base = engine.pnl_regions([dict(side=h['side'], strike=h['strike'], shares=int(h['shares']), paid_c=h['paid_c'], fee=h.get('fee') or 0) for h in held_legs]) if held_legs else []
            base_min = min((r['pnl'] for r in base), default=0.0)
            return min(r['pnl'] for r in regs) - min(0.0, base_min)   # the loss the new legs add on the worst final
        s = 1.0
        for _ in range(12):
            if worst(s) >= -cap - 1e-9:
                break
            s *= 0.8
        else:
            return []
        out = []
        for l in legs:
            n = int(l['count'] * s)
            if n >= 1:
                out.append(dict(l, count=n))
        return out

    # ---- recording and sending ----
    def record(self, rows):
        if not rows or not store.enabled() or not self.db_ok:
            return False
        ok = store.write(ORDERS, rows, on_conflict='client_order_id', ignore_duplicates=True)
        if not ok:
            self.db_ok = False
            print("orders: the table is not there yet (run supabase/011_orders.sql); auto orders are not being recorded")
        return ok

    def act(self, orders):
        """Shadow: record. Live: send each order and record what Kalshi said. Returns the rows as recorded."""
        if not orders:
            return []
        if not self.armed():
            for o in orders:
                o['mode'] = 'shadow' if self.mode() != 'live' else 'live'
                if self.mode() == 'live':
                    o['status'] = 'skipped'
                    o['note'] = 'not armed (TRADE_ENABLED, key or kill)'
            self.record(orders)
            return orders
        for o in orders:
            self.send(o)
        self.record(orders)
        return orders

    def send(self, o):
        """One live order. Every check here is a hard wall, whatever the planner did."""
        assert o['kind'] in ('rest', 'take') and o['side'] in ('yes', 'no') and o['action'] == 'buy'
        assert 1 <= int(o['price_c']) <= 99 and int(o['count']) >= 1
        if not self.armed():
            o.update(status='skipped', note='not armed at send time')
            return o
        exp = parse_ts(o['expire_at'])
        body = dict(ticker=o['market_ticker'], action='buy', side=o['side'], type='limit', count=int(o['count']),
                    client_order_id=o['client_order_id'], expiration_ts=int(exp.timestamp()) if exp else None)
        body[o['side'] + '_price'] = int(o['price_c'])
        if o['kind'] == 'rest':
            body['post_only'] = True
        else:
            body['time_in_force'] = 'immediate_or_cancel'
        try:
            res = api('POST', ORDER_PATH, body)
            order = res.get('order') or res
            o.update(status=order.get('status') or 'sent', kalshi_order_id=order.get('order_id'), sent_at=now_iso())
            fc = order.get('fill_count_fp') or order.get('fill_count')
            if fc not in (None, ''):
                o['filled_count'] = float(fc)
            if o['status'] in ('executed', 'filled'):
                o['status'] = 'filled'
            self.sent.append((o['game'], o['side'], o['strike'], o['price_c'], o['count']))
            print(f"sent {o['game']} {o['side'].upper()} {o['strike']:g} at {o['price_c']}c x{o['count']} ({o['reason']}): {o['status']}")
        except Exception as e:
            o.update(status='rejected', note=str(e)[:240])
            print(f"order rejected {o['game']} {o['side']} {o['strike']:g}: {e}")
        return o

    def cancel(self, o, why):
        if not o.get('kalshi_order_id') or o.get('status') not in ('sent', 'resting'):
            return
        try:
            api('DELETE', f"{ORDER_PATH}/{o['kalshi_order_id']}")
            o.update(status='cancelled', note=why)
        except Exception as e:
            o['note'] = f'cancel failed: {e}'[:240]

    def cancel_game(self, rec, why):
        """Live only: pull every resting order on a game (the score moved, or a kill)."""
        rows = []
        for st in rec.get('auto', {}).values():
            for o in st.get('open') or []:
                if o.get('mode') == 'live' and o.get('kalshi_order_id') and o.get('status') in ('sent', 'resting'):
                    self.cancel(o, why)
                    rows.append(o)
        if rows:
            store.write(ORDERS, rows, on_conflict='client_order_id')

    # ---- the shadow fill model, and status refresh for live orders ----
    def touch(self, g, rec, quotes, phase, at=None):
        """Mark open orders whose price the ladder has reached. Returns the rows that changed."""
        at = at or now_iso()
        changed = []
        for stage, st in (rec.get('auto') or {}).items():
            start = parse_ts(st.get('at'))
            keep = []
            for o in st.get('open') or []:
                if o.get('status') not in ('planned', 'sent', 'resting'):
                    continue
                if (o.get('created_at') or '') >= at:
                    keep.append(o)   # the pass that planned it: a take at the ask it was priced at is trivially there
                    continue
                if (o.get('expire_at') or '') <= at:
                    if o.get('mode') == 'shadow':
                        o['status'] = 'expired'
                        changed.append(o)
                    elif o.get('status') in ('sent', 'resting'):
                        o['status'] = 'expired'   # Kalshi expires it on its own clock; the refresh confirms
                        changed.append(o)
                    continue
                q = quotes.get(float(o['strike'])) or {}
                ask = q.get('y') if o['side'] == 'yes' else q.get('n')
                if o.get('mode') == 'shadow' and ask is not None and ask <= o['price_c']:
                    secs = int((parse_ts(at) - start).total_seconds()) if start else None
                    o.update(status='touched', touched_at=at, touch_phase=phase, touch_s=secs)
                    changed.append(o)
                    continue
                keep.append(o)
            st['open'] = keep
        if changed:
            store.write(ORDERS, changed, on_conflict='client_order_id')
        return changed

    def refresh(self, rec):
        """Live orders: ask Kalshi what became of each open one (resting, executed, canceled, expired)."""
        if not self.on or self.mode() != 'live' or not key_present():
            return
        changed = []
        for stage, st in (rec.get('auto') or {}).items():
            keep = []
            for o in st.get('open') or []:
                if o.get('mode') != 'live' or not o.get('kalshi_order_id') or o.get('status') not in ('sent', 'resting'):
                    if o.get('status') in ('planned', 'sent', 'resting'):
                        keep.append(o)
                    continue
                try:
                    res = api('GET', f"{ORDER_PATH}/{o['kalshi_order_id']}")
                    order = res.get('order') or res
                    status = order.get('status') or o['status']
                    fc = order.get('fill_count_fp') or order.get('fill_count') or 0
                    o['filled_count'] = float(fc)
                    if status == 'executed' or (status == 'canceled' and float(fc) > 0):
                        o.update(status='filled' if float(fc) >= o['count'] else 'partial', filled_at=now_iso())
                    elif status in ('canceled', 'expired'):
                        o['status'] = status if status == 'expired' else 'cancelled'
                    else:
                        o['status'] = 'resting'
                        keep.append(o)
                    changed.append(o)
                except Exception as e:
                    o['note'] = f'refresh: {e}'[:200]
                    keep.append(o)
            st['open'] = keep
        if changed:
            store.write(ORDERS, changed, on_conflict='client_order_id')

    # ---- grading ----
    @staticmethod
    def pnl_of(o, T):
        """Dollars a filled order made on final total T (maker fills pay no fee; takes pay the taker fee)."""
        n = float(o.get('filled_count') if o.get('mode') == 'live' and o.get('filled_count') is not None else o['count'])
        p = o['price_c'] / 100
        win = T > o['strike'] if o['side'] == 'yes' else T < o['strike']
        fee = engine.order_fee(int(n), p, 'taker') if o['kind'] == 'take' else 0.0
        return round((n * (1 - p) - fee) if win else (-n * p - fee), 2)

    def grade(self, g, rec, T):
        """Grade this game's auto orders at the final: every touched (shadow) or filled (live) order gets a pnl."""
        if not self.on or not store.enabled() or not self.db_ok:
            return None
        rows = store.read(ORDERS, {'select': '*', 'game_id': f"eq.{g['id']}", 'limit': 500})
        if not rows:
            return None
        out, pnl, n = [], 0.0, 0
        for o in rows:
            if o.get('status') in ('planned', 'sent', 'resting'):
                o['status'] = 'expired'
            if o.get('status') in ('touched', 'filled', 'partial'):
                o['pnl'] = self.pnl_of(o, T)
                pnl += o['pnl']
                n += 1
            o['final_total'] = T
            o['graded_at'] = now_iso()
            out.append(o)
        store.write(ORDERS, out, on_conflict='client_order_id')
        rec['auto_graded'] = dict(at=now_iso(), fills=n, pnl=round(pnl, 2))
        return dict(fills=n, pnl=round(pnl, 2), orders=len(out))


def readout(date_from=None, mode=None):
    """The shadow (or live) readout: orders by sport, kind and reason; fills at the break vs in play; P&L."""
    params = {'select': '*', 'limit': 20000, 'order': 'created_at'}
    if date_from:
        params['date_et'] = f'gte.{date_from}'
    if mode:
        params['mode'] = f'eq.{mode}'
    rows = store.read(ORDERS, params)
    if not rows:
        return 'auto: no orders recorded'
    lines = []
    for md in sorted({r.get('mode') for r in rows}):
        for sport in sorted({r.get('sport') for r in rows if r.get('mode') == md}):
            for kind in ('rest', 'take'):
                rs = [r for r in rows if r.get('mode') == md and r.get('sport') == sport and r.get('kind') == kind]
                if not rs:
                    continue
                games = len({r['game_id'] for r in rs})
                filled = [r for r in rs if r.get('status') in ('touched', 'filled', 'partial')]
                brk = [r for r in filled if (r.get('touch_phase') or '') in ('half', 'early3', 'q3end', 'early4', '')]
                play = [r for r in filled if r not in brk]
                graded = [r for r in filled if r.get('pnl') is not None]
                pnl = sum(float(r['pnl']) for r in graded)
                cost = sum(float(r.get('cost') or 0) for r in graded)
                line = (f"auto {md} {sport} {kind}: {len(rs)} orders on {games} games, {len(filled)} filled ({len(brk)} at the break, {len(play)} in play)"
                        + (f", graded {len(graded)}: ${pnl:+.0f} on ${cost:.0f}" if graded else ''))
                # middles: both legs of a pair filled
                pairs = {}
                for r in rs:
                    if r.get('pair'):
                        pairs.setdefault((r['game_id'], r['pair'], r.get('reason')), []).append(r)
                both = sum(1 for v in pairs.values() if sum(1 for r in v if r.get('status') in ('touched', 'filled', 'partial')) >= 2)
                one = sum(1 for v in pairs.values() if sum(1 for r in v if r.get('status') in ('touched', 'filled', 'partial')) == 1)
                if pairs:
                    line += f"; middles {len(pairs)} posted, {both} filled both legs, {one} one leg"
                lines.append(line)
    secs = [r['touch_s'] for r in rows if r.get('touch_s') is not None and r.get('kind') == 'rest']
    if secs:
        secs.sort()
        lines.append(f"resting fills by seconds after the first look: median {secs[len(secs) // 2]}s, under 60s {sum(1 for s in secs if s < 60)}, "
                     f"1 to 5 min {sum(1 for s in secs if 60 <= s < 300)}, 5 to 15 min {sum(1 for s in secs if 300 <= s < 900)}, later {sum(1 for s in secs if s >= 900)}")
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--readout', action='store_true', help='print the shadow and live readout from the orders table')
    ap.add_argument('--since', help='date_et from (YYYY-MM-DD)')
    ap.add_argument('--mode', help='shadow or live')
    a = ap.parse_args()
    if a.readout:
        print(readout(a.since, a.mode))
