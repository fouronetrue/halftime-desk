"""Order executor: the one module in Halftime Desk that may send an order to Kalshi.

Two things live here.

1. The shadow planner, for every sport in config auto.sports. At each break the worker writes the orders it would
   have posted to the orders table in Supabase (price, size, window, reason) and watches the ladder to say whether
   they would have filled. Nothing goes to Kalshi. This is the fill model the scorecard reads.

2. The pilot (config auto.pilot): the only way an order leaves this module. For the sports it lists, at the first
   look at the half, the worker does what the push says, at pilot size: on a PLAY it takes the lead single, on a
   read it posts the REST A MIDDLE block's two legs. Only when all of these hold at the moment of sending:
     a. config.json has an auto.pilot block with the sport in pilot.sports and a wallet above zero
     b. the environment has TRADE_ENABLED=1
     c. the trade key is in the environment: KALSHI_TRADE_KEY_ID and KALSHI_TRADE_PRIVATE_KEY (a second Kalshi
        key, kept in the Railway worker's variables only, never in GitHub secrets, so the Actions backup can never
        trade; portfolio.py keeps using the read pair and still signs GET requests only)
     d. the control row in Supabase (id 'trade') does not say kill
     e. the self-test passed in this process (Trader.preflight): the key read its balance, and a one-contract YES
        bid at 1c and a one-contract NO bid at 1c were posted, read back as the side and price they were meant to
        be, and cancelled
   The money walls, checked inside send() for every order whatever planned it:
     the wallet     the most the pilot may lose, ever. Its realized P&L (graded live orders; an order from an
                    earlier night that may have filled and was never graded counts as lost) is read from the orders
                    table before every order. At minus the wallet it stops for good.
     the night cap  the most order money it may post in one night, filled or not, each order counted at its
                    limit price with its fee. A resting order that expires unfilled still counts, so the worst
                    night is bounded by a sum, not by a model.
     the leash      until the trade key is walled (locked to a numbered Kalshi subaccount that holds the wallet
                    and no more), the night cap and the sizes are the leash's: small. The full numbers apply only
                    to a walled key, where Kalshi itself refuses a cent past the wallet.
     the ceilings   PILOT_HARD below, in code: a typo in config cannot open more.
   An unreadable ledger stops an order (no read, no send). Every order is written to the table before it is sent
   (no record, no send), and the table's key is the order's id, so a restart cannot send it twice.

Every order is a limit order at a price the engine set (the resting limit, or the ask the engine priced), with a
client_order_id built from the game, window, strike, side, price and reason. A resting order is post-only and
carries an expiration at the end of the break (a dead worker leaves nothing resting); the worker also cancels it
when the second half starts. A take is immediate-or-cancel. tests/trade_guard.py and tests/pilot.py pin all of it.

Kalshi's order API (docs.kalshi.com, read Nov 12, 2026): orders are created and cancelled on the V2 event-order
path, which replaced the old write calls in June 2026. The book is the YES book: a bid buys YES at its price; an
ask sells YES, which is buying NO at 100 minus that price. Counts and prices are fixed-point strings. An order is
read back one at a time on the old read path. The legacy calls this module was first written for were never used.

What the shadow planner plans at each break (the first look at the half, and the NBA's end of the third):
  rest   the resting middle legs: 'pair' mode posts the push's resting middle(s) (the tight and wide pair for the
         NBA), 'ladder' mode posts YES on every strike at or below fair and NO on every strike at or above it
         within rest_near_pts, each at the resting limit (fair minus the margin and the maker fee). Sized by the
         auto cap: if every order filled, the worst final loses at most pair_miss_pct of bankroll (pair_miss_max
         dollars when set), less what you already hold on the total.
  take   the push's first single, or the cleared middle at the asks, as immediate-or-cancel limit orders at the
         price the push named, so the readout says how often the ask was still there.
Budgets: open resting orders at once under rest_capital_pct of bankroll; once the night's graded shadow orders
have lost night_loss_pct of bankroll (night_loss_max dollars when set), nothing new is planned that night;
max_orders_per_game and max_orders_per_night as hard stops.

Shadow fill model: a resting YES bid at P counts as touched when a later quote shows the YES ask at or under P
(someone sold through our price), a NO bid the same way on the NO ask; a take counts when the ask it was
priced at is still at or under the price on the next quote. The worker keeps reading the ladder for a game with
open orders through the third quarter (rest_until 'q4'), so the readout can split fills at the break from fills
in play. The split came back on Nov 12 (claude/go-live-nov12.md): the legs touched in play lost, the legs touched
during the break about broke even. So a live resting order never outlives the break; rest_until 'q4' is the
shadow model's measuring window.

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
ORDER_PATH = '/portfolio/events/orders'     # create (POST) and cancel (DELETE .../{order_id}): Kalshi's V2 order calls
ORDER_READ_PATH = '/portfolio/orders'       # read one order back (GET .../{order_id})
BALANCE_PATH = '/portfolio/balance'
BASE = os.environ.get('KALSHI_API_BASE') or feeds.KALSHI
NS = uuid.UUID('6f1b2a3c-4d5e-4f60-8a71-9b82c3d4e5f6')   # client_order_id namespace

DEFAULTS = dict(mode='shadow', sports=['nba'], rest_mode='pair', rest_until='q4',
                pair_miss_pct=0.5, pair_miss_max=None, night_loss_pct=5.0, night_loss_max=None, rest_capital_pct=40.0,
                singles=False, max_orders_per_game=12, max_orders_per_night=200)
# The pilot's numbers when config does not give them. wallet 0 is off. leash: what applies until the key is walled.
PILOT = dict(sports=[], wallet=0.0, night_cap=200.0, rest_pairs=5, single_cost=15.0, kinds=['rest', 'take'],
             leash=dict(night_cap=50.0, rest_pairs=3, single_cost=5.0))
# Ceilings in code, whatever config says: the most the wallet and a night may be, the most one order may cost or
# hold, and the most orders in a night. Raising one of these is a commit, with a reason.
PILOT_HARD = dict(wallet=500.0, night_cap=250.0, order_cost=20.0, order_count=40, orders_per_night=150)
MAX_REST_MIN = 30      # a resting order must expire inside this many minutes of being sent
WALL_SLACK = 1.5       # a key counts as walled while the balance it sees is under this many wallets (winnings stay in)
OPEN = ('planned', 'sent', 'resting', 'unconfirmed')
# Minutes from the first look at a break to the end of that break, and to the start of the fourth quarter.
BREAK_MIN = {'half': {'nfl': 14, 'cfb': 21, 'nba': 16, 'cbb': 16}, 'q3': {'nba': 4}}
# q3: until about the first timeout of the 4th; college basketball has no 4th, so its rest runs to about the under-12 timeout
Q4_MIN = {'half': {'nfl': 60, 'cfb': 70, 'nba': 50, 'cbb': 40}, 'q3': {'nba': 10}}
SPORT_NAME = {'cbb': 'college basketball', 'cfb': 'college football', 'nba': 'the NBA', 'nfl': 'the NFL'}


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_ts(s):
    try:
        t = dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def fnum(v):
    """A number from Kalshi's fixed-point strings ('3.00', '0.4200'), or None."""
    try:
        return None if v in (None, '') else float(v)
    except (TypeError, ValueError):
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
    no query string. This signer takes GET, POST and DELETE; portfolio.py's takes GET only, and keeps its own test."""
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


