"""Fees (Nov 12). The engine prices a take at 7% x P x (1 - P) and a resting fill at 1.75% x P x (1 - P): what Kalshi's
own record says for the total series the desk prices (fee_type quadratic_with_maker_fees, multiplier 1; Kalshi's fee
change history dates it to Nov 15, 2025). Until Nov 12, 2026 the desk priced a resting fill at no fee.
1. The engine: both rates, the resting limit with the maker fee inside the margin, the resting pair's cost, win and
   miss with the fee in, and a filled order graded with the fee it pays.
2. watch.Desk.fee_check reads Kalshi's record of each series against what the engine charges itself and pushes once
   per distinct record that differs: loud when Kalshi charges more than the desk counts (its limits are too high),
   quiet when Kalshi charges less (its limits are a touch low, which is safe). When a series that was pushed reads
   as priced again, one push says so. The state the live worker held on Nov 12 (all four series pushed as maker
   fees the desk did not price) clears with one push.
No network."""
import sys, os, json, copy, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, feeds, notify, store, engine, worker, trade

import requests
def boom(*a, **k):
    raise AssertionError('network call attempted')
requests.get = requests.post = requests.request = boom

# 1. what the engine is built on
assert engine.FEE_RATE == 0.07 and engine.MAKER_RATE == 0.0175
assert abs(engine.fee_per(0.5) - 0.0175) < 1e-12 and abs(engine.fee_per(0.5, 'maker') - 0.004375) < 1e-12
assert engine.order_fee(100, 0.5) == 1.75 and engine.order_fee(100, 0.5, 'maker') == 0.44 and engine.order_fee(1, 0.5, 'maker') == 0.01, 'a fee rounds up to the cent per order'
# the most to bid so that price plus fee stays inside the margin: a take at 48c, a resting order at 49c, for a 50c all-in
assert engine.max_quote(0.50, 'taker') == 48 and engine.max_quote(0.50, 'maker') == 49 and engine.max_quote(0.505, 'maker') == 50
assert set(feeds.SERIES[s]['total'] for s in ('nfl', 'cfb', 'nba', 'cbb')) == {'KXNFLTOTAL', 'KXNCAAFTOTAL', 'KXNBATOTAL', 'KXNCAAMBTOTAL'}
# a college basketball half: every resting limit carries the maker fee inside the 3c margin, and one cent more would not
m = engine.HalfModel('cbb', 145.5, -4.0, 34, 31)
rows = engine.price_lines(m, [l + 0.5 for l in range(130, 160)], 'fg', 0.03)
moved = 0
for r in rows:
    for fair, rest, take in ((r['p_over'], r['over_rest'], r['over_take']), (r['p_under'], r['under_rest'], r['under_take'])):
        if not 1 <= rest <= 98:
            continue
        p = rest / 100
        assert p + engine.fee_per(p, 'maker') <= fair - 0.03 + 1e-9, (r['line'], rest, fair)
        assert (p + 0.01) + engine.fee_per(p + 0.01, 'maker') > fair - 0.03 + 1e-9, (r['line'], rest, fair)
        assert take <= rest <= take + 2, 'a resting limit sits at or a cent or two over the take limit'
        moved += rest < int(100 * (fair - 0.03) + 1e-9)
assert moved >= 5, 'on a full ladder the maker fee moves some limits down a cent'
rp = engine.rest_plan(m, rows, 'fg', 0.03, 3590.0, 89.75, 269.25, near_pts=6)
assert rp['middles'] and rp['legs']
for md in rp['middles']:
    pa, pb, n = md['a']['over_rest'] / 100, md['b']['under_rest'] / 100, md['pairs']
    assert abs(md['c'] - (pa + pb + engine.fee_per(pa, 'maker') + engine.fee_per(pb, 'maker'))) < 1e-12, md['c']
    cost = round(n * (pa + pb) + engine.order_fee(n, pa, 'maker') + engine.order_fee(n, pb, 'maker'), 2)
    assert md['cost'] == cost and md['best'] == round(2 * n - cost, 2) and md['worst'] == round(n - cost, 2), md
    assert md['worst'] < n * (1 - pa - pb) < 0 < md['best'], 'a miss costs the two limits and the two fees'
