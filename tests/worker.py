"""Worker checks, no network:
1. Two watchers (the Railway worker and the GitHub Actions backup) on the same fixtures with a shared alerts
   table: exactly one push goes out, and the second marks the slot as pushed elsewhere.
2. With Supabase unreachable, claim() lets the push through (a duplicate beats a miss).
3. pace() picks 5 s around the half, 60 s when live or near kickoff, 5 min otherwise.
4. State round-trips through desk_state, the archive row included.
5. The write cadence (Nov 8, Supabase's Disk IO warning): a heartbeat that leaves the state column alone, the
   state at most once a minute for routine changes and at least every 5 minutes, orders and the day's spend on
   the pass they change, finished games in the archive row, the pregame row only when it moves, a failed write
   retried after 30 s. On the repo's own state.json, ten minutes of a 5-second break write well under a
   twentieth of the bytes the old every-pass write did."""
import sys, os, copy, json, tempfile, datetime as dt
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
writes = []   # (table, row keys, bytes) for every write the worker makes
down = []     # non-empty: every write fails, as with Supabase unreachable
def fake_write(table, rows, on_conflict=None, ignore_duplicates=False):
    if down:
        return False
    for r in rows:
        writes.append((table, r.get('id'), tuple(sorted(r)), len(json.dumps(r, default=str))))
    if table == 'desk_state':
        # an upsert on id: a new row takes the column defaults (state '{}'), an existing one only the columns sent
        for r in rows:
            db['desk_state'].setdefault(r['id'], {'id': r['id'], 'state': {}}).update(copy.deepcopy(r))
    return True
def fake_read(table, params):
    if table == 'desk_state':
        op, val = params['id'].split('.', 1)
        ids = val.strip('()').split(',') if op == 'in' else [val]
        return [copy.deepcopy(db['desk_state'][i]) for i in ids if i in db['desk_state']]
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
d.phases, d.next_kick = {'pre': 4}, '2026-10-17T18:30:00+00:00';        assert worker.pace(d, now) == 60
d.phases, d.next_kick = {'pre': 4}, '2026-10-17T19:30:00+00:00';        assert worker.pace(d, now) == 300
d.phases, d.next_kick = {'post': 8}, None;                              assert worker.pace(d, now) == 300
print('pace: 5 / 60 / 300 as designed')

# state round trip
worker.store.write, worker.store.read = fake_write, fake_read
worker.save_state({'games': {'1': {'slots': {'half': 'play'}}}}, 'test')
assert worker.load_state() == {'games': {'1': {'slots': {'half': 'play'}}}}
print('state: saved and reloaded')

# ---- the write cadence ----
def reset():
    db['desk_state'].clear()
    writes.clear()
    down.clear()

def fulls():
    return [w for w in writes if w[1] == worker.STATE_ID and 'state' in w[2]]

def beats():
    return [w for w in writes if w[1] == worker.STATE_ID and 'state' not in w[2]]

def game(phase, **kw):
    return dict(dict(sport='nba', name='A at B', date='2026-11-08', first_seen='2026-11-08T00:00:00+00:00',
                     last_seen='2026-11-08T00:00:00+00:00', phase=phase), **kw)

def tick(rec, t):
    """What every pass does to a game whatever happens: read times and prices that nothing needs after a restart."""
    stamp = f'2026-11-08T01:{t // 60 % 60:02d}:{t % 60:02d}+00:00'
    rec['last_seen'] = stamp
    if rec['phase'] == 'pre':
        rec['mkt'] = dict(line=220.5, legs=[dict(side='over', k=219.5, c=52)], at=stamp)
        rec.setdefault('pre', {}).update(total=220.5, home_spread=-3.5, source='odds:pinnacle', at=stamp)
    else:
        rec['poly'] = dict(at=stamp, quotes={'220.5': dict(y=50 + t % 7)})
        rec['last_eval'] = stamp

