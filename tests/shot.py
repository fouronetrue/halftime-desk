"""The mismatch lane (tail study, Oct 24): in a college game with a 28+ point pregame spread the second half is
more predictable than the block says (the ladder's spread runs 0.87 of the model's), so the 80-90c sides there
won 88 percent at an 85c price. In shadow mode the desk logs and shows what a narrowed ladder would take, as a
SHOT line, graded as a what-if; the live desk's numbers do not change. No network: a hand-built fixture set."""
import sys, os, copy, json, shutil, tempfile, csv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, store, notify, feeds, engine

FIX = os.path.join(ROOT, 'tests', 'fixtures')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = watch.load_json(watch.CONFIG_PATH, {})
assert cfg['mismatch']['cfb']['mode'] == 'shadow' and cfg['mismatch']['cfb']['spread'] == 28 and cfg['mismatch']['cfb']['width'] == 0.87 and cfg['mismatch']['cfb']['band_hi'] == 90, cfg['mismatch']
cfg['sports'] = ['cfb']
pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': (pushes.append((title, body)) or ['test'])
captured = {}
store.enabled = lambda: True
store.write = lambda table, rows, on_conflict=None, ignore_duplicates=False: captured.setdefault(table, []).extend(copy.deepcopy(rows)) or True
store.read = lambda table, params: []
store.claim = lambda table, row, on_conflict: True

# a 31-point favorite (Clemson) up 24-3 at the half, total 55.5, with a Kalshi ladder whose unders sit at 80-90c
fx = os.path.join(scratch, 'fx')
os.makedirs(fx)
espn = json.load(open(os.path.join(FIX, 'espn_cfb.json')))
ev = espn['events'][0]
ev['status'] = {'period': 2, 'displayClock': '0:00', 'type': {'state': 'in', 'name': 'STATUS_HALFTIME', 'shortDetail': 'Halftime'}}
for c in ev['competitions'][0]['competitors']:
    c['score'] = '24' if c['homeAway'] == 'home' else '3'
    c['linescores'] = [{'value': 14}, {'value': 10}] if c['homeAway'] == 'home' else [{'value': 0}, {'value': 3}]
json.dump(espn, open(os.path.join(fx, 'espn_cfb.json'), 'w'))
def mk(strike, y, n):
    return {'ticker': f'KXNCAAFTOTAL-26OCT15CHSOCLEM-{int(strike + 0.5)}', 'event_ticker': 'KXNCAAFTOTAL-26OCT15CHSOCLEM', 'title': f'Will there be over {strike} points scored?',
            'floor_strike': strike, 'strike_type': 'greater', 'status': 'active', 'yes_ask_dollars': f'{y / 100:.4f}', 'yes_bid_dollars': f'{(y - 3) / 100:.4f}',
            'no_ask_dollars': f'{n / 100:.4f}', 'no_bid_dollars': f'{(n - 3) / 100:.4f}'}
kal = json.load(open(os.path.join(FIX, 'kalshi_KXNCAAFTOTAL.json')))
kal['events'][0]['markets'] = [mk(45.5, 72, 31), mk(48.5, 60, 43), mk(51.5, 48, 55), mk(54.5, 36, 67), mk(57.5, 26, 77), mk(60.5, 20, 80), mk(63.5, 16, 83)]
json.dump(kal, open(os.path.join(fx, 'kalshi_KXNCAAFTOTAL.json'), 'w'))
json.dump([{'id': ev['id'], 'pre_total': 55.5, 'pre_home_spread': -31.0, 'pre_source': 'espn', 'pre_at': '2026-10-15T20:00:00+00:00'}], open(os.path.join(fx, 'supabase_games.json'), 'w'))
for f in ('kalshi_KXNCAAFSPREAD.json',):
    shutil.copy(os.path.join(FIX, f), fx)

d = watch.Desk(cfg, {}, fx)
d.run_pass()
rec = d.state['games'][ev['id']]
shot = rec.get('shot')
assert shot and shot['mode'] == 'shadow' and shot['spread'] == 31.0 and shot['width'] == 0.87 and shot['band_hi'] == 90, shot
assert shot['picks'], 'the narrowed ladder should find a high-probability under on this ladder'
p = shot['picks'][0]
assert p['kind'] == 'under' and p['price_c'] >= 80 and p['fair_used'] == p['fair_model'] and p['edge'] >= 0.03 and p['fair_model'] > p['fair_live'] and p['fair_kalshi'] is not None, p
assert p['contracts'] > 0 and p['cost'] <= cfg['bankroll'] * cfg['cost_pct'] / 100 + 1, p
print(f"shot: {p['kind']} {p['line']} at {p['price_c']}c, narrowed fair {100 * p['fair_model']:.1f}c, desk {100 * p['fair_live']:.1f}c, {p['contracts']} sh ${p['cost']}")