class ApiError(RuntimeError):
    """A Kalshi call that did not succeed. status is the HTTP status, or None when no answer came back (a timeout
    or a dropped connection: the call may or may not have landed)."""
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def api(method, path, body=None, params=None, key=None, tries=2, timeout=8):
    """A signed call with the trade key. path is relative to BASE (e.g. ORDER_PATH). Raises ApiError. The timeout is
    short on purpose: these calls run inside the pass that prices a break, and a slow Kalshi must not hold the
    next game's push."""
    if requests is None:
        raise ApiError('requests is not installed')
    try:
        key = key or load_trade_key()
    except Exception as e:   # a key pasted wrong is a refusal to send, never a crash in the middle of a pass
        raise ApiError(f'the trade key could not be read ({type(e).__name__}): check KALSHI_TRADE_PRIVATE_KEY is the whole key, BEGIN line to END line')
    if key is None or not os.environ.get('KALSHI_TRADE_KEY_ID'):
        raise ApiError('no trade key in the environment')
    full = BASE.split('://', 1)[1]
    sign_path = full[full.index('/'):] + path
    last, status = None, None
    for i in range(tries):
        ts = str(int(time.time() * 1000))
        try:
            headers = {'KALSHI-ACCESS-KEY': os.environ['KALSHI_TRADE_KEY_ID'], 'KALSHI-ACCESS-TIMESTAMP': ts,
                       'KALSHI-ACCESS-SIGNATURE': sign(key, ts, method, sign_path), 'User-Agent': 'halftime-desk/1.0', 'Content-Type': 'application/json'}
        except Exception as e:
            raise ApiError(f'the request could not be signed ({type(e).__name__}: {e})')
        try:
            r = requests.request(method, BASE + path, params=params, data=None if body is None else json.dumps(body), headers=headers, timeout=timeout)
            if r.status_code < 300:
                return r.json() if r.text else {}
            last, status = f'HTTP {r.status_code} {r.text[:240]}', r.status_code
            if 400 <= r.status_code < 500 and r.status_code != 429:
                break   # a rejected order or a bad key will not get better on retry
        except Exception as e:
            last, status = str(e), None
        if i + 1 < tries:
            time.sleep(1.0 * (i + 1))
    raise ApiError(f'{method} {path} failed: {last}', status)


def order_body(o):
    """One order as Kalshi's V2 create call takes it. The book is the YES book: side 'yes' (the over) is a bid at
    its price; side 'no' (the under) is an ask at 100 minus its price, which is buying NO at that price (Kalshi:
    bid is yes, ask is no, always, and the price does not change with direction). A resting order is post-only
    with an expiration; a take is immediate-or-cancel."""
    yes_c = int(o['price_c']) if o['side'] == 'yes' else 100 - int(o['price_c'])
    body = dict(ticker=o['market_ticker'], side='bid' if o['side'] == 'yes' else 'ask', count=f"{int(o['count'])}.00", price=f'{yes_c / 100:.4f}',
                self_trade_prevention_type='taker_at_cross', client_order_id=o['client_order_id'], cancel_order_on_pause=True)
    if o['kind'] == 'rest':
        exp = parse_ts(o.get('expire_at'))
        if exp is None:
            raise ValueError('a resting order needs an expiry')
        body.update(time_in_force='good_till_canceled', post_only=True, expiration_time=int(exp.timestamp()))
    else:
        body['time_in_force'] = 'immediate_or_cancel'
    return body


def all_in(o):
    """The most an order can lose: its count at its limit price, plus the fee on it (the taker fee on a take, the
    maker fee on a resting order). This is what the pilot's walls count, so a night's cap and the wallet bound
    what can be lost, fees included, not only what is posted."""
    n, p = int(float(o.get('count') or 0)), float(o.get('price_c') or 0) / 100
    return round(n * p + engine.order_fee(n, p, 'taker' if o.get('kind') == 'take' else 'maker'), 2)


def fill_cost(o):
    """Dollars a live order has in the game, fee in: what filled at the price it filled at, or the whole order
    when Kalshi never said what became of it."""
    n = fnum(o.get('filled_count'))
    if o.get('status') in ('filled', 'partial') and n is not None:
        p = fnum(o.get('fill_price_c'))
        p = (p if p is not None else float(o.get('price_c') or 0)) / 100
        return round(n * p + engine.order_fee(int(n), p, 'taker' if o.get('kind') == 'take' else 'maker'), 2)
    return all_in(o)


def fee_note(note):
    """The fee Kalshi charged, kept in the row's note as 'fee=0.0131' (the orders table has no fee column), or None."""
    m = re.search(r'fee=([0-9.]+)', note or '')
    return float(m.group(1)) if m else None


