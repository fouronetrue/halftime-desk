"""Pregame ladder snapshots (picks-lessons rule 7): the whole Kalshi ladder goes to quote_snapshots once at T-60
(phase pre60) and once as the close (phase pre0: the last read inside the 30 minutes before the kick, written by
the first pass that sees the game kicked off, at the time it was read). Every strike, written once each, and the
labelled rows never collide with the near-strike history read at the same instant. Offline, on the NBA fixtures,
with the wall clock moved around PHI @ NYK's listed tip."""
import sys, os, copy, json, tempfile, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, feeds, store, notify

FIX = os.path.join(ROOT, 'tests', 'fixtures_nba')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = dict(watch.load_json(watch.CONFIG_PATH, {}), sports=['nba'])
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': ['test']
captured = {}
store.enabled = lambda: True
store.write = lambda table, rows, on_conflict=None, ignore_duplicates=False: captured.setdefault(table, []).extend(copy.deepcopy(rows)) or True
store.read = lambda table, params: []
store.claim = lambda table, row, on_conflict: True

fx = tempfile.mkdtemp()
for f in os.listdir(FIX):
    json.dump(json.load(open(os.path.join(FIX, f))), open(os.path.join(fx, f), 'w'))
ESPN = json.load(open(os.path.join(fx, 'espn_nba.json')))
GID = '502'   # PHI @ NYK, listed 2026-10-21T00:00Z, still pregame in the fixture
TIP = dt.datetime.fromisoformat(next(e for e in ESPN['events'] if e['id'] == GID)['date'].replace('Z', '+00:00'))
N = len(next(e for e in json.load(open(os.path.join(fx, 'kalshi_KXNBATOTAL.json')))['events'] if e['event_ticker'] == 'KXNBATOTAL-26OCT20PHINYK')['markets'])
clock = lambda minutes: setattr(feeds, 'clock_now', lambda: TIP + dt.timedelta(minutes=minutes))
snaps = lambda phase: [r for r in captured.get('quote_snapshots', []) if r['game_id'] == GID and r['phase'] == phase]

desk = watch.Desk(cfg, {}, fx)
rec = lambda: desk.state['games'][GID]

# T-90: the near-strike history only
clock(-90); captured.clear(); desk.run_pass()
assert snaps('pre') and not snaps('pre60') and 'snap60' not in rec() and 'pre_ladder' not in rec(), (len(snaps('pre')), rec().keys())
near = len(snaps('pre'))
assert 0 < near < N, near
# T-59: the whole ladder once, labelled pre60; one row per key in the batch and the labelled row is the one kept
clock(-59); captured.clear(); desk._pre_last.clear(); desk.run_pass()
p60 = snaps('pre60')
assert len(p60) == N and rec()['snap60'] == p60[0]['taken_at'], (len(p60), N)
batch = captured['quote_snapshots']
keys = [(r['taken_at'], r['game_id'], r['strike']) for r in batch]
assert len(keys) == len(set(keys)), 'duplicate keys in one write'
assert not snaps('pre'), 'the near-strike rows at the same instant gave way to the pre60 rows'
assert all(r['p_over'] is None and r['market_ticker'] and r['event_ticker'] == 'KXNBATOTAL-26OCT20PHINYK' for r in p60)
assert 'pre_ladder' not in rec(), 'the close is kept only inside the last 30 minutes'
# T-45: nothing new
clock(-45); captured.clear(); desk.run_pass()
assert not snaps('pre60') and 'pre_ladder' not in rec()
# T-20 and T-10: the newest full ladder is kept on the record
clock(-20); captured.clear(); desk.run_pass()
pl = rec().get('pre_ladder')
assert pl and len(pl['quotes']) == N and pl['event'] == 'KXNBATOTAL-26OCT20PHINYK', pl and len(pl['quotes'])
clock(-10); captured.clear(); desk.run_pass()
assert rec()['pre_ladder']['at'] >= pl['at'] and not snaps('pre0')
last = rec()['pre_ladder']['at']
print('preladder: pre60 written once at T-60, the near-strike history stands aside, the close read is kept')

# the kick: ESPN shows the game in the first quarter; the kept ladder becomes the close, written once
ev = next(e for e in ESPN['events'] if e['id'] == GID)
ev['status'] = {'period': 1, 'displayClock': '10:12', 'type': {'state': 'in', 'name': 'STATUS_IN_PROGRESS', 'shortDetail': '10:12 - 1st'}}
json.dump(ESPN, open(os.path.join(fx, 'espn_nba.json'), 'w'))
clock(2); captured.clear(); desk.run_pass()
p0 = snaps('pre0')
assert len(p0) == N and all(r['taken_at'] == last for r in p0) and rec()['snap0'] == last and 'pre_ladder' not in rec(), (len(p0), rec().get('snap0'))
strikes = sorted(r['strike'] for r in p0)
assert strikes == sorted(float(k) for k in pl['quotes']) and all(isinstance(r['strike'], float) for r in p0)
clock(3); captured.clear(); desk.run_pass()
assert not snaps('pre0') and not snaps('pre60'), 'written once'
# a game whose last pregame read was more than 30 minutes before the kick has no close, and is asked once
other = dict(desk.state['games'][GID], snap0=None)
other.pop('snap0'); other.pop('pre_ladder', None)
g = dict(id='x', sport='nba', short='A @ B')
captured.clear(); desk.close_ladder(g, other)
assert other['snap0'] == 'none' and not captured.get('quote_snapshots')
print('preladder: the close is written once at the time it was read; no read inside 30 minutes means no close')