# 1. the heartbeat never carries the state, and the stored state survives it
reset()
st = {'games': {'g1': game('live'), 'g2': game('pre')}}
sv = worker.Saver()
sv.after_pass(st, 'first pass', now=0)
assert len(fulls()) == 1 and not beats(), writes
saved = copy.deepcopy(db['desk_state']['worker']['state'])
tick(st['games']['g1'], 5); tick(st['games']['g2'], 5)
sv.after_pass(st, 'second pass', now=5)
assert len(fulls()) == 1 and len(beats()) == 1, writes
row = db['desk_state']['worker']
assert row['state'] == saved and row['note'] == 'second pass', row
print('heartbeat: last_beat and the note only, the stored state left as it was')

# 2. routine changes wait for the minute, volatile ones for the five minutes, orders and spend go at once
reset()
st = {'games': {'g1': game('live'), 'g2': game('pre')}}
sv = worker.Saver()
sv.after_pass(st, 'p', now=0)
for t in range(5, 40, 5):   # passes where only read times and prices move (and the pregame line's first read)
    tick(st['games']['g1'], t); tick(st['games']['g2'], t)
    sv.after_pass(st, 'p', now=t)
assert len(fulls()) == 1, f'volatile fields alone wrote the state: {len(fulls())}'
st['games']['g1'].update(phase='half', half=dict(away=50, home=48), half_at='2026-11-08T01:01:00+00:00')
sv.after_pass(st, 'p', now=40)
assert len(fulls()) == 1, 'a routine change inside the minute wrote the state'
sv.after_pass(st, 'p', now=60)
assert len(fulls()) == 2, 'a routine change did not write the state after a minute'
st['games']['g1']['auto'] = {'half': dict(at='x', n=2, open=[dict(client_order_id='o1', status='planned')])}
sv.after_pass(st, 'p', now=65)
assert len(fulls()) == 3, 'an order change waited'
st['day_spend'] = {'2026-11-08': 41.5}
sv.after_pass(st, 'p', now=70)
assert len(fulls()) == 4, 'a spend change waited'
st['games']['g1']['counted_day'] = True
sv.after_pass(st, 'p', now=72)
assert len(fulls()) == 5, 'the counted mark waited'
for t in range(75, 380, 5):   # five more minutes of nothing but volatile fields: one write, at 72 + 300
    tick(st['games']['g1'], t); tick(st['games']['g2'], t)
    sv.after_pass(st, 'p', now=t)
assert len(fulls()) == 6, f'expected one write at the five-minute mark, got {len(fulls()) - 5}'
assert worker.load_state() == st, 'the five-minute write did not carry the volatile fields'
print('cadence: volatile alone waits 5 min, routine 1 min, orders and spend on the pass')

# 3. finished games live in the archive row, and every game comes back on a restart
reset()
st = {'day_spend': {'2026-11-07': 12.0}, 'games': {
    'done': game('post', half_at='x', settled=dict(at='y', final_total=210)),
    'never': game('post'),                                     # final, never priced: nothing to grade
    'grading': game('post', half_at='x'),                      # final, not graded yet: stays in the worker row
    'live': game('live'), 'pre': game('pre')}}
sv = worker.Saver()
sv.after_pass(st, 'p', now=0)
arch = db['desk_state']['worker_archive']['state']['games']
assert set(arch) == {'done', 'never'}, set(arch)
assert set(db['desk_state']['worker']['state']['games']) == {'grading', 'live', 'pre'}
assert db['desk_state']['worker']['state']['day_spend'] == {'2026-11-07': 12.0}
assert worker.load_state() == st, 'the two rows do not add back up to the state'
# the last open game finishes and is graded: written at the minute in the worker row, the archive waits its 30 minutes
st['games']['grading']['settled'] = dict(at='z', final_total=199)
sv.after_pass(st, 'p', now=60)
assert 'grading' in db['desk_state']['worker']['state']['games']
assert set(db['desk_state']['worker_archive']['state']['games']) == {'done', 'never'}
assert worker.load_state() == st
# an archived game that changes is back in the worker row on the next write, archive or not
st['games']['done']['phase'] = 'live'   # ESPN reopened it
st['games']['done']['note'] = 'reopened'
sv.after_pass(st, 'p', now=120)
assert 'done' in db['desk_state']['worker']['state']['games']
assert worker.load_state()['games']['done']['note'] == 'reopened'
st['games']['done']['phase'] = 'post'
st['games']['done'].pop('note')
# half an hour on, the archive is rewritten with every finished game and the worker row is left with the rest
sv.after_pass(st, 'p', now=1800)
assert set(db['desk_state']['worker_archive']['state']['games']) == {'done', 'never', 'grading'}
assert set(db['desk_state']['worker']['state']['games']) == {'live', 'pre'}
assert worker.load_state() == st
# a pruned game leaves the archive at its next rewrite; until then a restart folds it back in (prune drops it again)
del st['games']['never']
sv.after_pass(st, 'p', now=2100)
sv.after_pass(st, 'p', now=3700)
assert 'never' not in db['desk_state']['worker_archive']['state']['games']
assert worker.load_state() == st
# the stop write brings the archive up to date whatever the clock says
st['games']['live'].update(phase='post', half_at='x', settled=dict(at='w', final_total=230))
sv.save(st, 'stopped', now=3710, final=True)
assert 'live' in db['desk_state']['worker_archive']['state']['games']
assert db['desk_state']['worker']['note'] == 'stopped' and worker.load_state() == st
print('archive: finished games in their own row, the worker row keeps the rest, a restart gets all of it back')

