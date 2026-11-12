"""The walls around trade.py, the one module that may send an order. No network. (tests/pilot.py runs the pilot,
the only sending path, against a fake Kalshi.)
1. Static: only trade.py names an order endpoint (tests/readonly.py checks the rest of the repo), and the endpoints
   are Kalshi's V2 event-order path to write and the order path to read; portfolio.py still signs GET only.
2. armed(): false unless config carries a pilot block with a sport and a wallet AND TRADE_ENABLED=1 AND the trade
   key is present AND the kill switch is off AND the self-test passed in this process. config auto.mode 'live' on
   its own arms nothing. send() with any switch off records 'skipped' and never calls the network. send() refuses
   a price outside 1 to 99, a count under 1, or anything that is not a buy limit order. With every switch on a
   good order reaches the network, which this test forbids: with no clean answer it is recorded as unconfirmed.
3. The shadow planner on the NBA fixtures: the resting middle legs at the resting limits, sized so the
   worst final loses at most the auto cap; the push's lead (the middle) as takes; deterministic ids; nothing
   sent. The night budget and a held middle spend the cap. fit_cap scales a set of legs under the cap.
4. The shadow fill model: a resting bid is touched when the ask reaches it, not on the pass that planned it;
   an order past its expiry is expired. pnl_of grades a touched leg (the maker fee) and a take (the taker fee).
5. The signer: GET, POST and DELETE signatures verify."""
import sys, os, re, json, base64, tempfile, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine, watch, notify, store, trade

# 1. static
src = open(os.path.join(ROOT, 'trade.py')).read()
assert "ORDER_PATH = '/portfolio/events/orders'" in src and "ORDER_READ_PATH = '/portfolio/orders'" in src
assert trade.ORDER_PATH == '/portfolio/events/orders', "Kalshi's V2 order calls: the old write path was retired in June 2026"
assert "api('POST', ORDER_READ_PATH" not in src and "api('DELETE', f\"{ORDER_READ_PATH}" not in src and "api('DELETE', f'{ORDER_READ_PATH}" not in src, 'the old order path is read-only here'
pf = open(os.path.join(ROOT, 'portfolio.py')).read()
assert "if method != 'GET':" in pf and 'portfolio/orders' not in pf and 'events/orders' not in pf, 'portfolio.py must stay GET-only and name no order endpoint'
for name in ('watch.py', 'worker.py', 'held.py', 'feeds.py', 'store.py', 'engine.py'):
    text = open(os.path.join(ROOT, name)).read()
    assert 'portfolio/orders' not in text and 'events/orders' not in text, f'{name} names an order endpoint'
print('static: trade.py is the only module that names an order endpoint')

# a network call anywhere in this test is a failure
import requests
def boom(*a, **k):
    raise AssertionError('network call attempted')
requests.get = requests.post = requests.request = requests.delete = requests.patch = requests.put = boom

# 2. switches
cfg = json.load(open(os.path.join(ROOT, 'config.json')))
assert cfg.get('auto', {}).get('mode') == 'shadow', "config.json auto.mode stays shadow: it labels the planner's rows and sends nothing"
pilot = cfg['auto'].get('pilot') or {}
assert pilot.get('sports') == ['cbb'] and pilot.get('wallet') == 500, 'the pilot is college basketball with a $500 wallet'
assert pilot['night_cap'] <= trade.PILOT_HARD['night_cap'] and pilot['wallet'] <= trade.PILOT_HARD['wallet'] and pilot['leash']['night_cap'] == 50, pilot
for k in ('TRADE_ENABLED', 'KALSHI_TRADE_KEY_ID', 'KALSHI_TRADE_PRIVATE_KEY'):
    os.environ.pop(k, None)
