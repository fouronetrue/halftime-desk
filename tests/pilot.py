"""The pilot: the only way an order leaves trade.py. A fake Kalshi (the V2 order calls as docs.kalshi.com gives them)
and a fake orders table stand in for the real ones; any real network call fails the test.
1. The order body: a bid on the YES book for the over, an ask at 100 minus the price for the under; a resting order
   post-only with an expiration, a take immediate-or-cancel; fixed-point strings; none of the retired fields.
2. The switches: nothing is armed without the pilot block, a wallet, TRADE_ENABLED=1, the trade key, the kill row
   off, and a passed self-test. config auto.mode 'live' on its own does nothing.
3. The self-test: two 1c bids posted, read back and cancelled; a key Kalshi refuses, an order that reads back on
   the wrong side, and no market to test on each leave the pilot unarmed. A key locked to a funded subaccount is
   walled; anything else is on the leash.
4. The numbers: the leash until walled, the full ones after, each under its ceiling in code.
5. The college basketball fixtures, armed: the push's resting middle and lead single go to Kalshi at pilot size,
   written to the table first; the shadow rows are still planned; the push says what the pilot did. A fill is read
   back with its price and fee, the unfilled leg comes down when the second half starts, the final grades what
   filled, and one push sums the night.
6. The walls: the night cap holds a pair back as a pair, the wallet stops it for good, an unreadable table stops it,
   a row already in the table is not sent twice, an order over the ceiling or without an expiry is refused, the
   kill switch disarms, an order with no clean answer counts as posted and a refused one does not."""
import sys, os, re, json, copy, tempfile, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine, feeds, watch, notify, store, trade

import requests
def boom(*a, **k):
    raise AssertionError('network call attempted')
requests.get = requests.post = requests.request = requests.delete = requests.put = requests.patch = boom


class FakeStore:
    """Tables in memory with PostgREST's filters, as far as this repo uses them."""
    def __init__(self):
        self.t, self.down = {}, set()    # down: the tables that cannot be reached right now
    def enabled(self):
        return True
    def _match(self, row, params):
        for k, v in params.items():
            if k in ('select', 'limit', 'order', 'or'):
                continue
            x = row.get(k)
            op, _, arg = str(v).partition('.')
            if op == 'eq' and str(x) != arg: return False
            if op == 'neq' and str(x) == arg: return False
            if op == 'in' and str(x) not in arg.strip('()').split(','): return False
            if op == 'gt' and not (x is not None and str(x) > arg): return False
            if op == 'gte' and not (x is not None and str(x) >= arg): return False
        return True
    def read(self, table, params):
        return [] if table in self.down else [copy.deepcopy(r) for r in self.t.get(table, []) if self._match(r, params)]
    def fetch_all(self, table, params, key, page=1000):
        return None if table in self.down else sorted(self.read(table, params), key=lambda r: str(r.get(key)))
    def write(self, table, rows, on_conflict=None, ignore_duplicates=False):
        if table in self.down:
            return False
        tbl = self.t.setdefault(table, [])
        for r in rows:
            old = next((x for x in tbl if on_conflict and all(x.get(c) == r.get(c) for c in on_conflict.split(','))), None)
            if old is None:
                tbl.append(copy.deepcopy(r))
            elif not ignore_duplicates:
                old.update(copy.deepcopy(r))
        return True
    def claim(self, table, row, on_conflict, strict=False):
        if table in self.down:
            return not strict
        tbl = self.t.setdefault(table, [])
        if any(all(x.get(c) == row.get(c) for c in on_conflict.split(',')) for x in tbl):
            return False
        tbl.append(copy.deepcopy(row))
        return True