for l in rp['legs']:
    assert l['y_cost'] == round(l['y_n'] * l['y_c'] / 100 + engine.order_fee(l['y_n'], l['y_c'] / 100, 'maker'), 2), l
# a filled order, graded: YES 224.5 at 63c x10 on a 230 final. Resting: 3.70 less a 5c maker fee. Taken: less 17c.
assert engine.fill_pnl('yes', 224.5, 63, 10, 'rest', 230) == 3.65 and engine.fill_pnl('yes', 224.5, 63, 10, 'take', 230) == 3.53
assert engine.fill_pnl('yes', 224.5, 63, 10, 'rest', 220) == -6.35 and engine.fill_pnl('no', 224.5, 37, 10, 'rest', 220) == 6.25
# a row graded before Nov 12 holds the resting fill at no fee; read back, it is net of the fee like any other
old = dict(side='yes', strike=224.5, price_c=63, count=10, kind='rest', mode='shadow', pnl=3.7, final_total=230)
assert trade.net_pnl(old) == 3.65 and trade.net_pnl(dict(old, pnl=None)) is None and trade.net_pnl(dict(old, final_total=None)) == 3.7
# the auto cap counts the fee: two resting legs whose miss is $8.00 at the limits and $8.87 with both maker fees
legs = [dict(side='yes', strike=140.5, price_c=50, count=100, kind='rest'), dict(side='no', strike=145.5, price_c=58, count=100, kind='rest')]
assert [l['count'] for l in trade.Trader.fit_cap(legs, [], 9.0)] == [100, 100]
assert [l['count'] for l in trade.Trader.fit_cap(legs, [], 8.5)] == [80, 80], 'a cap between the two numbers must trim the legs'
print('fees: the engine prices the maker fee into resting limits, pairs, caps and graded fills')

# 1b. the app (app/lib/desk.js) charges the same two fees and grades a fill the same way. Runs when node is on the box.
import shutil, subprocess
if shutil.which('node'):
    orders = [dict(side='yes', strike=224.5, price_c=63, count=10, kind='rest', mode='shadow', pnl=3.7, final_total=230),
              dict(side='no', strike=228.5, price_c=42, count=10, kind='rest', mode='shadow', pnl=-4.2, final_total=230),
              dict(side='yes', strike=224.5, price_c=63, count=10, kind='take', mode='shadow', pnl=3.53, final_total=230),
              dict(side='yes', strike=224.5, price_c=63, count=10, filled_count=4, kind='rest', mode='live', pnl=1.48, final_total=230),
              dict(side='no', strike=140.5, price_c=47, count=37, kind='rest', mode='shadow', pnl=None, final_total=None),
              dict(side='no', strike=140.5, price_c=47, count=37, kind='rest', mode='shadow', pnl=19.61, final_total=None)]
    prices = [0.5, 0.63, 0.15, 0.85, 0.47]
    script = ("import { feePer, orderFee, fillPnl } from '%s/app/lib/desk.js';\n" % ROOT.replace('\\', '/')
              + 'const out = { fees: [], pnl: [] };\n'
              + 'for (const p of %s) out.fees.push([feePer(p), feePer(p, "rest"), orderFee(37, p), orderFee(37, p, "rest"), orderFee(1, p, "rest")]);\n' % json.dumps(prices)
              + 'for (const o of %s) out.pnl.push(fillPnl(o));\n' % json.dumps(orders)
              + 'console.log(JSON.stringify(out));\n')
    tmp = os.path.join(tempfile.mkdtemp(), 'fee_check.mjs')
    open(tmp, 'w').write(script)
    got = json.loads(subprocess.run(['node', '--no-warnings', tmp], capture_output=True, text=True, check=True).stdout.strip())
    for p, g in zip(prices, got['fees']):
        want = [engine.fee_per(p), engine.fee_per(p, 'maker'), engine.order_fee(37, p), engine.order_fee(37, p, 'maker'), engine.order_fee(1, p, 'maker')]
        assert all(abs(a - b) < 1e-9 for a, b in zip(g, want)), (p, g, want)
    assert got['pnl'] == [trade.net_pnl(o) for o in orders] == [3.65, -4.25, 3.53, 1.48, None, 19.61], got['pnl']   # the live row's own pnl stands
    print('fees: the app charges the same fees and grades a fill the same way')