class Trader:
    """Plans and records the shadow orders, and plans, walls and sends the pilot's, for one Desk. One per process;
    the worker owns it."""

    def __init__(self, config, bankroll):
        auto = config.get('auto') if isinstance(config, dict) else None
        self.on = isinstance(auto, dict)
        self.cfg = {**DEFAULTS, **(auto or {})}
        self.bank = float(bankroll)
        self.db_ok = True          # set False once the orders table says it is not there yet (one line, then quiet)
        self._kill = (None, 0.0)   # (value, read time)
        self.night = {}            # date_et -> dict(open_cost, orders, pnl) cache, refreshed from the table per plan
        self.sent = []             # (game, side, strike, price, count) this process sent live, for the log line
        pilot = (auto or {}).get('pilot')
        self.pilot = {**PILOT, **pilot, 'leash': {**PILOT['leash'], **(pilot.get('leash') or {})}} if isinstance(pilot, dict) else None
        self.verified = None       # the self-test's result in this process (preflight), None until it has run
        self.posted = {}           # date_et -> dollars this process has posted: the second count behind the table's
        self.outbox = []           # (title, body, priority) for the worker to push to the phone
        self._said = set()         # one push per night per reason
        self._summed = set()       # nights whose summary went out

    OPEN = OPEN   # the statuses of an order that may still be at Kalshi, for the watcher's open list

    def push_line(self, done):
        return pilot_line(done)

    # ---- switches ----
    def mode(self):
        """The label on the planner's rows: shadow. A live order comes from the pilot and is labelled there;
        config auto.mode on its own sends nothing, whatever it says."""
        return 'shadow'

    def kill(self):
        """The control row's kill flag, read at most every 5 seconds; True when it cannot be read (no read, no send)."""
        if time.time() - self._kill[1] < 5:
            return self._kill[0]
        val = True
        if store.enabled():
            rows = store.read(CONTROL, {'select': 'kill', 'id': 'eq.trade'})
            if rows:
                val = bool(rows[0].get('kill'))
        self._kill = (val, time.time())
        return val

    def pilot_sports(self):
        """The sports the pilot may trade: config auto.pilot.sports, and none without a wallet above zero."""
        if not self.on or not self.pilot:
            return []
        try:
            wallet = float(self.pilot.get('wallet') or 0)
        except (TypeError, ValueError):
            wallet = 0.0
        return list(self.pilot.get('sports') or []) if wallet > 0 else []

    def pilot_wants(self, sport):
        return sport in self.pilot_sports()

    def switches(self):
        """The switches outside the self-test and the kill row, as (name, on) pairs, for the boot line."""
        return [('pilot in config', bool(self.pilot_sports())), ('TRADE_ENABLED=1', os.environ.get('TRADE_ENABLED') == '1'),
                ('trade key', key_present()), ('requests', requests is not None)]

    def ready(self):
        """Every switch but the self-test and the kill row: the point at which the self-test is worth running."""
        return all(on for _, on in self.switches())

    def armed(self):
        """Live sending allowed right now: every switch on, the self-test passed, the kill row off. Nothing else counts."""
        return bool(self.ready() and self.verified and self.verified.get('ok') and not self.kill())

    def wants(self, sport):
        return self.on and sport in (self.cfg.get('sports') or [])

    def say(self, title, body, priority='default', once=None):
        """Queue a push for the worker. once: a key that lets it through one time in this process."""
        if once is not None:
            if once in self._said:
                return
            self._said.add(once)
        self.outbox.append((title, body, priority))

    def drain(self):
        out, self.outbox = self.outbox, []
        return out

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
        """What tonight's shadow orders have done so far: open resting cost, orders planned, graded P&L."""
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

    # ---- the pilot's walls ----
    def limits(self):
        """The pilot's numbers in force: the full ones for a walled key, the leash's otherwise, each under its
        ceiling in PILOT_HARD."""
        p = self.pilot or PILOT
        walled = bool(self.verified and self.verified.get('ok') and self.verified.get('walled'))
        src = p if walled else {**p, **(p.get('leash') or {})}
        def num(k):
            try:
                return max(0.0, float(src.get(k) or 0))
            except (TypeError, ValueError):
                return 0.0
        try:
            wallet = max(0.0, float(p.get('wallet') or 0))
        except (TypeError, ValueError):
            wallet = 0.0
        return dict(walled=walled, wallet=min(wallet, PILOT_HARD['wallet']), night_cap=min(num('night_cap'), PILOT_HARD['night_cap']),
                    rest_pairs=int(min(num('rest_pairs'), PILOT_HARD['order_count'])), single_cost=min(num('single_cost'), PILOT_HARD['order_cost']))

    def ledger(self, date_et):
        """What the pilot has done, from the orders table: dollars posted tonight (every live order that reached
        Kalshi or may have, filled or not, each at its limit price with its fee), how many orders that was, and
        its realized P&L for good (graded orders; an order from an earlier night that may have filled and was
        never graded counts as lost). None when the table cannot be read: no read, no send."""
        if not store.enabled() or not self.db_ok:
            return None
        rows = store.fetch_all(ORDERS, {'select': 'client_order_id,date_et,status,kind,cost,pnl,count,filled_count,price_c,fill_price_c', 'mode': 'eq.live'}, 'client_order_id')
        if rows is None:
            return None
        posted, real, n = 0.0, 0.0, 0
        for r in rows:
            tonight = str(r.get('date_et')) == str(date_et)
            if tonight and r.get('status') not in ('skipped', 'rejected'):
                posted += all_in(r)
                n += 1
            if r.get('pnl') is not None:
                real += float(r['pnl'])
            elif not tonight and r.get('status') in ('filled', 'partial') + OPEN:
                real -= fill_cost(r)
        return dict(posted=round(posted, 2), realized=round(real, 2), orders=n)

    def room(self, led, date_et):
        """Dollars the pilot may still post tonight, and what is left of the wallet, from a ledger read."""
        lim = self.limits()
        left = round(lim['wallet'] + min(0.0, led['realized']), 2)
        posted = max(led['posted'], self.posted.get(str(date_et), 0.0))
        return round(max(0.0, min(lim['night_cap'], left) - posted), 2), max(0.0, left), posted

    def wall(self, o, led=None, need=None):
        """Why this order may not be sent, or None. need: the dollars that must fit tonight for it to go (both legs
        of a pair when it is one of two; its own cost otherwise)."""
        if not self.pilot_wants(o.get('sport')):
            return f"{o.get('sport')} is not a pilot sport"
        cost = all_in(o)   # what it can lose: the limit price and the fee
        if int(o['count']) > PILOT_HARD['order_count'] or int(o['count']) * int(o['price_c']) / 100 > PILOT_HARD['order_cost'] + 1e-9:
            return f"an order of {int(o['count'])} at {int(o['price_c'])}c is over the ceiling (${PILOT_HARD['order_cost']:.0f}, {PILOT_HARD['order_count']} contracts)"
        if o['kind'] == 'rest':
            exp, now = parse_ts(o.get('expire_at')), dt.datetime.now(dt.timezone.utc)
            if exp is None or not now < exp <= now + dt.timedelta(minutes=MAX_REST_MIN):
                return f'a resting order must expire inside the next {MAX_REST_MIN} minutes'
        led = led if led is not None else self.ledger(o.get('date_et'))
        if led is None:
            return 'the orders table could not be read (no read, no send)'
        if led['orders'] >= PILOT_HARD['orders_per_night']:
            return f"{led['orders']} orders tonight, the ceiling"
        room, left, posted = self.room(led, o.get('date_et'))
        if left <= 0:
            return f"the wallet is spent (${-led['realized']:.2f} lost of ${self.limits()['wallet']:.0f})"
        if max(cost, need or 0.0) > room + 1e-9:
            return f"night cap: ${posted:.2f} posted, ${room:.2f} of room"
        return None

    # ---- planning ----
    def expiries(self, sport, stage, start_iso):
        start = parse_ts(start_iso) or dt.datetime.now(dt.timezone.utc)
        brk = start + dt.timedelta(minutes=BREAK_MIN.get(stage, {}).get(sport, 16))
        q4 = start + dt.timedelta(minutes=Q4_MIN.get(stage, {}).get(sport, 50))
        return brk, q4

    def plan(self, g, rec, stage, m, rows, sug, quotes, ev, sizing, ts, held_legs=None):
        """The shadow orders for this break, sized under the caps. Returns the list (possibly empty) and a note."""
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
        # The shadow orders rest to the 4th so the readout keeps splitting break fills from in-play fills. A live
        # order (plan_pilot) never outlives the break: the in-play fills are the ones that lost (605 touched legs,
        # minus 10% after fees, Oct 23 to Nov 11; engine.cancel_by), and the push tells the phone the same thing.
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
        # the cap counts every leg at once: if all fill, the worst final may not lose more than cap (the maker fee in)
        legs = self.fit_cap(list(legs.values()), held_legs, cap)
        # takes: what the push led with, at the asks it named (the middle in a middle-focus sport when one cleared,
        # else the first single; the backups are not a stack), recorded so the readout says how often the ask held.
        takes = []
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
            tbl += [dict(side=l['side'], strike=l['strike'], shares=max(0, int(l['count'] * scale)), paid_c=l['price_c'],
                         fee=engine.order_fee(max(0, int(l['count'] * scale)), l['price_c'] / 100, 'maker')) for l in legs]
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

    def plan_pilot(self, g, stage, m, rows, sug, quotes, ev, sizing, ts, held_legs=None, plays_live=True):
        """The pilot's orders for this break, at pilot size: what the push itself says to do. On a PLAY the push leads
        with a single, and the pilot takes it; on a read (an UPDATE) the push carries the REST A MIDDLE block, and
        the pilot posts those two legs. Never both on one game: a PLAY push names no resting middle, so none is
        posted. Returns (orders, note). An unarmed pilot plans nothing and writes nothing. plays_live: the sport's
        PLAYs are live on the phone (not in a shadow week), so its single may be taken."""
        sport = g['sport']
        if stage != 'half' or not self.pilot_wants(sport) or not self.armed():
            return [], None
        if held_legs:
            return [], 'you already hold this total, so the pilot stays out'
        lim = self.limits()
        kinds = self.pilot.get('kinds') or []
        brk, _ = self.expiries(sport, stage, ts)
        most = lambda price_c: min(PILOT_HARD['order_count'], int(PILOT_HARD['order_cost'] * 100 / int(price_c) + 1e-9))   # contracts one order may hold
        out = []
        def add(side, strike, price_c, n, kind, reason, pair):
            tk = (quotes.get(float(strike)) or {}).get('ticker')
            out.append(dict(client_order_id=order_id(g['id'], stage, side, strike, price_c, kind, f'live {reason}'), created_at=ts,
                            game_id=g['id'], sport=sport, game=g['short'], date_et=g['date_et'], event_ticker=ev.get('event_ticker'), market_ticker=tk,
                            strike=float(strike), side=side, action='buy', kind=kind, stage=stage, price_c=int(price_c), count=int(n), cost=round(int(n) * int(price_c) / 100, 2),
                            expire_at=brk.isoformat(), reason=reason, pair=pair, mode='live', status='planned',
                            kalshi_order_id=None, sent_at=None, filled_count=None, fill_price_c=None, filled_at=None, touched_at=None, touch_phase=None,
                            touch_s=None, pnl=None, graded_at=None, final_total=None, note=None))
        has = lambda strike, price_c: bool((quotes.get(float(strike)) or {}).get('ticker')) and price_c is not None and 1 <= int(price_c) <= 99
        singles, mid = engine.chosen(sug, 1)
        is_play = bool(singles or mid or engine.chosen_rev(sug))   # engine.order_sheet: anything that clears makes the push a PLAY
        if 'take' in kinds and plays_live and lim['single_cost'] > 0:
            if singles and has(singles[0]['line'], singles[0]['price_c']):
                s = singles[0]
                n = min(int(s['contracts']), int(lim['single_cost'] * 100 / int(s['price_c']) + 1e-9), most(s['price_c']))
                if n >= 1:
                    add('yes' if s['kind'] == 'over' else 'no', s['line'], s['price_c'], n, 'take', 'single', None)
        if 'rest' in kinds and lim['rest_pairs'] >= 1 and not is_play:
            # the resting middle the read names: engine.rest_block makes this call with these numbers
            rp = engine.rest_plan(m, rows, 'fg', sizing.get('margin', 0.03), sizing.get('bankroll', self.bank), sizing.get('max_risk', 75.0), sizing.get('max_cost', 225.0),
                                  mid_loss=sizing.get('mid_loss'), near_pts=sizing.get('near_pts', 3.5))
            md = rp.get('middle')
            # both legs or neither: a pair one of whose strikes has no market is never posted as a lone leg
            if md and has(md['a']['line'], md['a']['over_rest']) and has(md['b']['line'], md['b']['under_rest']):
                a, b = md['a'], md['b']
                n = min(int(md['pairs']), lim['rest_pairs'], most(a['over_rest']), most(b['under_rest']))
                if n >= 1:
                    pair = f"{a['line']:g}/{b['line']:g}"
                    add('yes', a['line'], a['over_rest'], n, 'rest', 'rest_mid', pair)
                    add('no', b['line'], b['under_rest'], n, 'rest', 'rest_mid', pair)
        return out, None

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
        """The shadow planner's orders: recorded, never sent. Returns the rows."""
        if not orders:
            return []
        for o in orders:
            o['mode'] = 'shadow'
        self.record(orders)
        return orders

    def act_live(self, orders):
        """Send one game's pilot orders. Each is checked against the walls, written to the table, sent, and written
        again with Kalshi's answer. A pair goes as a pair or not at all when tonight's room cannot hold both legs.
        Returns (the rows sent or tried, a note when something was held back)."""
        if not orders:
            return [], None
        date_et = str(orders[0]['date_et'])
        led = self.ledger(date_et)
        if led is None:
            return [], 'the orders table could not be read (no read, no send)'
        groups = {}
        for o in orders:
            groups.setdefault(o.get('pair') or o['client_order_id'], []).append(o)
        done, note = [], None
        for grp in groups.values():
            need = sum(all_in(o) for o in grp)
            why = next((w for w in (self.wall(o, led, need) for o in grp) if w), None)
            if why:
                note = why
                if why.startswith('night cap') or why.startswith('the wallet'):
                    lim = self.limits()
                    self.say('AUTO: done for the night' if why.startswith('night cap') else 'AUTO: the wallet is spent',
                             f"The pilot stopped posting: {why}. Tonight's cap is ${lim['night_cap']:.0f} of orders, filled or not"
                             + ('' if lim['walled'] else ' (the short leash: the trade key is not walled)') + '. Nothing for you to do.',
                             'default', once=f'{date_et}|{why.split(":")[0]}')
                continue
            for o in grp:
                if not store.claim(ORDERS, o, 'client_order_id', strict=True):
                    note = 'an order was already in the table, or the table refused it (no record, no send)'
                    continue
                self.send(o, led)
                if o['status'] not in ('skipped', 'rejected'):
                    self.posted[date_et] = round(self.posted.get(date_et, 0.0) + all_in(o), 2)
                    led['posted'] = round(led['posted'] + all_in(o), 2)
                    led['orders'] += 1
                store.write(ORDERS, [o], on_conflict='client_order_id')
                done.append(o)
                if o['status'] in ('rejected', 'unconfirmed'):
                    self.say('AUTO: Kalshi refused an order' if o['status'] == 'rejected' else 'AUTO: an order got no answer',
                             f"{o['game']}: {'Over' if o['side'] == 'yes' else 'Under'} {o['strike']:g} at {o['price_c']}c x{o['count']}. {(o.get('note') or '')[:160]}"
                             + ('' if o['status'] == 'rejected' else ' It may be resting at Kalshi; it expires with the break either way. Check your Kalshi orders.'),
                             'high' if o['status'] == 'unconfirmed' else 'default', once=f"{date_et}|{o['status']}|{(o.get('note') or '')[:40]}")
        return done, note

    def send(self, o, led=None):
        """One live order. Every check here is a hard wall, whatever the planner did."""
        assert o['kind'] in ('rest', 'take') and o['side'] in ('yes', 'no') and o['action'] == 'buy'
        assert 1 <= int(o['price_c']) <= 99 and int(o['count']) >= 1
        if not self.armed():
            o.update(status='skipped', note='not armed at send time')
            return o
        why = self.wall(o, led)
        if why:
            o.update(status='skipped', note=why[:240])
            return o
        try:
            res = api('POST', ORDER_PATH, order_body(o), tries=1, timeout=6)
        except ApiError as e:
            if e.status is not None and 400 <= e.status < 500 and e.status != 409:
                o.update(status='rejected', note=str(e)[:240])       # Kalshi said no: nothing is resting
                print(f"order rejected {o['game']} {o['side']} {o['strike']:g}: {e}")
            else:   # no clean answer (a timeout, a 5xx, or a 409 on an id it already holds): it may be live
                o.update(status='unconfirmed', sent_at=now_iso(), note=str(e)[:240])
                print(f"order unconfirmed {o['game']} {o['side']} {o['strike']:g}: {e}")
            return o
        if not res.get('order_id'):   # an answer with no order in it: treated like no answer
            o.update(status='unconfirmed', sent_at=now_iso(), note=f'no order id in the answer: {str(res)[:160]}')
            return o
        fc = fnum(res.get('fill_count'))
        if fc is None:
            fc = fnum(res.get('fill_count_fp')) or 0.0
        o.update(kalshi_order_id=res.get('order_id'), sent_at=now_iso(), filled_count=fc)
        if fc >= int(o['count']) - 1e-9:
            o['status'] = 'filled'
        elif o['kind'] == 'take':
            o['status'] = 'partial' if fc > 0 else 'cancelled'
        else:
            o['status'] = 'resting'
        if fc > 0:
            o['filled_at'] = now_iso()
            px, fee = fnum(res.get('average_fill_price')), fnum(res.get('average_fee_paid'))
            if px is not None:
                o['fill_price_c'] = own_price(o, 100 * px)
            if fee is not None:
                o['note'] = with_fee(o.get('note'), fee * fc)
        if o['kind'] == 'take' or fc > 0:
            # a take is over the moment it is sent, so its row is settled from Kalshi's own record of the order
            # (what filled, what it cost, the fee), not from the create call's summary
            try:
                self.read_back(o)
            except ApiError as e:
                o['note'] = add_note(o.get('note'), f'not read back: {e}')
        if o['status'] == 'cancelled' and o['kind'] == 'take':
            o['note'] = add_note(o.get('note'), 'the ask was gone')
        self.sent.append((o['game'], o['side'], o['strike'], o['price_c'], o['count']))
        print(f"sent {o['game']} {o['side'].upper()} {o['strike']:g} at {o['price_c']}c x{o['count']} ({o['reason']}): {o['status']}")
        return o

    def read_back(self, o):
        """Set a live order's row to what Kalshi says became of it. Raises ApiError when Kalshi cannot be asked."""
        res = api('GET', f"{ORDER_READ_PATH}/{o['kalshi_order_id']}", tries=1, timeout=6)
        order = res.get('order') or res
        fc = fnum(order.get('fill_count_fp'))
        if fc is None:
            fc = fnum(order.get('fill_count'))
        if fc is None or order.get('status') not in ('resting', 'canceled', 'executed'):
            # an answer this code cannot read is not an answer: the row stays as it was and the caller hears about it
            raise ApiError(f"order read back without a fill count or a known status: {str(order)[:160]}")
        o['filled_count'] = fc
        if fc > 0:
            cost = (fnum(order.get('maker_fill_cost_dollars')) or 0.0) + (fnum(order.get('taker_fill_cost_dollars')) or 0.0)
            fee = (fnum(order.get('maker_fees_dollars')) or 0.0) + (fnum(order.get('taker_fees_dollars')) or 0.0)
            if cost > 0:
                o['fill_price_c'] = own_price(o, 100 * cost / fc)
            o['note'] = with_fee(o.get('note'), fee)
            o['filled_at'] = o.get('filled_at') or now_iso()
        st = order.get('status')
        if st == 'executed' or (st == 'canceled' and fc > 0):
            o['status'] = 'filled' if fc >= int(o['count']) - 1e-9 else 'partial'
        elif st == 'canceled':
            o['status'] = 'expired' if (o['kind'] == 'rest' and (o.get('expire_at') or '') <= now_iso()) else 'cancelled'
        elif st == 'resting':
            o['status'] = 'resting'
        return o

    def cancel(self, o, why):
        """Pull one resting live order, then read back what filled before it went."""
        if not o.get('kalshi_order_id') or o.get('status') not in ('sent', 'resting'):
            return
        gone = False
        try:
            api('DELETE', f"{ORDER_PATH}/{o['kalshi_order_id']}", params={'market_ticker': o.get('market_ticker')}, timeout=6)
            gone = True
        except ApiError as e:
            if e.status != 404:   # 404: nothing resting under that id any more (it filled or expired); the read says which
                o['note'] = add_note(o.get('note'), f'cancel failed: {e}')
        try:
            self.read_back(o)
        except ApiError as e:
            if gone:
                o['status'] = 'cancelled'
            o['note'] = add_note(o.get('note'), f'read after cancel failed: {e}')
        if o.get('status') in ('cancelled', 'expired'):
            o['note'] = add_note(o.get('note'), why)

    def cancel_game(self, rec, why):
        """Pull every resting live order on a game (the second half started, the score was wrong, or a kill)."""
        rows = []
        for st in (rec.get('auto') or {}).values():
            for o in st.get('open') or []:
                if o.get('mode') == 'live' and o.get('kalshi_order_id') and o.get('status') in ('sent', 'resting'):
                    self.cancel(o, why)
                    rows.append(o)
            st['open'] = [o for o in st.get('open') or [] if o.get('mode') != 'live' or o.get('status') in OPEN]
        if rows:
            store.write(ORDERS, rows, on_conflict='client_order_id')
        return rows

    def has_live_open(self, rec):
        return any(o.get('mode') == 'live' and o.get('status') in OPEN for st in (rec.get('auto') or {}).values() for o in st.get('open') or [])

    # ---- the shadow fill model, and status refresh for live orders ----
    def touch(self, g, rec, quotes, phase, at=None):
        """Mark open shadow orders whose price the ladder has reached. A live order is Kalshi's to settle: refresh()
        asks, this leaves it alone. Returns the rows that changed."""
        at = at or now_iso()
        changed = []
        for stage, st in (rec.get('auto') or {}).items():
            start = parse_ts(st.get('at'))
            keep = []
            for o in st.get('open') or []:
                if o.get('mode') == 'live':
                    if o.get('status') in OPEN:
                        keep.append(o)
                    continue
                if o.get('status') not in ('planned', 'sent', 'resting'):
                    continue
                if (o.get('created_at') or '') >= at:
                    keep.append(o)   # the pass that planned it: a take at the ask it was priced at is trivially there
                    continue
                if (o.get('expire_at') or '') <= at:
                    o['status'] = 'expired'
                    changed.append(o)
                    continue
                q = quotes.get(float(o['strike'])) or {}
                ask = q.get('y') if o['side'] == 'yes' else q.get('n')
                if ask is not None and ask <= o['price_c']:
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
        """Live orders: ask Kalshi what became of each open one, and cancel one that is past its window and still
        resting. An order that never got an answer from Kalshi has no id to ask about: it stays unconfirmed, leaves
        the open list once its window is past, and counts against the walls until someone settles it."""
        if not self.pilot_sports() or not key_present():
            return []
        changed, now = [], now_iso()
        for st in (rec.get('auto') or {}).values():
            keep = []
            for o in st.get('open') or []:
                if o.get('mode') != 'live':
                    keep.append(o)
                    continue
                if o.get('status') not in OPEN:
                    continue
                past = (o.get('expire_at') or '') <= now
                if not o.get('kalshi_order_id'):
                    if not past:
                        keep.append(o)
                    continue
                before = (o.get('status'), o.get('filled_count'))
                try:
                    self.read_back(o)
                    if o['status'] == 'resting' and past:
                        self.cancel(o, 'past its window')
                except ApiError as e:
                    print(f"order refresh {o.get('game')}: {e}")
                if (o.get('status'), o.get('filled_count')) != before:
                    changed.append(o)
                if o.get('status') in OPEN:
                    keep.append(o)
            st['open'] = keep
        if changed:
            store.write(ORDERS, changed, on_conflict='client_order_id')
        return changed

    # ---- grading ----
    @staticmethod
    def pnl_of(o, T):
        """Dollars a filled order made on final total T, the fee in: a take pays the taker fee, a resting fill the
        maker fee. A live order is graded on what filled, at the price it filled at and the fee Kalshi charged when
        both are on the row. Rows graded before Nov 12, 2026 hold a resting fill at no fee in their pnl column; the
        readers (net_pnl below, scripts/readout.py) recompute from the order and its final, so every row reads the
        same way."""
        live = o.get('mode') == 'live'
        n = float(o.get('filled_count') if live and o.get('filled_count') is not None else o['count'])
        price = float(o['price_c'])
        if live:
            px, fee = fnum(o.get('fill_price_c')), fee_note(o.get('note'))
            if px is not None:
                price = px
            if fee is not None:
                win = float(T) > float(o['strike']) if o['side'] == 'yes' else float(T) < float(o['strike'])
                return round((n * (1 - price / 100) - fee) if win else (-n * price / 100 - fee), 2)
        return engine.fill_pnl(o['side'], float(o['strike']), price, n, o.get('kind'), float(T))

    def grade(self, g, rec, T):
        """Grade this game's auto orders at the final: every touched (shadow) or filled (live) order gets a pnl. A
        live order still open is read back from Kalshi first: the last word on a fill is Kalshi's."""
        if not self.on or not store.enabled() or not self.db_ok:
            return None
        rows = store.read(ORDERS, {'select': '*', 'game_id': f"eq.{g['id']}", 'limit': 500})
        if not rows:
            return None
        out, pnl, n, live_n = [], 0.0, 0, 0
        for o in rows:
            if o.get('mode') == 'live':
                live_n += 1
                if o.get('status') in ('sent', 'resting'):
                    try:
                        if not key_present():
                            raise ApiError('no trade key')
                        self.read_back(o)
                        if o['status'] == 'resting':
                            o['status'] = 'expired'   # the game is over and nothing was reported filled
                    except ApiError as e:
                        o.update(status='unconfirmed', note=add_note(o.get('note'), f'not read at the final: {e}'))
                elif o.get('status') == 'planned':
                    o.update(status='unconfirmed', note=add_note(o.get('note'), 'written and never answered'))
            elif o.get('status') in ('planned', 'sent', 'resting'):
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
        for st in (rec.get('auto') or {}).values():
            st['open'] = []
        if live_n:
            try:
                self.night_summary(g['date_et'])
            except Exception as e:   # a summary never blocks a grade
                print(f'pilot summary failed: {e}')
        return dict(fills=n, pnl=round(pnl, 2), orders=len(out))

    def night_summary(self, date_et):
        """One push when the last of a night's live orders is graded: what the pilot posted, what filled, what it
        made, and what is left of the wallet, with the shadow model's fill rate at the break beside its own."""
        date_et = str(date_et)
        if date_et in self._summed:
            return None
        rows = store.fetch_all(ORDERS, {'select': 'client_order_id,mode,sport,kind,status,cost,pnl,graded_at,filled_count,price_c,fill_price_c,count,touch_phase,stage',
                                        'date_et': f'eq.{date_et}'}, 'client_order_id')
        if not rows:
            return None
        live = [r for r in rows if r.get('mode') == 'live' and r.get('status') not in ('skipped', 'rejected')]
        if not live or any(r.get('graded_at') is None for r in live):
            return None
        led = self.ledger(date_et)
        if led is None:
            return None
        self._summed.add(date_et)
        fills = [r for r in live if r.get('status') in ('filled', 'partial')]
        pnl = sum(float(r['pnl']) for r in fills if r.get('pnl') is not None)
        rests = [r for r in live if r.get('kind') == 'rest']
        rest_f = [r for r in rests if r.get('status') in ('filled', 'partial')]
        lost = [r for r in live if r.get('status') == 'unconfirmed']
        sports = sorted({r.get('sport') for r in live})
        sh = [r for r in rows if r.get('mode') == 'shadow' and r.get('kind') == 'rest' and r.get('sport') in sports]
        sh_f = [r for r in sh if r.get('status') == 'touched' and (r.get('touch_phase') or '') in ('half', 'early3', '')]
        lim = self.limits()
        _, left, _ = self.room(led, date_et)
        pct = lambda a, b: f'{100 * a / b:.0f}%' if b else 'n/a'
        body = [f"{', '.join(SPORT_NAME.get(s, s) for s in sports).capitalize()}: {len(live)} orders posted (${sum(float(r.get('cost') or 0) for r in live):.2f}), "
                f"{len(fills)} filled (${sum(fill_cost(r) for r in fills):.2f} in), {usd(pnl)} after fees.",
                f"Resting legs filled: {len(rest_f)} of {len(rests)} ({pct(len(rest_f), len(rests))}). The shadow model had {len(sh_f)} of {len(sh)} at the break ({pct(len(sh_f), len(sh))}).",
                f"Pilot to date: {usd(led['realized'])}. Wallet left: ${left:.2f} of ${lim['wallet']:.0f}."]
        if lost:
            body.append(f"{len(lost)} order{'s' if len(lost) != 1 else ''} never got an answer from Kalshi and count as lost until checked. Look at your Kalshi orders for that night.")
        title = f"AUTO {date_et[5:]}: {usd(pnl)} on {len(fills)} fill{'s' if len(fills) != 1 else ''}"
        self.say(title, '\n'.join(body), 'default')
        return title

    # ---- the self-test ----
    def preflight(self, events):
        """The pilot's self-test, run by the worker once the switches are on. The trade key reads its balance; a
        one-contract YES bid at 1c and a one-contract NO bid at 1c are posted on a market whose asks are nowhere
        near, read back, checked for side and price, and cancelled. Passing sets self.verified['ok'], which
        armed() needs; anything else leaves the pilot unarmed with the step and Kalshi's words. events: Kalshi
        total events for the pilot's sports."""
        res = dict(ok=False, at=now_iso(), walled=False, step='switches', error=None, status=None, wait=False, balance=None, subaccount=None)
        self.verified = res
        if not self.ready():
            res['error'] = 'off: ' + ', '.join(name for name, on in self.switches() if not on)
            return res
        if self.kill():   # the kill switch stops every send, a 1c test order included
            res.update(step='the kill switch', wait=True, error='the kill switch is on (or the control row could not be read)')
            return res
        try:
            res['step'] = 'the balance read'
            b = api('GET', BALANCE_PATH)
            bal = fnum(b.get('balance_dollars'))
            if bal is None and isinstance(b.get('balance'), (int, float)):
                bal = b['balance'] / 100
            res['balance'] = bal
            res['step'] = 'finding a market'
            tk = test_market(events)
            if not tk:
                res.update(wait=True, error='no open two-sided total market to test on yet')
                return res
            for side in ('yes', 'no'):
                res['step'] = f"the {'YES' if side == 'yes' else 'NO'} test order"
                exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=120)
                o = dict(market_ticker=tk, side=side, price_c=1, count=1, kind='rest', client_order_id=str(uuid.uuid4()), expire_at=exp.isoformat())
                made = api('POST', ORDER_PATH, order_body(o), tries=1)
                oid = made.get('order_id')
                if not oid:
                    raise ApiError(f'no order id in the answer: {str(made)[:160]}')
                err = None
                try:
                    order = api('GET', f'{ORDER_READ_PATH}/{oid}')
                    order = order.get('order') or order
                    check_test(order, side)
                    if order.get('subaccount_number') is not None:
                        res['subaccount'] = order.get('subaccount_number')
                except ApiError as e:
                    err = e
                try:   # the test order comes down whatever the read said; it would expire in two minutes anyway
                    api('DELETE', f'{ORDER_PATH}/{oid}', params={'market_ticker': tk})
                except ApiError as e:
                    if e.status != 404 and err is None:
                        err = ApiError(f'the test order could not be cancelled ({e}); it expires on its own in two minutes', e.status)
                if err is not None:
                    raise err
        except ApiError as e:
            res.update(error=str(e)[:300], status=e.status)
            return res
        except Exception as e:
            res['error'] = f'{type(e).__name__}: {e}'[:300]
            return res
        wallet = self.limits()['wallet']
        sub = res.get('subaccount')
        res.update(ok=True, step='done',
                   walled=bool(isinstance(sub, int) and sub >= 1 and res['balance'] is not None and res['balance'] <= wallet * WALL_SLACK + 1e-9))
        return res

    def preflight_push(self, res=None):
        """(title, body, priority, signature) for the self-test's result. The signature changes when the answer
        does, so the worker pushes a result once, not at every restart."""
        res = res or self.verified or {}
        names = ', '.join(SPORT_NAME.get(s, s) for s in self.pilot_sports()) or 'no sport'
        if res.get('ok'):
            lim = self.limits()
            if lim['walled']:
                wall = f"Wall: Kalshi's. The key is locked to subaccount {res.get('subaccount')}, which holds ${res.get('balance'):.2f}."
            else:
                wall = ("Wall: the desk's own. " + ('This key is not locked to a subaccount' if not (isinstance(res.get('subaccount'), int) and res.get('subaccount') >= 1)
                                                    else 'Its subaccount holds more than the wallet') + ', so the short leash applies.')
            body = [f"Kalshi took the test orders and gave them back: a YES bid and a NO bid at 1c, posted, read back, cancelled. Cost $0.", wall,
                    f"In force: up to ${lim['night_cap']:.0f} of orders a night, {lim['rest_pairs']} pairs a resting middle, ${lim['single_cost']:.0f} a play. It stops for good at ${lim['wallet']:.0f} lost.",
                    'Kill switch: the Record tab.']
            return f'AUTO: armed for {names}', '\n'.join(body), 'high', f"ok|{lim['walled']}|{lim['night_cap']:g}|{lim['wallet']:g}"
        err = res.get('error') or 'unknown'
        hint = {401: 'Kalshi did not accept the key or its signature. Check KALSHI_TRADE_KEY_ID and KALSHI_TRADE_PRIVATE_KEY in Railway.',
                403: 'The key is missing a permission. It needs read and trade.',
                429: 'Kalshi rate-limited the test. It runs again in ten minutes.'}.get(res.get('status'), '')
        body = f"The self-test stopped at {res.get('step')}: {err}. Nothing will be sent." + (f' {hint}' if hint else '') + ' It runs again in ten minutes and after any restart.'
        return 'AUTO: NOT armed', body, 'high', f"fail|{res.get('step')}|{res.get('status')}|{err[:60]}"

    def status_line(self):
        """One line for the worker's boot log."""
        if not self.on:
            return 'auto off'
        base = f"auto shadow for {', '.join(self.cfg.get('sports') or [])}"
        if not self.pilot:
            return base + '; no pilot'
        if not self.pilot_sports():
            return base + '; pilot off (no sport or no wallet in config)'
        off = [name for name, on in self.switches() if not on]
        lim = self.limits()
        return (base + f"; pilot for {', '.join(self.pilot_sports())}, wallet ${lim['wallet']:.0f}: "
                + (f"switches off ({', '.join(off)})" if off else ('ARMED' if self.armed() else 'switches on, self-test pending')))


