"""The go-live sizing and the live lane's own play (Nov 12, claude/go-live-nov12.md). No network.
1. engine.suggest(lane=...): a single on a live lane's side, inside the lane's band, is scored at the model's full
   weight (the rows already carry the lane's lean). It carries lane=<cell>, is sized at the cell's own stake (a
   share of full size, whatever the desk's stake is), and leaves the legs the pairs use on their blended numbers.
   The other side, a price outside the band, a shadow cell and a missing lane change nothing. A cell with stake 0
   keeps its lean and calls no play.
2. stake scales the budget of singles on price (config stake_scale) after the risk cap, so half stake is half the
   size at any price and never more than half the cap; at 0 the plays on price are off and a live lane is
   untouched; middles are sized by their loss cap and do not move.
3. edge_cap: a claimed edge past the cap buys no more size than the cap.
4. The cancel rule on the push: a resting order comes down when play resumes, in every sport and window.
5. The desk on the NFL fixture (Bills 13 at Rams 7, Rams -3.5: the live cell) under config.json: one PLAY, the
   lane's over, at a quarter of full size (the cell's stake), named on the push with the lane's record, kept on
   the sheet, graded with the lane tag, charged to the day cap. With the cell in shadow the same half is a read.
6. A live resting order never outlives the break (trade.py), whatever rest_until says."""
import sys, os, copy, json, tempfile, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, feeds, store, notify, engine, trade

cfg0 = watch.load_json(watch.CONFIG_PATH, {})
assert cfg0.get('stake_scale') == 0.5 and cfg0.get('edge_cap_c') == 6 and cfg0.get('lane_band_c') == [40, 60], 'config.json: half stake, a 6c edge cap, lane singles at 40 to 60c'
# the rules that do not change without a reason are where they were
assert (cfg0['margin_c'], cfg0['min_price_c'], cfg0['max_price_c'], cfg0['risk_pct'], cfg0['cost_pct'], cfg0['day_cost_pct'], cfg0['trust_pct'], cfg0['single_min_price_c']) == (3, 15, 85, 2.5, 7.5, 20, 50, 40)
assert watch.DEFAULTS['stake_scale'] == 1.0 and watch.DEFAULTS['edge_cap_c'] is None and watch.DEFAULTS['lane_band_c'] == [40, 60], 'a config without the keys sizes the way it always did'

# 1. the lane's own single
BANK, RISK, COST = 3000, 75, 225
m = engine.HalfModel('nfl', 44.5, -3.5, 7, 13, center=24.5, center_w=0.5, lean=1.5)     # home favorite down 7-13, the lean applied
lines = [42.5, 45.5, 48.5]
# Kalshi's ladder sits about a point and a half under the desk's number: over 42.5 (model 60%) asks 52c, over 45.5
# (model 47%) asks 41c. Against the model alone both clear; halved against Kalshi's own price neither does.
quotes = {42.5: dict(y=52, n=50), 45.5: dict(y=41, n=61), 48.5: dict(y=31, n=71)}
lane = dict(engine.spot_lane('nfl', cfg0['spots'], 44.5, -3.5, 7, 13), band=(40, 60))
assert lane['side'] == 'over' and lane['stake'] == 0.25 and lane['mode'] == 'live'

def sug_of(risk=RISK, **kw):
    rows = engine.price_lines(m, lines, 'fg', 0.03)
    return rows, engine.suggest(rows, copy.deepcopy(quotes), 'taker', 0.03, 0.5, BANK, risk, COST, (15, 85), None, single_band=(40, 85), **kw)

rows0, plain = sug_of()
assert not [s for s in plain['singles'] if s['ok']], 'halved against Kalshi, nothing clears: the lane named a spot and never called a play'
rows1, laned = sug_of(lane=lane)
ok = [s for s in laned['singles'] if s['ok']]
assert ok and all(s['kind'] == 'over' and s['lane'] == 'home_fav_trailing' and 40 <= s['price_c'] <= 60 for s in ok), ok
for s in ok:
    assert s['fair_used'] == s['fair_model'] and abs(s['edge'] - (s['fair_model'] - s['eff'])) < 1e-12 and s['edge'] >= 0.03, s
    base = next(x for x in plain['singles'] if x['kind'] == 'over' and x['line'] == s['line'])
    assert base['edge'] < 0.03 <= s['edge'] and base['fair_used'] < s['fair_used'], 'the same leg, blended, did not clear'
