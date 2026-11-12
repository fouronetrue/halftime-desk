"""The spot lane (Nov 7, claude/scorecard-readout-nov07.md; re-measured Nov 12, claude/go-live-nov12.md): cells of
the halftime study whose second half runs over or under the desk's own blended number. A live cell's lean moves
the blended mean and the ladder with it, and its side is priced at the model's full weight (tests/lanes.py has the
play); a shadow cell is named on the push and kept on the sheet, never applied.
config spots.<sport>.<cell>: {lean, mode, stake, note}."""
import sys, os, copy, json, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, feeds, store, notify, engine

cfg0 = watch.load_json(watch.CONFIG_PATH, {})
spots = cfg0.get('spots') or {}
nfl_cell = (spots.get('nfl') or {}).get('home_fav_trailing', {})
assert nfl_cell.get('mode') == 'live' and nfl_cell.get('stake') == 0.5 and nfl_cell.get('note'), 'config.json: the NFL trailing-home-favorite cell is live at half size, with its record in a line'
assert set(spots.get('cfb') or {}) == {'fav_leading_1_7', 'hot_first_half'}, 'config.json: the college cells of the Nov 12 re-measure (the old trailing 1-7 cell was a spread-sign artifact)'
assert all(v.get('mode') == 'shadow' for sp in ('cfb', 'cbb') for v in (spots.get(sp) or {}).values()), 'config.json: the college cells stay in shadow until the rows earn them'
assert (spots.get('cbb') or {}).get('mismatch_hanging', {}).get('lean') == -1.0, 'config.json: the college basketball mismatch cell leans under'
assert (cfg0.get('auto') or {}).get('mode') == 'shadow' and set((cfg0.get('auto') or {}).get('sports') or []) >= {'nba', 'nfl', 'cfb', 'cbb'}, 'config.json: the shadow fill model runs on every sport'

# 1. the cells
sp = engine.spot_lane('nfl', spots, 44.5, -3.5, 7, 13)        # home favorite by 3.5, trailing 7-13
assert sp and sp['name'] == 'home_fav_trailing' and sp['mode'] == 'live' and sp['lean'] == 1.5, sp
assert sp['side'] == 'over' and sp['stake'] == 0.5 and sp['note'].startswith("58% over the book's 2H line since 2023 (104 of 179)"), sp
assert engine.spot_lane('nfl', spots, 44.5, -3.5, 13, 7) is None, 'the favorite leading is no cell'
assert engine.spot_lane('nfl', spots, 44.5, 3.5, 7, 13) is None, 'a home dog trailing is no cell'
assert engine.spot_lane('nfl', spots, 44.5, None, 7, 13) is None, 'no spread, no cell'
sp = engine.spot_lane('cfb', spots, 55.5, -7, 17, 14)          # home favorite leading by 3
assert sp and sp['name'] == 'fav_leading_1_7' and sp['mode'] == 'shadow' and sp['lean'] == 1.1 and sp['side'] == 'over' and sp['stake'] == 1.0 and sp['note'] is None, sp
sp = engine.spot_lane('cfb', spots, 55.5, 7, 14, 17)           # the road favorite leading by 3: the same cell
assert sp and sp['name'] == 'fav_leading_1_7', sp
assert engine.spot_lane('cfb', spots, 55.5, -7, 22, 14) is None, 'leading by 8 is outside the 1-7 cell'
assert engine.spot_lane('cfb', spots, 55.5, -7, 14, 14) is None, 'tied is no cell'
assert engine.spot_lane('cfb', spots, 55.5, -7, 10, 14) is None, 'the favorite trailing by 4 is no cell: that one was the spread-sign artifact'
assert engine.spot_lane('cfb', spots, 55.5, 0, 17, 14) is None and engine.spot_lane('cfb', spots, 55.5, None, 17, 14) is None, 'a pick or no spread names no favorite'
sp = engine.spot_lane('cfb', spots, 50.5, 3, 24, 17)           # 41 at the half against a 50.5 total: 15.75 over the pace (the road favorite trails)
assert sp and sp['name'] == 'hot_first_half' and sp['mode'] == 'shadow' and sp['lean'] == 1.0, sp
assert engine.spot_lane('cfb', spots, 50.5, 3, 20, 14) is None, '34 at the half is not 10 over the pace'
sp = engine.spot_lane('cbb', spots, 150.5, -17.5, 41, 30)      # a 17.5-point favorite up 11 at the half
assert sp and sp['name'] == 'mismatch_hanging' and sp['mode'] == 'shadow' and sp['lean'] == -1.0 and sp['side'] == 'under', sp
assert engine.spot_lane('cbb', spots, 150.5, 17.5, 33, 30)['name'] == 'mismatch_hanging', 'the road favorite behind at the half is in the cell'
assert engine.spot_lane('cbb', spots, 150.5, -17.5, 45, 30) is None, 'up 15 is away'
assert engine.spot_lane('cbb', spots, 150.5, -14.5, 41, 30) is None, 'a 14.5-point favorite is not a mismatch'
assert engine.spot_lane('cbb', spots, 150.5, None, 41, 30) is None
assert engine.spot_lane('nba', spots, 221.5, -1.5, 50, 58) is None, 'no NBA cells'
assert engine.spot_lane('nfl', {'nfl': {'no_such_cell': {'lean': 9, 'mode': 'live'}}}, 44.5, -3.5, 7, 13) is None, 'an unknown cell name is ignored'
# a cell's stake is clamped to 0..1 (a lane never sizes past the desk's own stake), and a bad value means full
assert engine.spot_lane('nfl', {'nfl': {'home_fav_trailing': {'lean': 1.5, 'mode': 'live', 'stake': 3}}}, 44.5, -3.5, 7, 13)['stake'] == 1.0
assert engine.spot_lane('nfl', {'nfl': {'home_fav_trailing': {'lean': 1.5, 'mode': 'live', 'stake': 'x'}}}, 44.5, -3.5, 7, 13)['stake'] == 1.0
print('spots: the cells')