else:
    print('fees: node not found, app fee parity skipped')

pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': (pushes.append((title, body, priority)) or ['test'])
store.enabled = lambda: False
cfg = watch.load_json(watch.CONFIG_PATH, {})
fx = tempfile.mkdtemp()
def put(series, fee_type='quadratic_with_maker_fees', mult=1):
    json.dump({'series': {'ticker': series, 'fee_type': fee_type, 'fee_multiplier': mult}}, open(os.path.join(fx, f'kalshi_series_{series}.json'), 'w'))
ALL = ['KXNFLTOTAL', 'KXNCAAFTOTAL', 'KXNBATOTAL', 'KXNCAAMBTOTAL']
for s in ALL:
    put(s)

# 2. the record the engine prices (maker fees, multiplier 1): nothing pushed
d = watch.Desk(cfg, {}, fx)
assert d.fee_check() == [] and not pushes
fees = d.state['fees']
assert set(fees) == set(ALL) and all(f['fee_type'] == 'quadratic_with_maker_fees' and f['fee_multiplier'] == 1.0 and f['alerted'] is None for f in fees.values()), fees
assert d.fee_check() == [] and not pushes
print('fees: the record the engine prices says nothing')

# 3. Kalshi charges more than the desk counts (the multiplier doubles): one loud push with both numbers; never twice
put('KXNBATOTAL', 'quadratic_with_maker_fees', 2)
out = d.fee_check()
assert out == ['FEES: KXNBATOTAL reads quadratic_with_maker_fees'] and len(pushes) == 1, (out, pushes)
title, body, pri = pushes[0]
assert pri == 'high' and 'fee_type quadratic_with_maker_fees, multiplier 2.' in body and '3.50c a share to take and 0.88c to rest; the desk counts 1.75c and 0.44c' in body, body
assert 'too high by the difference' in body and 'Skip its orders' in body, body
assert chr(8212) not in body and chr(8212) not in title
assert d.fee_check() == [] and len(pushes) == 1, 'the same record must not be pushed twice'
assert all(d.state['fees'][s]['alerted'] is None for s in ALL if s != 'KXNBATOTAL')
# back to the priced record: one all-clear naming the series, then quiet
put('KXNBATOTAL')
out = d.fee_check()
assert out == ['FEES: priced in'] and len(pushes) == 2 and pushes[1][2] == 'default' and 'KXNBATOTAL' in pushes[1][1] and 'KXNFLTOTAL' not in pushes[1][1], pushes[1]
assert d.state['fees']['KXNBATOTAL']['alerted'] is None and d.fee_check() == [] and len(pushes) == 2
print('fees: a fee the desk does not count is pushed once, loud, and cleared once')

# 4. Kalshi charges less than the desk counts (a series drops the maker fee, or carries it on combos only): quiet, once
put('KXNFLTOTAL', 'quadratic', 1)
n = len(pushes)
assert d.fee_check() == ['FEES: KXNFLTOTAL reads quadratic'] and len(pushes) == n + 1, pushes[-1]
title, body, pri = pushes[-1]
assert pri == 'default' and '1.75c a share to take and 0.00c to rest; the desk counts 1.75c and 0.44c' in body and 'a touch low' in body and 'Safe to keep betting' in body, body
assert d.fee_check() == [] and len(pushes) == n + 1
put('KXNFLTOTAL', 'quadratic_with_combo_maker_fees', 1)
assert d.fee_check() == ['FEES: KXNFLTOTAL reads quadratic_with_combo_maker_fees'] and pushes[-1][2] == 'default' and '0.00c to rest' in pushes[-1][1]
put('KXNFLTOTAL')
assert d.fee_check() == ['FEES: priced in'] and 'KXNFLTOTAL' in pushes[-1][1]
print('fees: a series that charges less than the desk counts is pushed once, quietly')