assert not [s for s in laned['singles'] if s['kind'] == 'under' and (s['ok'] or s.get('lane'))], 'the lane only prices its own side'
# the pairs still run on the blended numbers: same middles with or without the lane
key = lambda x: (x['a']['line'], x['b']['line'], x['ok'], x['pairs'], round(x['ev'], 6))
assert [key(x) for x in plain['mids']] == [key(x) for x in laned['mids']], 'the lane moved a middle'
assert all(abs(a['used_over'] - b['used_over']) < 1e-12 for a, b in zip(rows0, rows1)), 'the lane moved the blended ladder'
# the cell's stake: the same play at full lane stake is four times the size (to the contract), cap or no cap, and
# a quarter-stake lane play never risks more than a quarter of the risk cap
for risk in (10**6, RISK):
    _, qtr = sug_of(risk=risk, lane=lane)
    _, full = sug_of(risk=risk, lane=dict(lane, stake=1.0))
    for a, b in zip([s for s in qtr['singles'] if s['ok']], [s for s in full['singles'] if s['ok']]):
        assert a['line'] == b['line'] and abs(4 * a['contracts'] - b['contracts']) <= 3 and a['contracts'] > 0, (a['contracts'], b['contracts'])
_, capped_full = sug_of(lane=dict(lane, stake=1.0))
assert all(s['cost'] <= RISK + 1 for s in capped_full['singles'] if s['ok']) and all(s['cost'] <= RISK / 4 + 1 for s in ok)
assert any(s['cost'] > RISK - 2 for s in capped_full['singles'] if s['ok']), 'the scenario should hit the risk cap at full stake'
# the lane is its own tier: the desk's stake does not move it, and with the plays on price off (stake 0) it still plays
for st in (1.0, 0.5, 0.0):
    _, x = sug_of(lane=lane, stake=st)
    assert [(s['line'], s['contracts']) for s in x['singles'] if s['ok']] == [(s['line'], s['contracts']) for s in ok], st
# a cell with stake 0 keeps its lean on the ladder and calls no play of its own
_, lean_only = sug_of(lane=dict(lane, stake=0))
assert not [s for s in lean_only['singles'] if s['ok'] or s.get('lane')]
# outside the band the lane does nothing: the same over at 39c or 61c is not the lane's play
far = {39.5: dict(y=62, n=40), 45.5: dict(y=39, n=63)}
rows = engine.price_lines(m, list(far), 'fg', 0.03)
out = engine.suggest(rows, far, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), None, single_band=(40, 85), lane=lane)
overs = [s for s in out['singles'] if s['kind'] == 'over']
assert len(overs) == 2 and all(s['fair_model'] - s['eff'] >= 0.03 for s in overs), 'both overs clear against the model alone'
assert not [s for s in out['singles'] if s.get('lane') or s['ok']], 'a lane single outside 40 to 60c'
# the under side of an under lane works the same way, and an over there is left alone
mu_ = engine.HalfModel('cbb', 150.5, -17.5, 41, 30, center=78.0, center_w=0.5, lean=-3.0)
ul = dict(name='mismatch_hanging', label='x', lean=-3.0, mode='live', side='under', stake=1.0, note=None, band=(40, 60))
rows = engine.price_lines(mu_, [146.5, 149.5, 152.5], 'fg', 0.03)
uq = {146.5: dict(y=62, n=40), 149.5: dict(y=52, n=50), 152.5: dict(y=42, n=60)}
out = engine.suggest(rows, uq, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), None, single_band=(40, 85), lane=ul)
tagged = [s for s in out['singles'] if s.get('lane')]
assert tagged and all(s['kind'] == 'under' and s['ok'] for s in tagged), tagged
# a lane with no side (a bad dict) is ignored
rows = engine.price_lines(m, lines, 'fg', 0.03)
out = engine.suggest(rows, copy.deepcopy(quotes), 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), None, single_band=(40, 85), lane=dict(name='x', band=(40, 60)))
assert not [s for s in out['singles'] if s['ok'] or s.get('lane')]
print(f"lane: {len(ok)} over single(s) at the model's full weight, sized at the cell's stake; the other side, the pairs and the blended ladder untouched")