no_pilot = dict(cfg, auto={k: v for k, v in cfg['auto'].items() if k != 'pilot'})
t = trade.Trader(no_pilot, 3590)
assert t.on and t.mode() == 'shadow' and not t.armed() and t.pilot_sports() == []
old = trade.Trader(dict(no_pilot, auto=dict(no_pilot['auto'], mode='live')), 3590)
assert old.mode() == 'shadow' and not old.ready() and not old.armed(), "auto.mode 'live' in config arms nothing: the pilot block is the only way out"
live = trade.Trader(cfg, 3590)
assert live.pilot_sports() == ['cbb'] and not live.ready() and not live.armed(), 'the pilot block alone must not arm'
os.environ['TRADE_ENABLED'] = '1'
assert not live.ready() and not live.armed(), 'TRADE_ENABLED without a key must not arm'
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
ed = ed25519.Ed25519PrivateKey.generate()
os.environ['KALSHI_TRADE_KEY_ID'] = 'test-key'
os.environ['KALSHI_TRADE_PRIVATE_KEY'] = ed.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
store.enabled = lambda: True
store.read = lambda table, params: [dict(kill=False)]
live._kill = (None, 0.0)
assert live.ready() and not live.armed(), 'every switch on and no self-test: not armed'
# a self-test that cannot reach Kalshi is not a pass
res = live.preflight([dict(event_ticker='E', markets=[dict(ticker='E-140', floor_strike=140.5, status='active', yes_ask_dollars='0.5200', no_ask_dollars='0.5000')])])
assert not res['ok'] and 'network call attempted' in res['error'] and not live.armed(), res
live.verified = dict(ok=True, walled=False)
# the kill switch: with Supabase on, a kill row stops it; with Supabase unreadable, kill() is True (no read, no send)
store.read = lambda table, params: [dict(kill=True)]
live._kill = (None, 0.0)
assert live.kill() and not live.armed(), 'kill true must disarm'
store.read = lambda table, params: []
live._kill = (None, 0.0)
assert live.kill() and not live.armed(), 'an unreadable control row must disarm'
store.read = lambda table, params: [dict(kill=False)]
live._kill = (None, 0.0)
assert live.armed(), 'every switch on and the self-test passed: armed'
soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)).isoformat()
o = dict(kind='rest', side='yes', action='buy', price_c=45, count=3, sport='cbb', date_et='2026-11-12', market_ticker='KXNCAAMBTOTAL-26NOV12AB-140', client_order_id='x', expire_at=soon,
         game='t', strike=140.5, reason='rest_mid', cost=1.35)
os.environ['TRADE_ENABLED'] = '0'
r = live.send(dict(o))
assert r['status'] == 'skipped' and 'armed' in r['note'], r
os.environ['TRADE_ENABLED'] = '1'
store.fetch_all = lambda table, params, key, page=1000: []
for bad in (dict(o, price_c=0), dict(o, price_c=100), dict(o, count=0), dict(o, action='sell'), dict(o, kind='market'), dict(o, side='over')):
    try:
        live.send(bad)
        raise SystemExit(f'send accepted {bad}')
    except AssertionError as e:
        if 'network' in str(e):
            raise SystemExit(f'send reached the network for {bad}')
# the ledger cannot be read: no send
store.fetch_all = lambda table, params, key, page=1000: None
r = live.send(dict(o))
assert r['status'] == 'skipped' and 'no read, no send' in r['note'], r
# a good order with every switch on reaches the network, which this test forbids: no clean answer came back, so the
# order is recorded as one that may be live, never as one that was refused
store.fetch_all = lambda table, params, key, page=1000: []
r = live.send(dict(o))
assert r['status'] == 'unconfirmed' and 'network call attempted' in (r.get('note') or ''), r
store.enabled = lambda: False
os.environ['TRADE_ENABLED'] = '0'
print('switches: the pilot block, TRADE_ENABLED, the trade key, the kill row and the self-test all have to agree; bad orders refused')

# 3. the planner on the fixtures
notify.push = lambda title, body, priority='default', tags='football': ['test']
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv'); watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg2 = dict(cfg, sports=['nba'])
d = watch.Desk(cfg2, {}, os.path.join(ROOT, 'tests', 'fixtures_nba'))
d.trader = trade.Trader(cfg2, d.cfg['bankroll'])
d.run_pass()
rec = d.state['games']['501']
auto = rec['auto']['half']
assert auto['mode'] == 'shadow' and auto['n'] >= 4, auto
rests = [o for o in auto['open'] if o['kind'] == 'rest']
takes = [o for o in auto['open'] if o['kind'] == 'take']
assert rests and takes, auto
cap = d.trader.cap_game()
assert abs(cap - 3590 * 0.005) < 1e-6
# the legs sit at the resting limits the push named, and every one is a planned shadow order with a cost
for o in rests + takes:
    assert o['status'] == 'planned' and o['mode'] == 'shadow' and o['count'] >= 1 and 1 <= o['price_c'] <= 99 and o['cost'] == round(o['count'] * o['price_c'] / 100, 2)
    assert o['market_ticker'].startswith('KXNBATOTAL-') and o['event_ticker'] == rec['kalshi_total_event'] and o['stage'] == 'half'
    assert o['client_order_id'] == trade.order_id('501', 'half', o['side'], o['strike'], o['price_c'], o['kind'], o['reason'])