class FakeKalshi:
    """Kalshi's order calls as the docs give them (create and cancel on the V2 event-order path, read on the old
    one), with a book per ticker: ya the YES ask, yb the YES bid, in cents."""
    def __init__(self, balance=500.0, sub=1, book=None):
        self.balance, self.sub, self.book = balance, sub, book or {}
        self.orders, self.calls, self.n = {}, [], 0
        self.fail = None        # f(method, path, body) -> an ApiError to raise, or None
        self.flip = False       # read every order back on the other side (the mistake the self-test exists to catch)
    def api(self, method, path, body=None, params=None, key=None, tries=2, timeout=8):
        self.calls.append((method, path, copy.deepcopy(body), params))
        err = self.fail(method, path, body) if self.fail else None
        if err:
            raise err
        if method == 'GET' and path == trade.BALANCE_PATH:
            return {'balance': int(round(self.balance * 100)), 'balance_dollars': f'{self.balance:.4f}'}
        if method == 'POST' and path == trade.ORDER_PATH:
            assert {'ticker', 'side', 'count', 'price', 'time_in_force', 'self_trade_prevention_type', 'client_order_id'} <= set(body), body
            assert not {'action', 'type', 'yes_price', 'no_price', 'expiration_ts', 'buy_max_cost'} & set(body), f'a retired field: {body}'
            assert body['side'] in ('bid', 'ask') and re.fullmatch(r'\d+\.00', body['count']) and re.fullmatch(r'0\.\d{4}', body['price']), body
            assert body['self_trade_prevention_type'] == 'taker_at_cross' and body.get('cancel_order_on_pause') is True
            gtc = body['time_in_force'] == 'good_till_canceled'
            if gtc:
                assert body.get('post_only') is True and isinstance(body.get('expiration_time'), int), body
                left = body['expiration_time'] - dt.datetime.now(dt.timezone.utc).timestamp()
                assert 0 < left <= 30 * 60 + 5, f'a resting order must expire inside half an hour, not in {left:.0f}s'
            else:
                assert body['time_in_force'] == 'immediate_or_cancel' and 'expiration_time' not in body and not body.get('post_only'), body
            if any(o['client_order_id'] == body['client_order_id'] for o in self.orders.values()):
                raise trade.ApiError('POST failed: HTTP 409 order with this client_order_id exists', 409)
            if self.balance <= 0:
                raise trade.ApiError('POST failed: HTTP 400 insufficient balance', 400)
            yes_c, n = round(float(body['price']) * 100), float(body['count'])
            q = self.book.get(body['ticker']) or {}
            bid = body['side'] == 'bid'
            cross = (bid and q.get('ya') is not None and q['ya'] <= yes_c) or (not bid and q.get('yb') is not None and q['yb'] >= yes_c)
            if gtc and cross:
                raise trade.ApiError('POST failed: HTTP 400 post only order would cross', 400)
            fill, at = 0.0, None
            if not gtc and cross:
                fill, at = min(n, float(q.get('size', n))), (q['ya'] if bid else q['yb'])
            self.n += 1
            oid = f'ord-{self.n}'
            self.orders[oid] = dict(order_id=oid, client_order_id=body['client_order_id'], ticker=body['ticker'], bid=bid, yes_c=yes_c, n=n, fill=fill, at=at,
                                    status='executed' if fill >= n else ('resting' if gtc else 'canceled'), maker=False, exp=body.get('expiration_time'))
            res = dict(order_id=oid, client_order_id=body['client_order_id'], fill_count=f'{fill:.2f}', remaining_count=f'{(n - fill) if gtc else 0:.2f}', ts_ms=1)
            if fill > 0:
                res.update(average_fill_price=f'{at / 100:.4f}', average_fee_paid=f'{0.07 * (at / 100) * (1 - at / 100):.6f}')
            return res
        if method == 'GET' and path.startswith(trade.ORDER_READ_PATH + '/'):
            o = self.orders.get(path.rsplit('/', 1)[1])
            if o is None:
                raise trade.ApiError('GET failed: HTTP 404 not found', 404)
            return {'order': self.view(o)}
        if method == 'DELETE' and path.startswith(trade.ORDER_PATH + '/'):
            assert (params or {}).get('market_ticker'), 'a cancel names its market so Kalshi can route it'
            o = self.orders.get(path.rsplit('/', 1)[1])
            if o is None or o['status'] != 'resting':
                raise trade.ApiError('DELETE failed: HTTP 404 not found', 404)
            o['status'] = 'canceled'
            return dict(order_id=o['order_id'], client_order_id=o['client_order_id'], reduced_by=f"{o['n'] - o['fill']:.2f}", ts_ms=2)
        raise AssertionError(f'the pilot called something it should not: {method} {path}')
    def view(self, o):
        bid = o['bid'] != self.flip
        own = None if o['at'] is None else (o['at'] if o['bid'] else 100 - o['at'])   # what the order's own side paid a contract
        cost = 0.0 if own is None else o['fill'] * own / 100
        fee = 0.0 if own is None else (0.0175 if o['maker'] else 0.07) * (own / 100) * (1 - own / 100) * o['fill']
        z = '0.000000'
        return dict(order_id=o['order_id'], client_order_id=o['client_order_id'], ticker=o['ticker'], outcome_side='yes' if bid else 'no', book_side='bid' if bid else 'ask',
                    type='limit', status=o['status'], yes_price_dollars=f"{o['yes_c'] / 100:.4f}", no_price_dollars=f"{(100 - o['yes_c']) / 100:.4f}",
                    initial_count_fp=f"{o['n']:.2f}", fill_count_fp=f"{o['fill']:.2f}", remaining_count_fp=f"{(o['n'] - o['fill']) if o['status'] == 'resting' else 0:.2f}",
                    maker_fill_cost_dollars=f'{cost:.6f}' if o['maker'] else z, taker_fill_cost_dollars=z if o['maker'] else f'{cost:.6f}',
                    maker_fees_dollars=f'{fee:.6f}' if o['maker'] else z, taker_fees_dollars=z if o['maker'] else f'{fee:.6f}', subaccount_number=self.sub)
    def fill(self, oid, n=None):
        """Someone trades through a resting order: it fills at its own price, as the maker."""
        o = self.orders[oid]
        o['fill'] = o['n'] if n is None else float(n)
        o['at'], o['maker'] = o['yes_c'], True
        if o['fill'] >= o['n']:
            o['status'] = 'executed'
    def posts(self):
        return [c[2] for c in self.calls if c[0] == 'POST']


fs = FakeStore()
store.enabled, store.read, store.fetch_all, store.write, store.claim = fs.enabled, fs.read, fs.fetch_all, fs.write, fs.claim
fs.t['control'] = [dict(id='trade', kill=False)]
for k in ('TRADE_ENABLED', 'KALSHI_TRADE_KEY_ID', 'KALSHI_TRADE_PRIVATE_KEY'):
    os.environ.pop(k, None)