# 2. the lean moves the blended mean after the blend, and only when applied
m0 = engine.HalfModel('nfl', 44.5, -3.5, 7, 13, center=24.5, center_w=0.5)
m1 = engine.HalfModel('nfl', 44.5, -3.5, 7, 13, center=24.5, center_w=0.5, lean=1.5)
assert abs((m1.mu - m0.mu) - 1.5) < 1e-9 and m1.mu_model == m0.mu_model and m1.lean == 1.5 and m0.lean == 0.0, (m0.mu, m1.mu)
assert m1.p_over_2h(24.5) > m0.p_over_2h(24.5), 'the over gets likelier'
assert engine.fair_line(m1) >= engine.fair_line(m0)
print('spots: the lean lands after the blend')

# 3. the push names the lane
inp = dict(away='BUF', home='LAR', h1a=13, h1h=7, spot_lane=dict(name='home_fav_trailing', label='home favorite trailing', lean=1.5, mode='live'))
rows = engine.price_lines(m1, [42.5, 45.5, 48.5], 'fg', 0.03)
sug = engine.suggest(rows, {42.5: dict(y=60, n=42), 45.5: dict(y=50, n=52), 48.5: dict(y=40, n=62)}, 'taker', 0.03, 0.5, 3000, 75, 225, (15, 85), None, single_band=(40, 85))
kind, head, text = engine.order_sheet(m1, inp, rows, sug, dict(margin=0.03, bankroll=3000, max_risk=75, max_cost=225))
assert text.splitlines()[0].endswith('Spot: home favorite trailing, +1.5 on the number.'), text.splitlines()[0]
inp['spot_lane'] = dict(name='fav_leading_1_7', label='favorite leading by 1-7', lean=1.1, mode='shadow')
kind, head, text = engine.order_sheet(m1, inp, rows, sug, dict(margin=0.03, bankroll=3000, max_risk=75, max_cost=225))
assert text.splitlines()[0].endswith('Spot (watch): favorite leading by 1-7, would be +1.1.'), text.splitlines()[0]
inp['spot_lane'] = engine.spot_lane('cbb', spots, 150.5, -17.5, 41, 30)
kind, head, text = engine.order_sheet(m1, inp, rows, sug, dict(margin=0.03, bankroll=3000, max_risk=75, max_cost=225))
assert text.splitlines()[0].endswith('Spot (watch): 15+ point favorite not up by 15, would be -1.0.'), text.splitlines()[0]
assert 'Spot play' not in text, 'a shadow cell never claims a play'
inp['spot_lane'] = None
kind, head, text = engine.order_sheet(m1, inp, rows, sug, dict(margin=0.03, bankroll=3000, max_risk=75, max_cost=225))
assert 'Spot' not in text.splitlines()[0]
print('spots: the push names the lane')

# 4. the desk on the NFL fixture (BUF 13 @ LAR 7, LAR -3.5: the live cell): the sheet carries the lane and the lean, the grade marks it
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
sh = rec.get('sheet') or rec.get('play_sheet')
assert rec.get('spot_lane', {}).get('name') == 'home_fav_trailing' and sh and sh['spot_lane']['mode'] == 'live' and sh['lean'] == 1.5, (rec.get('spot_lane'), sh and sh.get('lean'))
half = [p for p in pushes if '(half' in p[0]]
assert len(half) == 1 and 'Spot: home favorite trailing, +1.5 on the number.' in half[0][1].splitlines()[0], half
assert sh['stake'] == cfg0['stake_scale'] and all('fair_c' in x and 'edge_c' in x for x in sh['singles']), 'the sheet keeps the stake and what each single claimed'
gr = watch.grade_sheet(sh, 51)
assert 'spot home_fav_trailing +1.5 live' in gr['detail'], gr['detail']
# the same half with the lane off: the fair sits lower by the lean
d0 = watch.Desk(dict(cfg, spots={}), {}, FIX)
d0.run_pass()
sh0 = d0.state['games']['401'].get('sheet') or d0.state['games']['401'].get('play_sheet')
assert sh0 and sh0.get('spot_lane') is None and sh0['lean'] == 0 and abs((sh['mu'] - sh0['mu']) - 1.5) < 0.02, (sh['mu'], sh0['mu'])
print('spots: the NFL fixture half sits in the live cell, the sheet and the grade carry it')
print('spots: ok')