legs = [dict(side=o['side'], strike=o['strike'], shares=o['count'], paid_c=o['price_c'], fee=0) for o in rests]
worst = min(r['pnl'] for r in engine.pnl_regions(legs))
assert worst >= -cap - 1e-6, (worst, cap)
assert any(o['reason'] == 'rest_mid' for o in rests) and any(o['reason'] == 'rest_mid wide' for o in rests), [o['reason'] for o in rests]
assert {o['reason'] for o in takes} == {'play_mid'} and len(takes) == 2, 'the NBA push led with the middle, so the takes are its two legs'
sh = rec['sheet']
assert sorted(o['strike'] for o in takes) == sorted([sh['mid']['a_line'], sh['mid']['b_line']]) and takes[0]['count'] == sh['mid']['pairs']
# the resting expiry runs to the fourth quarter (rest_until q4), a take's to the end of the break
assert all(o['expire_at'] > auto['at'] for o in rests + takes)
assert max(o['expire_at'] for o in rests) > max(o['expire_at'] for o in takes)
# the second window (OKC at SA at the end of the third) planned too, in its own stage
assert d.state['games']['503']['auto']['q3']['n'] >= 2
# ids are deterministic and change with price
assert trade.order_id('g', 'half', 'yes', 224.5, 63, 'rest', 'rest_mid') == trade.order_id('g', 'half', 'yes', 224.5, 63, 'rest', 'rest_mid') != trade.order_id('g', 'half', 'yes', 224.5, 64, 'rest', 'rest_mid')
print(f"planner: {len(rests)} resting legs (worst final {worst:+.2f} against a ${cap:.2f} cap) and {len(takes)} take legs, shadow, nothing sent")

# the night budget: a night already down the budget plans nothing
t2 = trade.Trader(cfg2, 3590)
t2.night_state = lambda date_et: dict(open_cost=0.0, orders=0, pnl=-t2.cap_night())
pl, note = t2.plan(dict(id='x', sport='nba', short='x', date_et='2026-10-23'), {}, 'half', None, [], {}, {}, {}, dict(max_risk=89, max_cost=269, margin=0.03), '2026-10-23T00:00:00+00:00')
assert pl == [] and 'night budget' in note, note
# a held middle spends the cap: what you hold already risks the cap, so nothing new
t3 = trade.Trader(cfg2, 3590)
t3.night_state = lambda date_et: dict(open_cost=0.0, orders=0, pnl=0.0)
held = [dict(side='yes', strike=224.5, shares=400, paid_c=60, fee=0), dict(side='no', strike=228.5, shares=400, paid_c=45, fee=0)]   # a miss loses $20
pl, note = t3.plan(dict(id='x', sport='nba', short='x', date_et='2026-10-23'), {}, 'half', None, [], {}, {}, {}, dict(max_risk=89, max_cost=269, margin=0.03), '2026-10-23T00:00:00+00:00', held_legs=held)
assert pl == [] and 'already risks' in note, note
# fit_cap scales a set of legs until the worst final is inside the cap
big = [dict(side='yes', strike=224.5, price_c=63, count=1000, reason='r', pair=None, kind='rest'), dict(side='no', strike=228.5, price_c=42, count=1000, reason='r', pair=None, kind='rest')]
fit = trade.Trader.fit_cap(big, [], 10.0)
w = min(r['pnl'] for r in engine.pnl_regions([dict(side=o['side'], strike=o['strike'], shares=o['count'], paid_c=o['price_c'], fee=0) for o in fit]))
assert fit and w >= -10.0 and fit[0]['count'] < 1000, (fit, w)
print('caps: the night budget stops planning, a held middle spends the cap, fit_cap scales legs under it')

# 4. the fill model
t4 = trade.Trader(cfg2, 3590)
mk = lambda side, strike, price, created, expire, kind='rest': dict(client_order_id=f'{side}{strike}', side=side, strike=strike, price_c=price, count=10, kind=kind, mode='shadow', status='planned',
                                                                   created_at=created, expire_at=expire, cost=round(10 * price / 100, 2))