cfg = json.load(open(os.path.join(ROOT, 'config.json')))
PILOT = dict(sports=['cbb'], wallet=500, night_cap=200, rest_pairs=5, single_cost=15, kinds=['rest', 'take'], leash=dict(night_cap=50, rest_pairs=3, single_cost=5))
pcfg = dict(cfg, sports=['cbb'], auto=dict(cfg['auto'], pilot=PILOT))
soon = lambda mins=10: (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=mins)).isoformat()

# 1. the order body
o = dict(market_ticker='KXNCAAMBTOTAL-26NOV02WOFTENN-140', side='yes', price_c=50, count=3, kind='rest', client_order_id='a', expire_at='2026-11-12T23:16:00+00:00')
b = trade.order_body(o)
assert b == dict(ticker='KXNCAAMBTOTAL-26NOV02WOFTENN-140', side='bid', count='3.00', price='0.5000', self_trade_prevention_type='taker_at_cross', client_order_id='a',
                 cancel_order_on_pause=True, time_in_force='good_till_canceled', post_only=True, expiration_time=int(dt.datetime(2026, 11, 12, 23, 16, tzinfo=dt.timezone.utc).timestamp())), b
b = trade.order_body(dict(o, side='no', price_c=58))
assert b['side'] == 'ask' and b['price'] == '0.4200', 'the under at 58c is an ask on the YES book at 42c'
b = trade.order_body(dict(o, side='no', price_c=30, kind='take', count=16))
assert b['side'] == 'ask' and b['price'] == '0.7000' and b['count'] == '16.00' and b['time_in_force'] == 'immediate_or_cancel' and 'post_only' not in b and 'expiration_time' not in b, b
try:
    trade.order_body(dict(o, expire_at=None))
    raise SystemExit('a resting order with no expiry got a body')
except ValueError:
    pass
assert trade.ORDER_PATH == '/portfolio/events/orders' and trade.ORDER_READ_PATH == '/portfolio/orders'
assert trade.own_price(dict(price_c=58), 42.0) == 58.0 and trade.own_price(dict(price_c=58), 58.0) == 58.0 and trade.own_price(dict(price_c=50), 47.0) == 47.0 and trade.own_price(dict(price_c=30), 72.0) == 28.0
assert trade.own_price(dict(price_c=30), 50.0) is None, 'a price that fits neither way is not guessed at'
assert trade.with_fee(None, 0.0131) == 'fee=0.0131' and trade.with_fee('x; fee=0.0100', 0.02) == 'x; fee=0.0200' and trade.fee_note('x; fee=0.0200') == 0.02 and trade.fee_note('x') is None
print('pilot: the order body is a bid or an ask on the YES book, fixed-point, post-only with an expiry or immediate-or-cancel')

# 2. the switches
config_pilot = (cfg.get('auto') or {}).get('pilot')
assert config_pilot and config_pilot.get('sports') == ['cbb'] and config_pilot.get('wallet') == 500, 'config.json auto.pilot: college basketball, a $500 wallet'
assert cfg['auto'].get('mode') == 'shadow'
plain = trade.Trader(dict(cfg, auto={k: v for k, v in cfg['auto'].items() if k != 'pilot'}), 3590)
assert plain.on and plain.mode() == 'shadow' and plain.pilot_sports() == [] and not plain.ready() and not plain.armed()
old_live = trade.Trader(dict(cfg, auto=dict({k: v for k, v in cfg['auto'].items() if k != 'pilot'}, mode='live')), 3590)
assert old_live.mode() == 'shadow' and not old_live.armed(), "auto.mode 'live' on its own sends nothing"
assert trade.Trader(dict(pcfg, auto=dict(pcfg['auto'], pilot=dict(PILOT, wallet=0))), 3590).pilot_sports() == [], 'no wallet, no pilot'
t = trade.Trader(pcfg, 3590)
assert t.pilot_sports() == ['cbb'] and t.pilot_wants('cbb') and not t.pilot_wants('nba') and not t.ready() and not t.armed()
os.environ['TRADE_ENABLED'] = '1'
assert not t.ready(), 'TRADE_ENABLED without a key is not ready'
os.environ['KALSHI_TRADE_KEY_ID'], os.environ['KALSHI_TRADE_PRIVATE_KEY'] = 'test-key', 'test-pem'
assert t.ready() and not t.armed(), 'every switch on and no self-test: not armed'
assert 'self-test pending' in t.status_line() and 'pilot for cbb, wallet $500' in t.status_line(), t.status_line()
r = t.send(dict(kind='rest', side='yes', action='buy', price_c=45, count=3, sport='cbb', date_et='2026-11-12', market_ticker='T', client_order_id='x', expire_at=soon(), game='t', strike=140.5, reason='rest_mid'))
assert r['status'] == 'skipped' and 'armed' in r['note'], r
print('pilot: nothing is armed on the config, the env switch and the key alone')

# 3. the self-test
EV = [dict(event_ticker='KXNCAAMBTOTAL-TEST', markets=[dict(ticker='TEST-140', floor_strike=140.5, status='active', yes_ask_dollars='0.5200', no_ask_dollars='0.5000', yes_bid_dollars='0.5000', no_bid_dollars='0.4800'),
                                                      dict(ticker='TEST-170', floor_strike=170.5, status='active', yes_ask_dollars='0.0300', no_ask_dollars='0.9900', yes_bid_dollars='0.0100', no_bid_dollars='0.9700')])]