def own_price(o, cents):
    """A fill price in the order's own terms. Kalshi's book is the YES book, so a NO order's fill can come back as
    the YES price; of a number and its complement, the one at or under the order's limit and nearest to it is the
    price that was paid. None when neither fits."""
    limit = float(o['price_c'])
    fits = [c for c in (float(cents), 100 - float(cents)) if c <= limit + 0.5]
    return round(min(fits, key=lambda c: limit - c), 2) if fits else None


def usd(x):
    """Signed dollars to the cent: the pilot's numbers are small."""
    return f"{'+' if x >= 0 else '-'}${abs(x):.2f}"


def add_note(note, more):
    return (f'{note}; {more}' if note else str(more))[:240]


def with_fee(note, fee):
    """The row's note with the fee Kalshi charged written (or rewritten) into it as 'fee=0.0131'."""
    rest = re.sub(r'(; )?fee=[0-9.]+', '', note or '').strip('; ')
    return add_note(rest or None, f'fee={float(fee):.4f}')


def test_market(events):
    """A market to run the self-test on: both asks well inside the book, so a 1c bid on either side cannot cross."""
    for ev in events or []:
        for _, q in sorted(feeds.total_quotes(ev).items()):
            if q.get('ticker') and q.get('y') is not None and q.get('n') is not None and 10 <= q['y'] <= 90 and 10 <= q['n'] <= 90:
                return q['ticker']
    return None


