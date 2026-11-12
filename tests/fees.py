"""The fee watch (Nov 12). The engine prices a take at 7% x P x (1 - P) and a resting fill at no fee, which is what
Kalshi's fee schedule of July 7, 2026 says for the total series: maker fees are charged only on the series the
schedule lists (the game-winner series among them, no total series). watch.Desk.fee_check reads Kalshi's own
record of each total series the desk prices and pushes once when a series moves onto maker fees, reads as anything
but the general table, or changes from the first clean read. It tells the phone; it does not reprice anything.
No network."""
import sys, os, json, copy, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, feeds, notify, store, engine, worker

import requests
def boom(*a, **k):
    raise AssertionError('network call attempted')
requests.get = requests.post = requests.request = boom

# what the engine is built on
assert engine.FEE_RATE == 0.07 and abs(engine.fee_per(0.5) - 0.0175) < 1e-12 and engine.fee_per(0.5, 'maker') == 0.0 and engine.order_fee(100, 0.5, 'maker') == 0.0
assert set(feeds.SERIES[s]['total'] for s in ('nfl', 'cfb', 'nba', 'cbb')) == {'KXNFLTOTAL', 'KXNCAAFTOTAL', 'KXNBATOTAL', 'KXNCAAMBTOTAL'}

pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': (pushes.append((title, body, priority)) or ['test'])
store.enabled = lambda: False
cfg = watch.load_json(watch.CONFIG_PATH, {})
fx = tempfile.mkdtemp()
def put(series, fee_type='quadratic', mult=1):
    json.dump({'series': {'ticker': series, 'fee_type': fee_type, 'fee_multiplier': mult}}, open(os.path.join(fx, f'kalshi_series_{series}.json'), 'w'))
ALL = ['KXNFLTOTAL', 'KXNCAAFTOTAL', 'KXNBATOTAL', 'KXNCAAMBTOTAL']
for s in ALL:
    put(s)

# 1. the record the engine expects: nothing pushed, the first clean read kept as the baseline
d = watch.Desk(cfg, {}, fx)
assert d.fee_check() == [] and not pushes
fees = d.state['fees']
assert set(fees) == set(ALL) and all(f['fee_type'] == 'quadratic' and f['fee_multiplier'] == 1.0 and f['base'] == dict(fee_type='quadratic', fee_multiplier=1.0) and f['alerted'] is None for f in fees.values()), fees
assert d.fee_check() == [] and not pushes
print('fees: a clean read is the baseline, and says nothing')

# 2. a total series moves onto maker fees: one push, high priority, with what it costs; never twice
put('KXNBATOTAL', 'quadratic_with_maker_fees', 1)
out = d.fee_check()
assert out == ['FEES: KXNBATOTAL is now quadratic_with_maker_fees'] and len(pushes) == 1, (out, pushes)
title, body, pri = pushes[0]
assert pri == 'high' and 'fee_type quadratic_with_maker_fees, multiplier 1.0 (it was quadratic, 1.0)' in body and 'about 0.44c a share' in body and 'every REST limit is that much too high' in body, body
assert chr(8212) not in body and chr(8212) not in title
assert d.fee_check() == [] and len(pushes) == 1, 'the same record must not be pushed twice'
assert d.state['fees']['KXNBATOTAL']['base'] == dict(fee_type='quadratic', fee_multiplier=1.0), 'the baseline stays the first clean read'
assert all(d.state['fees'][s]['alerted'] is None for s in ALL if s != 'KXNBATOTAL')
# back to the baseline: quiet, and the next move is news again
put('KXNBATOTAL')
assert d.fee_check() == [] and len(pushes) == 1 and d.state['fees']['KXNBATOTAL']['alerted'] is None
put('KXNBATOTAL', 'quadratic_with_maker_fees', 2)
assert d.fee_check() == ['FEES: KXNBATOTAL is now quadratic_with_maker_fees'] and len(pushes) == 2 and 'about 0.88c a share' in pushes[1][1], pushes[-1]
put('KXNBATOTAL')
d.fee_check()
print('fees: maker fees on a total series are pushed once, with the cost of a resting fill')