# the live desk did not change: same mu and sd as a plain HalfModel with the same center, and the push's plays are the desk's own
row = captured['suggestions'][0]
m0 = engine.HalfModel('cfb', 55.5, -31.0, 24, 3, center=row['center'], center_w=0.8 if row['center'] is not None else 1.0)
assert abs(row['sd'] - round(m0.sd, 2)) < 0.011 and abs(row['mu'] - round(m0.mu, 2)) < 0.011, (row['mu'], row['sd'], m0.mu, m0.sd)
assert row.get('shot') == shot and 'weather' in row, 'the suggestions row carries the shot (and the weather key, None for college)'
assert row['weather'] is None
title, body = pushes[0]
L = body.split('\n')
shot_line = [l for l in L if l.startswith('SHOT (shadow, 31-point spread): UNDER')]
assert len(shot_line) == 1 and 'Logged, not a play.' in shot_line[0] and f"at {p['price_c']}c, fair {100 * p['fair_used']:.0f}c (desk says {100 * p['fair_live']:.0f}c)" in shot_line[0], L
assert 'Weather' not in body
# order: the shot line comes after any play lines and before YOU HOLD / the resting middle
idx = L.index(shot_line[0])
assert all(not l.startswith(('REST A MIDDLE', 'YOU HOLD', 'No middle to post')) for l in L[:idx]), L
print('shot: shown on the push, logged on the row, the live desk unchanged')

# graded as a what-if at the final, never part of the play
sheet = rec.get('sheet')
assert sheet and sheet.get('shot') == shot, 'the sheet keeps the shot for grading'
gr_win = watch.grade_sheet(sheet, p['line'] - 1)     # final under the strike: the under wins
gr_lose = watch.grade_sheet(sheet, p['line'] + 1)
assert gr_win['shot_win'] is True and abs(gr_win['shot_pnl'] - (p['contracts'] - p['cost'])) < 0.01 and f"shot under {p['line']:g}@{p['price_c']} W" in gr_win['detail'], gr_win
assert gr_lose['shot_win'] is False and abs(gr_lose['shot_pnl'] + p['cost']) < 0.01 and ' L ' in gr_lose['detail'].split('shot')[-1], gr_lose
assert gr_win['pnl'] == gr_lose['pnl'] or sheet['lead'] != 'rest', 'the shot never moves the play P&L'
print('shot: graded as a what-if')

# not in the lane: a 21-point spread gets no shot; a game in the lane with mode live prices the desk narrowed
json.dump([{'id': ev['id'], 'pre_total': 55.5, 'pre_home_spread': -21.0, 'pre_source': 'espn', 'pre_at': '2026-10-15T20:00:00+00:00'}], open(os.path.join(fx, 'supabase_games.json'), 'w'))
captured.clear(); pushes.clear()
d = watch.Desk(cfg, {}, fx)
d.run_pass()
rec = d.state['games'][ev['id']]
assert not rec.get('shot') and captured['suggestions'][0].get('shot') is None and 'SHOT' not in pushes[0][1]
json.dump([{'id': ev['id'], 'pre_total': 55.5, 'pre_home_spread': -31.0, 'pre_source': 'espn', 'pre_at': '2026-10-15T20:00:00+00:00'}], open(os.path.join(fx, 'supabase_games.json'), 'w'))
cfg2 = copy.deepcopy(cfg); cfg2['mismatch']['cfb']['mode'] = 'live'
captured.clear(); pushes.clear()
d = watch.Desk(cfg2, {}, fx)
d.run_pass()
rec = d.state['games'][ev['id']]
row = captured['suggestions'][0]
assert not rec.get('shot') and 'SHOT' not in pushes[0][1], 'live mode has no shadow line'
assert abs(row['sd'] - round(m0.sd * 0.87, 2)) < 0.011, (row['sd'], m0.sd)
print('shot: 21-point spread stays out; live mode narrows the desk itself')
print('shot: ok')