assert trade.test_market(EV) == 'TEST-140' and trade.test_market([]) is None, 'the test runs on a market whose asks are nowhere near 1c'
k = FakeKalshi(balance=500.0, sub=1)
trade.api = k.api
res = t.preflight(EV)
assert res['ok'] and res['walled'] and res['subaccount'] == 1 and res['balance'] == 500.0 and t.armed(), res
posts = k.posts()
assert [(p['side'], p['price'], p['count'], p['post_only']) for p in posts] == [('bid', '0.0100', '1.00', True), ('ask', '0.9900', '1.00', True)], posts
assert [c[0] for c in k.calls] == ['GET', 'POST', 'GET', 'DELETE', 'POST', 'GET', 'DELETE'] and all(o['status'] == 'canceled' and o['fill'] == 0 for o in k.orders.values()), 'both test orders come down, unfilled'
title, body, pri, sig = t.preflight_push(res)
assert title == 'AUTO: armed for college basketball' and "Wall: Kalshi's. The key is locked to subaccount 1, which holds $500.00." in body, body
assert 'up to $200 of orders a night, 5 pairs a resting middle, $15 a play' in body and 'stops for good at $500 lost' in body and chr(8212) not in body, body
assert t.preflight_push(res)[3] == sig, 'the same answer has the same signature, so a restart does not push it again'
# a key that can see the whole account: armed, on the leash, and the balance is not put on a push
k2 = FakeKalshi(balance=3590.0, sub=0)
trade.api = k2.api
t2 = trade.Trader(pcfg, 3590)
res2 = t2.preflight(EV)
title, body, pri, sig2 = t2.preflight_push(res2)
assert res2['ok'] and not res2['walled'] and t2.armed() and "Wall: the desk's own. This key is not locked to a subaccount, so the short leash applies." in body, body
assert 'up to $50 of orders a night, 3 pairs a resting middle, $5 a play' in body and '3590' not in body and '3,590' not in body and sig2 != sig, body
# a subaccount that holds far more than the wallet is not a wall
k3 = FakeKalshi(balance=3000.0, sub=2)
trade.api = k3.api
t3 = trade.Trader(pcfg, 3590)
assert t3.preflight(EV)['ok'] and not t3.limits()['walled'] and 'Its subaccount holds more than the wallet' in t3.preflight_push()[1]
# winnings stay in: a walled wallet that has grown to $700 is still walled
k3.balance = 700.0
assert trade.Trader(pcfg, 3590).preflight(EV)['walled']
# Kalshi refuses the key: not armed, with where it stopped and what to check
bad = FakeKalshi()
bad.fail = lambda method, path, body: trade.ApiError('GET /portfolio/balance failed: HTTP 401 invalid signature', 401)
trade.api = bad.api
t4 = trade.Trader(pcfg, 3590)
res4 = t4.preflight(EV)
title, body, pri, _ = t4.preflight_push(res4)
assert not res4['ok'] and not t4.armed() and title == 'AUTO: NOT armed' and pri == 'high' and 'stopped at the balance read' in body and 'KALSHI_TRADE_KEY_ID' in body and 'Nothing will be sent' in body, body
bad.fail = lambda method, path, body: trade.ApiError('POST failed: HTTP 403 scope', 403) if method == 'POST' else None
res4 = t4.preflight(EV)
assert not res4['ok'] and res4['step'] == 'the YES test order' and 'needs read and trade' in t4.preflight_push(res4)[1] and not bad.orders, res4
# an order that reads back on the other side: the mapping is wrong somewhere, so nothing is armed and the test order still comes down
flip = FakeKalshi()
flip.flip = True
trade.api = flip.api
t5 = trade.Trader(pcfg, 3590)
res5 = t5.preflight(EV)
assert not res5['ok'] and not t5.armed() and 'meant yes, Kalshi holds outcome no' in res5['error'] and len(flip.posts()) == 1, res5
assert all(o['status'] == 'canceled' for o in flip.orders.values()), 'a failed self-test still cancels its test order'
# an order record without the fields a fill is read from: fills could go unseen, so nothing is armed
thin = FakeKalshi()
view = thin.view
thin.view = lambda o: {k: v for k, v in view(o).items() if k not in ('fill_count_fp', 'maker_fees_dollars')}
trade.api = thin.api
t7 = trade.Trader(pcfg, 3590)
res7 = t7.preflight(EV)
assert not res7['ok'] and not t7.armed() and 'without a fill count' in res7['error'] and all(o['status'] == 'canceled' for o in thin.orders.values()), res7
thin.view = lambda o: {k: v for k, v in view(o).items() if k != 'maker_fees_dollars'}
assert 'without maker_fees_dollars' in t7.preflight(EV)['error']
# the kill switch stops the self-test too: no test order goes up while it is on
fs.t['control'] = [dict(id='trade', kill=True)]
kk = FakeKalshi()
trade.api = kk.api
t8 = trade.Trader(pcfg, 3590)
res8 = t8.preflight(EV)
assert res8['wait'] and not res8['ok'] and res8['step'] == 'the kill switch' and not kk.calls, res8
fs.t['control'] = [dict(id='trade', kill=False)]
# no market to test on yet: wait, do not fail, do not arm
k6 = FakeKalshi()
trade.api = k6.api
t6 = trade.Trader(pcfg, 3590)
res6 = t6.preflight([])
assert res6['wait'] and not res6['ok'] and not t6.armed() and not k6.posts()
print('pilot: the self-test arms a key that works, reads the wall, and refuses a key or a mapping that is wrong')

