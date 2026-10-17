"""Worker checks, no network:
1. Two watchers (the Railway worker and the GitHub Actions backup) on the same fixtures with a shared alerts
   table: exactly one push goes out, and the second marks the slot as pushed elsewhere.
2. With Supabase unreachable, claim() lets the push through (a duplicate beats a miss).
3. pace() picks 5 s around the half, 60 s when live or near kickoff, 5 min otherwise.
4. State round-trips through desk_state."""
import sys, os, copy, tempfile, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, store, notify, worker

FIX = os.path.join(ROOT, 'tests', 'fixtures')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = watch.load_json(watch.CONFIG_PATH, {})
pushes = []
notify.push = lambda title, body, priority='default', tags='football': (pushes.append(title) or ['test'])

# a fake Supabase: alerts keyed by (game_id, slot), desk_state keyed by id
db = {'alerts': {}, 'desk_state': {}}
def fake_claim(table, row, on_conflict):
    key = tuple(row[k] for k in on_conflict.split(','))
    if key in db[table]:
        return False
    db[table][key] = row
    return True
def fake_write(table, rows, on_conflict=None, ignore_duplicates=False):
    if table == 'desk_state':
        for r in rows:
            db['desk_state'][r['id']] = copy.deepcopy(r)
    return True
def fake_read(table, params):
    if table == 'desk_state':
        r = db['desk_state'].get(params['id'].split('.', 1)[1])
        return [r] if r else []
    return []
store.enabled, store.claim, store.write, store.read = (lambda: True), fake_claim, fake_write, fake_read

a, b = watch.Desk(cfg, {}, FIX), watch.Desk(cfg, {}, FIX)
a.run_pass(); b.run_pass()
assert len(pushes) == 1, f'expected one push across both watchers, got {pushes}'
slots_b = [r.get('slots') for r in b.state['games'].values() if r.get('slots')]
assert slots_b and list(slots_b[0].values()) == ['elsewhere'], slots_b
print('claim: two watchers, one push')

# Supabase down: claim() itself must say go
store.claim = watch.store.claim = None
import importlib; importlib.reload(store)
store.enabled = lambda: True
store.requests = type('R', (), {'post': staticmethod(lambda *a, **k: (_ for _ in ()).throw(ConnectionError('down')))})
assert store.claim('alerts', {'game_id': 'x', 'slot': 'half'}, 'game_id,slot') is True
print('claim: Supabase down still pushes')

# pacing
d = watch.Desk(cfg, {}, FIX)
now = dt.datetime(2026, 10, 17, 16, 0, tzinfo=dt.timezone.utc)
d.phases, d.next_kick = {'half': 1, 'pre': 5}, None;                 assert worker.pace(d, now) == 5
d.phases = {'approaching': 1};                                          assert worker.pace(d, now) == 5
d.phases = {'live': 3, 'pre': 2};                                       assert worker.pace(d, now) == 60
d.phases, d.next_kick = {'pre': 4}, '2026-10-17T16:10:00+00:00';        assert worker.pace(d, now) == 60
d.phases, d.next_kick = {'pre': 4}, '2026-10-17T19:30:00+00:00';        assert worker.pace(d, now) == 300
d.phases, d.next_kick = {'post': 8}, None;                              assert worker.pace(d, now) == 300
print('pace: 5 / 60 / 300 as designed')

# state round trip
worker.store.write, worker.store.read = fake_write, fake_read
worker.save_state({'games': {'1': {'slots': {'half': 'play'}}}}, 'test')
assert worker.load_state() == {'games': {'1': {'slots': {'half': 'play'}}}}
print('state: saved and reloaded')
print('worker: ok')