def check_test(order, side):
    """The self-test's read: the order Kalshi holds is on the side and at the price it was meant to be. Raises
    ApiError with what it read otherwise. A NO bid at 1c reads back as outcome no, book side ask, NO price 0.01."""
    out, book = order.get('outcome_side'), order.get('book_side')
    if out is None and book is None:
        raise ApiError(f'the order read back without a direction: {str(order)[:160]}')
    if (out is not None and out != side) or (book is not None and book != ('bid' if side == 'yes' else 'ask')):
        raise ApiError(f'meant {side}, Kalshi holds outcome {out}, book side {book}')
    px = fnum(order.get('yes_price_dollars' if side == 'yes' else 'no_price_dollars'))
    if px is None or abs(px - 0.01) > 1e-6:
        raise ApiError(f"meant 1c on the {side} side, Kalshi holds {order.get('yes_price_dollars')} yes, {order.get('no_price_dollars')} no")
    n = fnum(order.get('initial_count_fp'))
    if n is not None and abs(n - 1) > 1e-6:
        raise ApiError(f'meant 1 contract, Kalshi holds {n}')
    if order.get('status') not in ('resting', 'executed', 'canceled'):
        raise ApiError(f"unknown order status {order.get('status')}")
    # the fields a real fill is read from: if Kalshi's order record does not carry them, fills could go unseen
    if fnum(order.get('fill_count_fp')) is None and fnum(order.get('fill_count')) is None:
        raise ApiError(f'the order read back without a fill count: {str(order)[:160]}')
    missing = [k for k in ('maker_fill_cost_dollars', 'taker_fill_cost_dollars', 'maker_fees_dollars', 'taker_fees_dollars') if k not in order]
    if missing:
        raise ApiError(f"the order read back without {', '.join(missing)}")