# 2. the stake
m2 = engine.HalfModel('nfl', 44.5, -3.5, 14, 10)
rows = engine.price_lines(m2, [40.5, 43.5, 46.5, 49.5], 'fg', 0.03)
cheap = {r['line']: dict(y=max(1, int(100 * r['p_over']) - 12), n=max(1, int(100 * r['p_under']) - 12)) for r in rows}   # every side 12c under the model
big = lambda **kw: engine.suggest(engine.price_lines(m2, [40.5, 43.5, 46.5, 49.5], 'fg', 0.03), copy.deepcopy(cheap), 'taker', 0.03, 1.0, 100000, 10**6, 10**6, (15, 85), None, single_band=(40, 85), **kw)
s1, s5 = big(), big(stake=0.5)
pairs = [(a, b) for a, b in zip(s1['singles'], s5['singles']) if a['ok']]
assert pairs and all(a['line'] == b['line'] and a['kind'] == b['kind'] and b['ok'] and abs(a['contracts'] - 2 * b['contracts']) <= 1 for a, b in pairs), 'half stake is half the contracts'
assert [(x['a']['line'], x['b']['line'], x['pairs']) for x in s1['mids']] == [(x['a']['line'], x['b']['line'], x['pairs']) for x in s5['mids']], 'a middle is sized by its loss cap, not the stake'
# the stake comes off after the cap: where the risk cap binds at full stake (every play here), half stake is half
# the cap, not the cap again. Before this a pricey favorite stayed at full size at "half stake".
capped = lambda **kw: engine.suggest(engine.price_lines(m2, [40.5, 43.5, 46.5, 49.5], 'fg', 0.03), copy.deepcopy(cheap), 'taker', 0.03, 1.0, 100000, 75, 225, (15, 85), None, single_band=(40, 85), **kw)
c1, c5 = capped(), capped(stake=0.5)
ok1 = [(a, b) for a, b in zip(c1['singles'], c5['singles']) if a['ok']]
assert ok1 and all(74 < a['cost'] <= 75 + 1 and b['cost'] <= 37.5 + 1 and abs(a['contracts'] - 2 * b['contracts']) <= 1 for a, b in ok1), [(a['cost'], b['cost']) for a, b in ok1]
first_ok = lambda sug: next(s for s in sug['singles'] if s['ok'])
assert first_ok(s1)['contracts'] > 0 and first_ok(big(stake=None))['contracts'] == first_ok(s1)['contracts'], 'no stake given is full stake'
# stake 0 switches the plays on price off: every line is still on the row with its edge, none is a play
off = big(stake=0)
assert not [s for s in off['singles'] if s['ok'] or s['contracts']] and [round(s['edge'], 9) for s in off['singles']] == [round(s['edge'], 9) for s in s1['singles']]
assert not [r for r in off.get('revs') or [] if r['ok']] and [(x['a']['line'], x['b']['line'], x['pairs']) for x in off['mids']] == [(x['a']['line'], x['b']['line'], x['pairs']) for x in s1['mids']]
print('stake: half stake is half the contracts on every single, at half the cap where the cap binds; middles unmoved')

# 3. the edge cap
top = first_ok(s1)
assert top['edge'] > 0.06, top['edge']
sc = next(x for x in big(edge_cap=0.06)['singles'] if x['line'] == top['line'] and x['kind'] == top['kind'])
p, eff = top['price_c'] / 100, top['eff']
want = int(0.25 * 0.06 / (1 - eff) * 100000 / (p + engine.fee_per(p)) + 1e-9)
assert sc['line'] == top['line'] and sc['contracts'] == want < top['contracts'] and sc['edge'] == top['edge'] and sc['ok'], (sc['contracts'], want, top['contracts'])
small = [s for s in s1['singles'] if s['ok'] and s['edge'] <= 0.06]
for s in small:
    t = next(x for x in big(edge_cap=0.06)['singles'] if x['line'] == s['line'] and x['kind'] == s['kind'])
    assert t['contracts'] == s['contracts'], 'an edge under the cap is sized as it was'
print(f"edge cap: a {100 * top['edge']:.0f}c claim is sized as a 6c one ({sc['contracts']} contracts, not {top['contracts']}); the edge on record is the claim")

# 4. the cancel rule
class M:   # the two fields cancel_by reads
    def __init__(self, sport, stage=None): self.sport, self.stage = sport, stage
assert engine.cancel_by(M('nfl')) == engine.cancel_by(M('cfb')) == engine.cancel_by(M('nba')) == 'when the 3rd starts'
assert engine.cancel_by(M('cbb')) == 'when the 2nd half starts' and engine.cancel_by(M('nba', 'q3')) == 'when the 4th starts'
assert engine.rest_head(M('nba')) == 'REST A MIDDLE (cancel unfilled legs when the 3rd starts):'
assert engine.rest_head(M('cbb')) == 'REST A MIDDLE (cancel unfilled legs when the 2nd half starts):'
assert '4th quarter' not in open(os.path.join(ROOT, 'engine.py')).read().split('def cancel_by')[1].split('def rest_head')[0].split('"""')[2], 'the rule itself no longer says the 4th quarter at the half'
print('cancel rule: resting orders come down when play resumes')