# 5. a fee table the desk cannot price (flat, or a record with no multiplier): loud
d3 = watch.Desk(dict(cfg, sports=['cfb']), {}, fx)
put('KXNCAAFTOTAL', 'flat', 1)
n = len(pushes)
assert d3.fee_check() == ['FEES: KXNCAAFTOTAL reads flat'] and len(pushes) == n + 1 and pushes[-1][2] == 'high' and 'not a fee table the desk knows how to price' in pushes[-1][1], pushes[-1]
assert set(d3.state['fees']) == {'KXNCAAFTOTAL'}, 'only the sports in config are read'
json.dump({'series': {'ticker': 'KXNCAAFTOTAL', 'fee_type': 'quadratic_with_maker_fees'}}, open(os.path.join(fx, 'kalshi_series_KXNCAAFTOTAL.json'), 'w'))
assert d3.fee_check() == ['FEES: KXNCAAFTOTAL reads quadratic_with_maker_fees'] and pushes[-1][2] == 'high' and 'multiplier n/a' in pushes[-1][1], pushes[-1]
put('KXNCAAFTOTAL')

# 6. the state the live worker held on Nov 12: every series pushed as maker fees the desk did not price yet (and a
# baseline key the old watch kept). The first check on the new engine sends one all-clear for all four, then nothing.
live = {s: dict(fee_type='quadratic_with_maker_fees', fee_multiplier=1.0, base=None, checked='2026-11-12T20:06:00+00:00', alerted='quadratic_with_maker_fees|1.0') for s in ALL}
d4 = watch.Desk(cfg, dict(fees=copy.deepcopy(live)), fx)
n = len(pushes)
assert d4.fee_check() == ['FEES: priced in'] and len(pushes) == n + 1
title, body, pri = pushes[-1]
assert pri == 'default' and all(s in body for s in ALL) and '1.75% when a resting order fills (0.44c a share at 50c)' in body and 'Nothing to skip' in body, body
assert chr(8212) not in body
assert all(f['alerted'] is None and 'base' not in f for f in d4.state['fees'].values()), d4.state['fees']
assert d4.fee_check() == [] and len(pushes) == n + 1
print('fees: the Nov 12 alerts clear with one push')

# 7. a series that cannot be read teaches nothing and changes nothing
os.remove(os.path.join(fx, 'kalshi_series_KXNFLTOTAL.json'))
before = copy.deepcopy(d.state['fees']['KXNFLTOTAL'])
n = len(pushes)
assert d.fee_check() == [] and len(pushes) == n and d.state['fees']['KXNFLTOTAL'] == before
json.dump({'series': {'ticker': 'KXNFLTOTAL'}}, open(os.path.join(fx, 'kalshi_series_KXNFLTOTAL.json'), 'w'))     # a record with no fee_type
assert d.fee_check() == [] and d.state['fees']['KXNFLTOTAL'] == before
# off the fixtures the reader swallows a failed request and returns {}
assert feeds.kalshi_series('KXNFLTOTAL') == {}, 'a failed read must come back empty, never raise'
off = watch.Desk(dict(cfg, sports=['nfl']), {}, None)
assert off.fee_check() == [] and not off.state.get('fees'), 'nothing read, nothing stored'
print('fees: an unreadable record changes nothing')

# 8. the worker asks every six hours, inside a try
src = open(os.path.join(ROOT, 'worker.py')).read()
assert worker.FEE_CHECK == 6 * 3600 and 'desk.fee_check()' in src and "print(f'fee check failed: {e}', flush=True)" in src
assert 'if wait != FAST and time.time() - last_fees > FEE_CHECK:' in src, 'the fee read must never run around a break'
print('fees: ok')