# 4. the numbers in force
assert t.limits() == dict(walled=True, wallet=500.0, night_cap=200.0, rest_pairs=5, single_cost=15.0), t.limits()
assert t2.limits() == dict(walled=False, wallet=500.0, night_cap=50.0, rest_pairs=3, single_cost=5.0), t2.limits()
wild = trade.Trader(dict(pcfg, auto=dict(pcfg['auto'], pilot=dict(PILOT, wallet=1e6, night_cap=1e6, rest_pairs=10**6, single_cost=1e6))), 3590)
wild.verified = dict(ok=True, walled=True)
assert wild.limits() == dict(walled=True, wallet=500.0, night_cap=250.0, rest_pairs=40, single_cost=20.0), 'config cannot open more than the ceilings in code'
assert trade.PILOT_HARD == dict(wallet=500.0, night_cap=250.0, order_cost=20.0, order_count=40, orders_per_night=150)
print('pilot: the leash until the key is walled, the full numbers after, the ceilings in code over both')

# 5. the college basketball fixtures, armed and walled
pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': (pushes.append((title, body, priority)) or ['test'])
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv'); watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
FIX = os.path.join(ROOT, 'tests', 'fixtures_cbb')
book = {}
for ev in json.load(open(os.path.join(FIX, 'kalshi_KXNCAAMBTOTAL.json')))['events']:
    for q in feeds.total_quotes(ev).values():
        book[q['ticker']] = dict(ya=q['y'], yb=q['yb'])
k = FakeKalshi(balance=500.0, sub=1, book=book)
trade.api = k.api
d = watch.Desk(pcfg, {}, FIX)
d.trader = trade.Trader(pcfg, d.cfg['bankroll'])
assert d.trader.preflight(d.events('cbb', 'total'))['walled'] and d.trader.armed()
n_test = len(k.posts())
d.run_pass()
rec, rec4 = d.state['games']['601'], d.state['games']['604']
live = rec['auto']['half_live']
assert live['mode'] == 'live' and live['n'] >= 1, live
rows = [r for r in fs.t['orders'] if r['mode'] == 'live']
shadow = [r for r in fs.t['orders'] if r['mode'] == 'shadow']
assert rows and shadow, 'the shadow rows are still planned beside the live ones'
assert not {r['client_order_id'] for r in rows} & {r['client_order_id'] for r in shadow}
sent = k.posts()[n_test:]
assert len(sent) == len(rows) and all(r['kalshi_order_id'] for r in rows), (len(sent), len(rows))
lim = d.trader.limits()
for r in rows:
    assert r['sport'] == 'cbb' and r['stage'] == 'half' and r['action'] == 'buy' and r['count'] >= 1 and r['cost'] == round(r['count'] * r['price_c'] / 100, 2) <= trade.PILOT_HARD['order_cost']
    body = next(p for p in sent if p['client_order_id'] == r['client_order_id'])
    assert body['ticker'] == r['market_ticker'] and body['count'] == f"{r['count']}.00"
    assert (body['side'], body['price']) == (('bid', f"{r['price_c'] / 100:.4f}") if r['side'] == 'yes' else ('ask', f"{(100 - r['price_c']) / 100:.4f}")), (r, body)
    if r['kind'] == 'rest':
        assert r['count'] <= lim['rest_pairs'] and body['post_only'] is True and r['status'] == 'resting' and r['pair']
    else:
        assert r['cost'] <= lim['single_cost'] and body['time_in_force'] == 'immediate_or_cancel'
# the take is the push's lead single at the ask it named, filled at once and read back with its cost and fee
sh = rec['sheet']
takes = [r for r in rows if r['kind'] == 'take' and r['game_id'] == '601']
assert len(takes) == 1 and sh['singles'], rows
tk, lead = takes[0], sh['singles'][0]
assert (tk['strike'], tk['price_c'], tk['side']) == (lead['line'], lead['price_c'], 'yes' if lead['kind'] == 'over' else 'no'), (tk, lead)
assert tk['count'] == min(lead['contracts'], int(15 * 100 / lead['price_c'])) and tk['status'] == 'filled' and tk['filled_count'] == tk['count'] and tk['fill_price_c'] == tk['price_c'], tk
assert abs(trade.fee_note(tk['note']) - 0.07 * tk['count'] * (tk['price_c'] / 100) * (1 - tk['price_c'] / 100)) < 1e-4, tk['note']
# the resting middle is the one the push names, at pilot size, both legs
pairs = {}
for r in rows:
    if r['kind'] == 'rest':
        pairs.setdefault((r['game_id'], r['pair']), []).append(r)