rec4 = dict(auto=dict(half=dict(at='2026-10-23T01:00:00+00:00', open=[mk('yes', 224.5, 63, '2026-10-23T01:00:00+00:00', '2026-10-23T01:50:00+00:00'),
                                                                     mk('no', 228.5, 42, '2026-10-23T01:00:00+00:00', '2026-10-23T01:50:00+00:00'),
                                                                     mk('no', 236.5, 65, '2026-10-23T01:00:00+00:00', '2026-10-23T01:10:00+00:00')])))
# the planning pass itself touches nothing
ch = t4.touch(dict(id='x'), rec4, {224.5: dict(y=60, n=41), 228.5: dict(y=59, n=40)}, 'half', at='2026-10-23T01:00:00+00:00')
assert ch == [] and len(rec4['auto']['half']['open']) == 3
# five seconds later the YES ask at 224.5 sits at 60, under the 63 bid: touched at the break, 5 s after the first look
ch = t4.touch(dict(id='x'), rec4, {224.5: dict(y=60, n=41), 228.5: dict(y=59, n=44)}, 'half', at='2026-10-23T01:00:05+00:00')
assert [c['client_order_id'] for c in ch] == ['yes224.5'] and ch[0]['status'] == 'touched' and ch[0]['touch_phase'] == 'half' and ch[0]['touch_s'] == 5, ch
assert [o['client_order_id'] for o in rec4['auto']['half']['open']] == ['no228.5', 'no236.5']
# in play the NO ask at 228.5 drops to 42: touched in play; the 236.5 order is past its expiry: expired
ch = t4.touch(dict(id='x'), rec4, {224.5: dict(y=70, n=31), 228.5: dict(y=60, n=42)}, 'live', at='2026-10-23T01:20:00+00:00')
st = {c['client_order_id']: c['status'] for c in ch}
assert st == {'no228.5': 'touched', 'no236.5': 'expired'} and next(c for c in ch if c['client_order_id'] == 'no228.5')['touch_phase'] == 'live', st
assert rec4['auto']['half']['open'] == []
# grading: YES 224.5 at 63 x10 on a 230 final wins 3.70 less the 5c maker fee; NO 228.5 at 42 x10 loses 4.20 and the
# fee; a take pays the taker fee
y = dict(side='yes', strike=224.5, price_c=63, count=10, kind='rest', mode='shadow')
n = dict(side='no', strike=228.5, price_c=42, count=10, kind='rest', mode='shadow')
assert engine.order_fee(10, 0.63, 'maker') == 0.05 and engine.order_fee(10, 0.42, 'maker') == 0.05
assert trade.Trader.pnl_of(y, 230) == 3.65 and trade.Trader.pnl_of(n, 230) == -4.25 and trade.Trader.pnl_of(n, 226) == 5.75
tk = dict(side='yes', strike=224.5, price_c=63, count=10, kind='take', mode='shadow')
assert trade.Trader.pnl_of(tk, 230) == round(3.7 - engine.order_fee(10, 0.63, 'taker'), 2)
lv = dict(side='yes', strike=224.5, price_c=63, count=10, filled_count=4, kind='rest', mode='live')
assert trade.Trader.pnl_of(lv, 230) == round(4 * 0.37 - engine.order_fee(4, 0.63, 'maker'), 2) == 1.46, 'a live partial fill is graded on what filled'
print('fill model: touched when the ask reaches the bid (break vs in play), expired past the window, graded at the final')

# 5. the signer
sig = base64.b64decode(trade.sign(ed, '1760000000000', 'POST', '/trade-api/v2' + trade.ORDER_PATH))
ed.public_key().verify(sig, b'1760000000000POST/trade-api/v2/portfolio/events/orders')
sig = base64.b64decode(trade.sign(ed, '1760000000000', 'DELETE', '/trade-api/v2' + trade.ORDER_PATH + '/abc'))
ed.public_key().verify(sig, b'1760000000000DELETE/trade-api/v2/portfolio/events/orders/abc')
sig = base64.b64decode(trade.sign(ed, '1760000000000', 'GET', '/trade-api/v2' + trade.ORDER_READ_PATH + '/abc'))
ed.public_key().verify(sig, b'1760000000000GET/trade-api/v2/portfolio/orders/abc')
assert type(trade.load_trade_key()) is type(ed)
print('signer: POST and DELETE verify with the trade key')
print('trade_guard: ok')