# 4. the pregame row: on a move, or once a minute
reset()
st = {'games': {'p1': game('pre'), 'p2': game('pre')}}
tick(st['games']['p1'], 0); tick(st['games']['p2'], 0)
sv = worker.Saver()
pregame = lambda: [w for w in writes if w[1] == 'pregame']
sv.after_pass(st, 'p', now=0)
assert len(pregame()) == 1
for t in (5, 10, 15):
    tick(st['games']['p1'], t); tick(st['games']['p2'], t)
    sv.after_pass(st, 'p', now=t)
assert len(pregame()) == 1, 'a pregame row went out with nothing but new read times'
st['games']['p1']['mkt']['legs'][0]['c'] = 55
sv.after_pass(st, 'p', now=20)
assert len(pregame()) == 2 and db['desk_state']['pregame']['state']['p1']['legs'][0]['c'] == 55
tick(st['games']['p1'], 80); tick(st['games']['p2'], 80)
st['games']['p1']['mkt']['legs'][0]['c'] = 55
sv.after_pass(st, 'p', now=80)
assert len(pregame()) == 3, 'the pregame row went stale past a minute'
print('pregame row: written on a move or once a minute')

# 5. a failed write is tried again after 30 seconds, with heartbeats (also failing here) in between
reset()
st = {'games': {'g1': game('live')}}
sv = worker.Saver()
down.append(1)
sv.after_pass(st, 'p', now=0)
assert sv.full_at is None and sv.fail_at == 0 and not writes
calls = []
real_save = sv.save
sv.save = lambda *a, **k: (calls.append(a[2] if len(a) > 2 else k.get('now')) or real_save(*a, **k))
sv.after_pass(st, 'p', now=10)
assert not calls, 'a failed write was retried inside 30 seconds'
down.clear()
sv.after_pass(st, 'p', now=31)
assert calls == [31] and len(fulls()) == 1, (calls, writes)
print('outage: the state write waits 30 s after a failure, then goes')

# 6. the bytes: ten minutes of a 5-second break on the repo's state.json, old write against new
real = watch.load_json(watch.STATE_PATH, {})
live = [gid for gid, r in real.get('games', {}).items() if r.get('phase') != 'post'][:6] or list(real.get('games', {}))[:6]
reset()
sv = worker.Saver()
old_bytes = 0
for i, t in enumerate(range(0, 600, 5)):
    for gid in live:
        tick(real['games'][gid], t)
    if i == 30:   # one break read lands in the middle: a routine change
        real['games'][live[0]]['half'] = dict(away=55, home=51)
    old_bytes += len(json.dumps(dict(id='worker', state=real), default=str))
    sv.after_pass(real, 'p', now=t)
new_bytes = sum(w[3] for w in writes)
assert new_bytes * 20 < old_bytes, f'new {new_bytes} vs old {old_bytes}'
print(f'bytes: ten minutes of a break wrote {new_bytes / 1e6:.2f} MB, the old way {old_bytes / 1e6:.1f} MB ({old_bytes / max(1, new_bytes):.0f}x less)')
print('worker: ok')