# 5. the desk on the NFL fixture
FIX = os.path.join(ROOT, 'tests', 'fixtures')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv'); watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': (pushes.append((title, body, priority)) or ['test'])
captured = {}
store.enabled = lambda: True
store.write = lambda table, rows, on_conflict=None, ignore_duplicates=False: captured.setdefault(table, []).extend(copy.deepcopy(rows)) or True
store.read = lambda table, params: []
store.claim = lambda table, row, on_conflict: True
cfg = dict(cfg0, sports=['nfl'])
d = watch.Desk(cfg, {}, FIX)
d.run_pass()
rec = d.state['games']['401']
sh = rec.get('play_sheet') or rec.get('sheet')
half = [p for p in pushes if '(half' in p[0]]
assert rec['slots'] == {'half': 'play'} and len(half) == 1 and half[0][0] == 'PLAY: Bills 13, Rams 7 (half, NFL)' and half[0][2] == 'high', (rec.get('slots'), half)
body = half[0][1]
L = body.split('\n')
assert L[0].endswith('Spot: home favorite trailing, +1.5 on the number.') and any(l.startswith('Buy OVER ') for l in L), body
note = [l for l in L if l.startswith('Spot play')]
assert note == ["Spot play: 58% over the book's 2H line since 2023 (104 of 179). Quarter size until it earns more."], note
assert not any(l.startswith('Buy UNDER') for l in L)
assert sh['kind'] == 'play' and sh['lead'] == 'single' and sh['stake'] == 0.5 and sh['singles'] and all(x['kind'] == 'over' and x['lane'] == 'home_fav_trailing' and 40 <= x['price_c'] <= 60 for x in sh['singles']), sh['singles']
lead = sh['singles'][0]
assert lead['edge_c'] >= 3 and lead['fair_c'] > lead['price_c'], lead
# a quarter of full size: the same half priced with the cell at stake 1
cfg_full = dict(cfg, stake_scale=1.0, edge_cap_c=None, spots=dict(cfg['spots'], nfl=dict(home_fav_trailing=dict(cfg['spots']['nfl']['home_fav_trailing'], stake=1.0))))
pushes_n = len(pushes)
d1 = watch.Desk(cfg_full, {}, FIX); d1.run_pass()
sh1 = d1.state['games']['401'].get('play_sheet') or d1.state['games']['401'].get('sheet')
lead1 = next(x for x in sh1['singles'] if x['line'] == lead['line'])
pp = lead['price_c'] / 100
eff = pp + engine.fee_per(pp)
cap = cfg['bankroll'] * cfg['risk_pct'] / 100
want = int(min(0.25 * min(0.06, lead1['edge_c'] / 100) / (1 - eff) * cfg['bankroll'], cap) * 0.25 / eff + 1e-9)     # quarter Kelly on at most 6c, under the cap, at the lane's quarter stake
assert lead1['contracts'] > 0 and abs(lead['contracts'] - want) <= 1, (lead['contracts'], want, lead1['contracts'], lead1['edge_c'])
assert lead['cost'] < lead1['cost'] / 3 and lead1['cost'] <= cfg['bankroll'] * cfg['risk_pct'] / 100 + 1
# charged to the day cap, written to the suggestions row, graded with the lane tag
assert rec.get('counted_day') and abs(d.state['day_spend'][rec['date_et'] if 'date_et' in rec else list(d.state['day_spend'])[0]] - lead['cost']) < 0.01, d.state.get('day_spend')
row = captured['suggestions'][0]
assert [s for s in row['singles'] if s.get('lane') == 'home_fav_trailing' and s['ok']], 'the suggestions row carries the lane single'
win, lose = watch.grade_sheet(sh, lead['line'] + 1), watch.grade_sheet(sh, lead['line'] - 1)
assert f"lane over {lead['line']:g}@{lead['price_c']} W" in win['detail'] and win['pnl'] == round(lead['contracts'] - lead['cost'], 2) and win['options'][0]['lane'] == 'home_fav_trailing', win
assert f"lane over {lead['line']:g}@{lead['price_c']} L" in lose['detail'] and lose['pnl'] == -lead['cost'], lose
# with the plays on price switched off (stake_scale 0) the lane still plays, at the same size
d0 = watch.Desk(dict(cfg, stake_scale=0), {}, FIX); d0.run_pass()
sh0 = d0.state['games']['401'].get('play_sheet') or d0.state['games']['401'].get('sheet')
assert d0.stake() == 0.0 and watch.Desk(dict(cfg, stake_scale=None), {}, FIX).stake() == 1.0 and d.stake() == 0.5
assert sh0['kind'] == 'play' and sh0['stake'] == 0 and [(x['line'], x['contracts'], x.get('lane')) for x in sh0['singles']] == [(x['line'], x['contracts'], x.get('lane')) for x in sh['singles']]
# the cell in shadow: named on the push, never applied, never a play
pushes.clear()
cfg_sh = dict(cfg, spots=dict(cfg['spots'], nfl=dict(home_fav_trailing=dict(cfg['spots']['nfl']['home_fav_trailing'], mode='shadow'))))
d2 = watch.Desk(cfg_sh, {}, FIX); d2.run_pass()
rec2 = d2.state['games']['401']
assert rec2['slots'] == {'half': 'read'} and pushes[0][0].startswith('UPDATE') and 'Spot (watch): home favorite trailing, would be +1.5.' in pushes[0][1] and 'Spot play' not in pushes[0][1], pushes[0]
assert not [x for x in (rec2['sheet'].get('singles') or []) if x.get('lane')] and rec2['sheet']['lean'] == 0
print(f"desk: the lane's play, over {lead['line']:g} at {lead['price_c']}c for ${lead['cost']:.0f} (${lead1['cost']:.0f} at full stake), named, kept, graded apart; in shadow the same half is a read")