def pilot_line(done):
    """One line for the push when the pilot acted on the game, so nobody places the same orders by hand."""
    live = [o for o in done or [] if o.get('status') not in ('skipped', 'rejected')]
    if not live:
        return None
    rests = [o for o in live if o['kind'] == 'rest']
    takes = [o for o in live if o['kind'] == 'take']
    side = lambda o: 'Over' if o['side'] == 'yes' else 'Under'
    parts = []
    if rests:
        parts.append('resting ' + ' and '.join(f"{side(o)} {o['strike']:g} at {o['price_c']}c x{o['count']}" for o in rests))
    for o in takes:
        n = o.get('filled_count') or 0
        parts.append(f"took {side(o)} {o['strike']:g} at {o['price_c']}c, {int(n)} of {o['count']} filled" if n else f"{side(o)} {o['strike']:g} at {o['price_c']}c was gone")
    return 'AUTO did this one: ' + '; '.join(parts) + '. Do not place these again.'


def net_pnl(o):
    """A graded order's P&L with the fee it pays, whenever it was graded: recomputed from the order and the final it
    was graded on. None when the order was never graded."""
    if o.get('pnl') is None:
        return None
    if o.get('mode') == 'live' or o.get('final_total') is None or o.get('strike') is None or o.get('price_c') is None:
        return float(o['pnl'])   # a live order was graded on the fill and the fee Kalshi reported: the column stands
    return Trader.pnl_of(o, float(o['final_total']))


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
                pnl = sum(net_pnl(r) for r in graded)
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