assert pairs and all(len(v) == 2 and {x['side'] for x in v} == {'yes', 'no'} and v[0]['count'] == v[1]['count'] for v in pairs.values()), pairs
rm4 = rec4['sheet'].get('rest_mid')
legs4 = pairs.get(('604', f"{rm4['a_line']:g}/{rm4['b_line']:g}"))
assert legs4 and {(x['side'], x['strike'], x['price_c']) for x in legs4} == {('yes', rm4['a_line'], rm4['a_price']), ('no', rm4['b_line'], rm4['b_price'])}, (rm4, legs4)
assert legs4[0]['count'] == min(rm4['pairs'], 5)
# the push says what the pilot did
p601 = next(p for p in pushes if 'Terriers' in p[0])
assert 'AUTO did this one:' in p601[1] and 'Do not place these again.' in p601[1] and f"took {'Over' if tk['side'] == 'yes' else 'Under'} {tk['strike']:g} at {tk['price_c']}c, {tk['count']} of {tk['count']} filled" in p601[1], p601[1]
p604 = next(p for p in pushes if 'Dragons' in p[0])
assert 'AUTO did this one: resting Over' in p604[1] and chr(8212) not in p604[1], p604[1]
# a second pass plans nothing new
n_posts = len(k.posts())
d._events = {}; d.run_pass()
assert len(k.posts()) == n_posts, 'the pilot plans once per break'
print(f"pilot: {len(rows)} live orders on the fixtures ({len(pairs)} resting pairs, {len(takes)} take), written first, sent as the push names them, shadow rows untouched")

# a leg fills while it rests; the refresh reads it back with the price and the maker fee Kalshi charged
yes4 = next(x for x in legs4 if x['side'] == 'yes')
no4 = next(x for x in legs4 if x['side'] == 'no')
k.fill(yes4['kalshi_order_id'])
ch = d.trader.refresh(rec4)
row = next(r for r in fs.t['orders'] if r['client_order_id'] == yes4['client_order_id'])
assert [c['client_order_id'] for c in ch] == [yes4['client_order_id']] and row['status'] == 'filled' and row['fill_price_c'] == yes4['price_c'], row
fee = 0.0175 * yes4['count'] * (yes4['price_c'] / 100) * (1 - yes4['price_c'] / 100)
assert abs(trade.fee_note(row['note']) - fee) < 1e-4, (row['note'], fee)
assert [o['client_order_id'] for o in rec4['auto']['half_live']['open']] == [no4['client_order_id']], 'the filled leg leaves the open list, the other stays'
# the second half starts: what is still resting comes down
g4 = copy.deepcopy([x for x in d.games('cbb') if x['id'] == '604'][0])
d.watch_orders(g4, rec4, 'live')
row_no = next(r for r in fs.t['orders'] if r['client_order_id'] == no4['client_order_id'])
assert row_no['status'] == 'cancelled' and 'the break ended' in row_no['note'] and k.orders[no4['kalshi_order_id']]['status'] == 'canceled' and not d.trader.has_live_open(rec4), row_no
# the final: the filled leg is graded on what it paid and the fee Kalshi charged; the cancelled leg has no P&L
T = int(yes4['strike'] + 3.5)
d.trader.grade(dict(id='604', date_et=g4['date_et']), rec4, T)
row = next(r for r in fs.t['orders'] if r['client_order_id'] == yes4['client_order_id'])
assert row['pnl'] == round(yes4['count'] * (1 - yes4['price_c'] / 100) - trade.fee_note(row['note']), 2) and row['final_total'] == T and row['graded_at'], row
assert next(r for r in fs.t['orders'] if r['client_order_id'] == no4['client_order_id'])['pnl'] is None
assert not d.trader.outbox, 'the night is not summed while another game has live orders ungraded'
# the other game's final ends the night: one push sums it, with the shadow fill rate beside the pilot's
g1 = copy.deepcopy([x for x in d.games('cbb') if x['id'] == '601'][0])
d.trader.cancel_game(rec, 'the break ended')
d.trader.grade(dict(id='601', date_et=g1['date_et']), rec, 144)
out = d.trader.drain()
assert len(out) == 1 and out[0][0].startswith(f"AUTO {g1['date_et'][5:]}: "), out
body = out[0][1]
live_rows = [r for r in fs.t['orders'] if r['mode'] == 'live']
assert f"College basketball: {len(live_rows)} orders posted" in body and 'Resting legs filled: 1 of ' in body and 'The shadow model had ' in body and 'Wallet left: $' in body and chr(8212) not in body, body
led = d.trader.ledger(g1['date_et'])
assert led['posted'] == round(sum(r['cost'] for r in live_rows), 2) and led['realized'] == round(sum(r['pnl'] for r in live_rows if r['pnl'] is not None), 2), led
d.trader.grade(dict(id='601', date_et=g1['date_et']), rec, 144)
assert not d.trader.drain(), 'a night is summed once'
print('pilot: a fill is read back with its price and fee, the other leg comes down at the second half, the final grades it, one push sums the night')

# 6. the walls
def fresh(kalshi, sub_walled=True):
    fs.t['orders'] = []
    trade.api = kalshi.api
    tr = trade.Trader(pcfg, 3590)
    tr.verified = dict(ok=True, walled=sub_walled, subaccount=1 if sub_walled else 0, balance=500.0)
    return tr
mk = lambda i, side, strike, price, n, kind='rest', pair='140.5/145.5', date='2026-11-13': dict(
    client_order_id=f'c{i}', created_at=trade.now_iso(), game_id='g', sport='cbb', game='A @ B', date_et=date, event_ticker='E', market_ticker=f'E-{strike:g}', strike=strike, side=side,
    action='buy', kind=kind, stage='half', price_c=price, count=n, cost=round(n * price / 100, 2), expire_at=soon(), reason='rest_mid' if kind == 'rest' else 'single', pair=pair if kind == 'rest' else None,
    mode='live', status='planned', kalshi_order_id=None, sent_at=None, filled_count=None, fill_price_c=None, filled_at=None, touched_at=None, touch_phase=None, touch_s=None, pnl=None,
    graded_at=None, final_total=None, note=None)