# 3. the record changes without maker fees (a different multiplier): pushed once, as a thing to check
put('KXNFLTOTAL', 'quadratic', 2)
n = len(pushes)
assert d.fee_check() == ['FEES: KXNFLTOTAL is now quadratic'] and len(pushes) == n + 1 and 'Check the fee schedule before the next slate.' in pushes[-1][1] and '(it was quadratic, 1.0)' in pushes[-1][1], pushes[-1]
assert d.fee_check() == [] and len(pushes) == n + 1
put('KXNFLTOTAL')
print('fees: any other change from the baseline is pushed once')

# 4. a first read that already carries maker fees has no clean baseline, and is still pushed
d2 = watch.Desk(dict(cfg, sports=['cbb']), {}, fx)
put('KXNCAAMBTOTAL', 'quadratic_with_maker_fees', 1)
n = len(pushes)
assert d2.fee_check() == ['FEES: KXNCAAMBTOTAL is now quadratic_with_maker_fees'] and len(pushes) == n + 1 and '(it was' not in pushes[-1][1]
assert d2.state['fees']['KXNCAAMBTOTAL']['base'] is None and set(d2.state['fees']) == {'KXNCAAMBTOTAL'}, 'only the sports in config are read'
put('KXNCAAMBTOTAL')
assert d2.fee_check() == [] and d2.state['fees']['KXNCAAMBTOTAL']['base'] == dict(fee_type='quadratic', fee_multiplier=1.0), 'the first clean read becomes the baseline'

# 4b. the combo variant prices a single market like the general table (its maker fee is on combos, which the desk
# never trades): a clean first read. A flat-fee series is not what the engine prices: pushed, even on a first read.
d3 = watch.Desk(dict(cfg, sports=['cfb']), {}, fx)
put('KXNCAAFTOTAL', 'quadratic_with_combo_maker_fees', 1)
n = len(pushes)
assert d3.fee_check() == [] and len(pushes) == n and d3.state['fees']['KXNCAAFTOTAL']['base'] == dict(fee_type='quadratic_with_combo_maker_fees', fee_multiplier=1.0)
put('KXNCAAFTOTAL', 'flat', 1)
assert d3.fee_check() == ['FEES: KXNCAAFTOTAL is now flat'] and 'Check the fee schedule before the next slate.' in pushes[-1][1] and 'REST limit' not in pushes[-1][1], pushes[-1]
d4 = watch.Desk(dict(cfg, sports=['cfb']), {}, fx)
assert d4.fee_check() == ['FEES: KXNCAAFTOTAL is now flat'] and d4.state['fees']['KXNCAAFTOTAL']['base'] is None
put('KXNCAAFTOTAL')

# 5. a series that cannot be read teaches nothing and changes nothing
os.remove(os.path.join(fx, 'kalshi_series_KXNFLTOTAL.json'))
before = copy.deepcopy(d.state['fees']['KXNFLTOTAL'])
n = len(pushes)
assert d.fee_check() == [] and len(pushes) == n and d.state['fees']['KXNFLTOTAL'] == before
json.dump({'series': {'ticker': 'KXNFLTOTAL'}}, open(os.path.join(fx, 'kalshi_series_KXNFLTOTAL.json'), 'w'))     # a record with no fee_type
assert d.fee_check() == [] and d.state['fees']['KXNFLTOTAL'] == before
# off the fixtures the reader swallows a failed request and returns {}
assert feeds.kalshi_series('KXNFLTOTAL') == {}, 'a failed read must come back empty, never raise'
live = watch.Desk(dict(cfg, sports=['nfl']), {}, None)
assert live.fee_check() == [] and not live.state.get('fees'), 'nothing read, nothing stored'
print('fees: an unreadable record changes nothing')

# 6. the worker asks every six hours, inside a try
src = open(os.path.join(ROOT, 'worker.py')).read()
assert worker.FEE_CHECK == 6 * 3600 and 'desk.fee_check()' in src and "print(f'fee check failed: {e}', flush=True)" in src
assert 'if wait != FAST and time.time() - last_fees > FEE_CHECK:' in src, 'the fee read must never run around a break'
print('fees: ok')