# 6. a live resting order never outlives the break
import requests
def boom(*a, **k):
    raise AssertionError('network call attempted')
requests.post = requests.request = requests.delete = requests.patch = requests.put = boom
for k in ('TRADE_ENABLED', 'KALSHI_TRADE_KEY_ID', 'KALSHI_TRADE_PRIVATE_KEY'):
    os.environ.pop(k, None)
store.enabled = lambda: False
def planned(mode):
    """The NBA fixture half planned in a mode by an unarmed trader (no key, no TRADE_ENABLED): nothing leaves the test."""
    c = dict(cfg0, sports=['nba'], auto=dict(cfg0['auto'], mode=mode, rest_until='q4'))
    desk = watch.Desk(c, {}, os.path.join(ROOT, 'tests', 'fixtures_nba'))
    desk.trader = trade.Trader(c, desk.cfg['bankroll'])
    assert desk.trader.mode() == mode and not desk.trader.armed()
    seen, plan = [], desk.trader.plan
    def spy(*a, **k):
        orders, note = plan(*a, **k)
        seen.extend(copy.deepcopy(orders))
        return orders, note
    desk.trader.plan = spy
    desk.run_pass()
    a = desk.state['games']['501']['auto']['half']
    assert all(o['status'] in ('planned', 'skipped') for o in a.get('open') or []), 'an unarmed trader sends nothing'
    return [o for o in seen if o['stage'] == 'half'], a
sh_orders, sh_auto = planned('shadow')
lv_orders, lv_auto = planned('live')
start = dt.datetime.fromisoformat(sh_auto['at'])
rest_sh = [o for o in sh_orders if o['kind'] == 'rest']
take_sh = [o for o in sh_orders if o['kind'] == 'take']
rest_lv = [o for o in lv_orders if o['kind'] == 'rest']
assert rest_sh and take_sh and rest_lv, (len(rest_sh), len(take_sh), len(rest_lv))
mins = lambda o, t0: round((dt.datetime.fromisoformat(o['expire_at']) - t0).total_seconds() / 60)
assert {mins(o, start) for o in rest_sh} == {trade.Q4_MIN['half']['nba']} and {mins(o, start) for o in take_sh} == {trade.BREAK_MIN['half']['nba']}, 'shadow rests to the 4th, the measuring window'
assert {mins(o, dt.datetime.fromisoformat(lv_auto['at'])) for o in rest_lv} == {trade.BREAK_MIN['half']['nba']}, 'a live resting order must expire with the break, rest_until q4 or not'
assert {(o['side'], o['strike'], o['price_c']) for o in rest_lv} == {(o['side'], o['strike'], o['price_c']) for o in rest_sh}, 'the same legs at the same limits either way'
print(f"trade: shadow rests {trade.Q4_MIN['half']['nba']} minutes to keep measuring; a live order would expire with the break ({trade.BREAK_MIN['half']['nba']} minutes); nothing sent")
print('lanes: ok')