# the night cap, on the leash: $50 of orders, filled or not. $47 is already posted; a $5.40 pair does not fit, so neither leg goes.
k = FakeKalshi(); tr = fresh(k, sub_walled=False)
fs.t['orders'] = [dict(mk(90, 'yes', 130.5, 47, 100), status='expired', cost=47.0)]
done, note = tr.act_live([mk(1, 'yes', 140.5, 50, 5), mk(2, 'no', 145.5, 58, 5)])
assert done == [] and note.startswith('night cap: $47.00 posted, $3.00 of room') and not k.posts(), (done, note)
say = tr.drain()
assert len(say) == 1 and say[0][0] == 'AUTO: done for the night' and 'short leash' in say[0][1], say
done, note = tr.act_live([mk(3, 'yes', 141.5, 50, 5), mk(4, 'no', 146.5, 58, 5)])
assert done == [] and not tr.drain(), 'the cap is said once a night'
# a single that fits still goes, and its cost is counted at once: the next one does not fit
done, note = tr.act_live([mk(5, 'yes', 140.5, 50, 5, kind='take')])
assert len(done) == 1 and done[0]['status'] == 'cancelled' and done[0]['note'] == 'the ask was gone' and tr.posted['2026-11-13'] == 2.5, done
done, note = tr.act_live([mk(6, 'yes', 140.5, 50, 2, kind='take')])
assert done == [] and 'night cap' in note
# walled: the same night has $200 of room
tr = fresh(FakeKalshi())
fs.t['orders'] = [dict(mk(90, 'yes', 130.5, 47, 100), status='expired', cost=47.0)]
done, note = tr.act_live([mk(1, 'yes', 140.5, 50, 5), mk(2, 'no', 145.5, 58, 5)])
assert [o['status'] for o in done] == ['resting', 'resting'] and note is None
# the wallet: realized losses count for good; an order from an earlier night that may have filled and was never graded counts as lost
tr = fresh(FakeKalshi())
fs.t['orders'] = [dict(mk(80, 'yes', 130.5, 50, 40, date='2026-11-10'), status='filled', filled_count=40, pnl=-420.0, graded_at='x'),
                  dict(mk(81, 'yes', 131.5, 50, 40, date='2026-11-11'), status='unconfirmed', cost=20.0),
                  dict(mk(82, 'yes', 132.5, 50, 40, date='2026-11-11'), status='filled', filled_count=30, fill_price_c=50, cost=20.0),
                  dict(mk(83, 'yes', 133.5, 50, 40, date='2026-11-11'), status='expired', cost=20.0)]
led = tr.ledger('2026-11-13')
assert led == dict(posted=0.0, realized=-455.0, orders=0), led     # -420 graded, -20 unconfirmed, -15 filled and ungraded; the expired order cost nothing
assert tr.room(led, '2026-11-13') == (45.0, 45.0, 0.0)
done, note = tr.act_live([mk(1, 'yes', 140.5, 50, 40, kind='take'), mk(2, 'yes', 141.5, 50, 40, kind='take'), mk(3, 'yes', 142.5, 50, 40, kind='take')])
assert len(done) == 2 and 'night cap' in note, (len(done), note)    # $20 and $20 fit in $45, the third does not
fs.t['orders'].append(dict(mk(84, 'yes', 134.5, 50, 40, date='2026-11-12'), status='filled', filled_count=40, pnl=-60.0, graded_at='x'))
done, note = tr.act_live([mk(4, 'yes', 143.5, 50, 2, kind='take', date='2026-11-14')])
assert done == [] and note.startswith('the wallet is spent ($515.00 lost of $500)'), note
assert tr.drain()[-1][0] == 'AUTO: the wallet is spent'
# an unreadable orders table stops everything, in the batch and inside send(); so does an unreadable control row
k = FakeKalshi(); tr = fresh(k)
fs.down = {'orders'}
done, note = tr.act_live([mk(1, 'yes', 140.5, 50, 5, kind='take')])
assert done == [] and 'no read, no send' in note and not k.posts()
o = mk(2, 'yes', 140.5, 50, 5, kind='take')
assert tr.send(o)['status'] == 'skipped' and 'no read, no send' in o['note'] and not k.posts(), o
fs.down = {'control'}
tr._kill = (None, 0.0)
o = mk(2, 'yes', 140.5, 50, 5, kind='take')
assert tr.send(o)['status'] == 'skipped' and 'not armed' in o['note'] and not k.posts(), 'a kill row that cannot be read is a kill'
fs.down = set()
tr._kill = (None, 0.0)
# a row already in the table is not sent again (a restart that plans the same order)
done, _ = tr.act_live([mk(1, 'yes', 140.5, 50, 5, kind='take')])
assert len(done) == 1 and len(k.posts()) == 1
done, note = tr.act_live([mk(1, 'yes', 140.5, 50, 5, kind='take')])
assert done == [] and 'already in the table' in note and len(k.posts()) == 1
# the ceilings and the expiry, inside send() whatever planned the order
for bad, word in ((mk(10, 'yes', 140.5, 50, 41), 'over the ceiling'), (mk(11, 'yes', 140.5, 90, 23), 'over the ceiling'), (dict(mk(12, 'yes', 140.5, 50, 5), expire_at=soon(45)), 'must expire inside'),
                  (dict(mk(13, 'yes', 140.5, 50, 5), expire_at=None), 'must expire inside'), (dict(mk(14, 'yes', 140.5, 50, 5), sport='nba'), 'not a pilot sport')):
    n = len(k.posts())
    r = tr.send(bad)
    assert r['status'] == 'skipped' and word in r['note'] and len(k.posts()) == n, (r['note'], word)
for bad in (dict(mk(15, 'yes', 140.5, 50, 5), price_c=0), dict(mk(16, 'yes', 140.5, 50, 5), count=0), dict(mk(17, 'yes', 140.5, 50, 5), action='sell'), dict(mk(18, 'yes', 140.5, 50, 5), side='over')):
    try:
        tr.send(bad)
        raise SystemExit(f'send accepted {bad}')
    except AssertionError as e:
        assert 'network' not in str(e)
# the kill switch disarms; an unreadable control row does too
fs.t['control'] = [dict(id='trade', kill=True)]
tr._kill = (None, 0.0)
assert not tr.armed() and tr.send(mk(20, 'yes', 140.5, 50, 5))['status'] == 'skipped'
fs.t['control'] = []
tr._kill = (None, 0.0)
assert tr.kill() and not tr.armed(), 'no control row, no send'
fs.t['control'] = [dict(id='trade', kill=False)]
tr._kill = (None, 0.0)
assert tr.armed()
# no clean answer from Kalshi: the order may be live, so it counts as posted and the phone hears about it; a refusal does not count
k = FakeKalshi(); tr = fresh(k)
k.fail = lambda method, path, body: trade.ApiError('POST failed: timed out', None) if method == 'POST' else None
done, _ = tr.act_live([mk(1, 'yes', 140.5, 50, 5, kind='take')])
assert done[0]['status'] == 'unconfirmed' and tr.posted['2026-11-13'] == 2.5 and tr.ledger('2026-11-13')['posted'] == 2.5, done
assert tr.drain()[0][0] == 'AUTO: an order got no answer'
k.fail = lambda method, path, body: trade.ApiError('POST failed: HTTP 400 market closed', 400) if method == 'POST' else None
done, _ = tr.act_live([mk(2, 'yes', 141.5, 50, 5, kind='take')])
assert done[0]['status'] == 'rejected' and tr.posted['2026-11-13'] == 2.5 and tr.ledger('2026-11-13')['posted'] == 2.5, 'a refused order posted nothing'
assert tr.drain()[0][0] == 'AUTO: Kalshi refused an order'
# a resting leg Kalshi refuses as crossing is refused cleanly; the other leg still rests
k = FakeKalshi(book={'E-140.5': dict(ya=50, yb=48)}); tr = fresh(k)
done, _ = tr.act_live([mk(1, 'yes', 140.5, 50, 5), mk(2, 'no', 145.5, 58, 5)])
assert [o['status'] for o in done] == ['rejected', 'resting'], [o['status'] for o in done]
# a take against a thin ask fills what is there and cancels the rest
k = FakeKalshi(book={'E-140.5': dict(ya=48, yb=46, size=2)}); tr = fresh(k)
done, _ = tr.act_live([mk(1, 'yes', 140.5, 50, 5, kind='take')])
assert done[0]['status'] == 'partial' and done[0]['filled_count'] == 2 and done[0]['fill_price_c'] == 48.0, done[0]
assert trade.Trader.pnl_of(done[0], 150) == round(2 * 0.52 - trade.fee_note(done[0]['note']), 2), 'graded on what filled, at the price it filled at'
# a take whose record cannot be read back keeps what the create call said, and says so
k = FakeKalshi(book={'E-140.5': dict(ya=48, yb=46)}); tr = fresh(k)
k.fail = lambda method, path, body: trade.ApiError('GET failed: HTTP 500', 500) if method == 'GET' else None
done, _ = tr.act_live([mk(1, 'yes', 140.5, 50, 5, kind='take')])
assert done[0]['status'] == 'filled' and done[0]['filled_count'] == 5 and done[0]['fill_price_c'] == 48.0 and 'not read back' in done[0]['note'] and trade.fee_note(done[0]['note']) is not None, done[0]
# an order record this code cannot read is not an answer: the row stays as it was
k = FakeKalshi(); tr = fresh(k)
done, _ = tr.act_live([mk(1, 'yes', 140.5, 50, 5), mk(2, 'no', 145.5, 58, 5)])
view = k.view
k.view = lambda o: dict(view(o), status='pending_review')
rec_x = dict(auto=dict(half_live=dict(at=trade.now_iso(), open=list(done))))
assert tr.refresh(rec_x) == [] and [o['status'] for o in rec_x['auto']['half_live']['open']] == ['resting', 'resting'], 'an unknown status changes nothing'
k.view = view
# the pilot stays out of a game Nick already holds, and plans nothing unarmed
assert tr.plan_pilot(dict(id='g', sport='cbb', short='A @ B', date_et='2026-11-13'), 'half', None, [], {}, {}, {}, {}, trade.now_iso(), held_legs=[dict(side='yes')])[1].startswith('you already hold')
tr.verified = None
assert tr.plan_pilot(dict(id='g', sport='cbb', short='A @ B', date_et='2026-11-13'), 'half', None, [], {}, {}, {}, {}, trade.now_iso()) == ([], None)
print('pilot: the night cap, the wallet, the ledger, the ceilings, the kill switch and an unanswered order each stop it the way they should')
print('pilot: ok')
