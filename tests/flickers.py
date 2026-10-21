"""The bets that come and go between the pushes.
1. flickers_from_rows: every line that cleared in any priced row, once per line, with first/last/how many rows,
   the best price and edge, whether it was pushed, and the grade.
2. A half where nothing clears at the first look (the push is a read), then Over 42.5 drops to 40c for one
   look and goes back: Today showed a BET for one pass, no push went out, and at the final the line is graded
   as cleared-not-pushed. The suggestions rows carry `since` on each cleared line (how long it has held)."""
import sys, os, copy, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, store, notify

FIX = os.path.join(ROOT, 'tests', 'fixtures')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = watch.load_json(watch.CONFIG_PATH, {})
pushes = []
notify.push = lambda title, body, priority='default', tags='football': (pushes.append((title, body)) or ['test'])

# 1. the pure function
rows = [
    dict(taken_at='2026-10-17T20:00:00+00:00', phase='half', singles=[dict(kind='over', line=42.5, price_c=59, contracts=121, cost=73.0, ok=False, edge=0.01)], mids=[], revs=[]),
    dict(taken_at='2026-10-17T20:00:30+00:00', phase='half', singles=[dict(kind='over', line=42.5, price_c=52, contracts=150, cost=80.0, ok=True, edge=0.06)],
         mids=[dict(a=dict(line=42.5, price_c=52), b=dict(line=48.5, price_c=45), pairs=118, cost=116.0, ok=True, ev=0.04)], revs=[]),
    dict(taken_at='2026-10-17T20:02:00+00:00', phase='early3', singles=[dict(kind='over', line=42.5, price_c=55, contracts=140, cost=79.0, ok=True, edge=0.04), dict(kind='under', line=51.5, price_c=60, contracts=90, cost=55.0, ok=True, edge=0.035)],
         mids=[], revs=[]),
]
fl = watch.flickers_from_rows(rows, 52, pushed=dict(singles=[dict(kind='under', line=51.5)], mid=None))
by = {(f['kind'], f.get('side'), f.get('line'), f.get('a_line')): f for f in fl}
o = by[('single', 'over', 42.5, None)]
assert o['n'] == 2 and o['rows'] == 3 and o['first'].endswith('20:00:30+00:00') and o['last'].endswith('20:02:00+00:00') and o['secs'] == 90, o
assert o['price_c'] == 52 and o['best_edge_c'] == 6.0 and o['contracts'] == 150 and not o['pushed'] and o['win'] and o['pnl'] == 70.0, o
u = by[('single', 'under', 51.5, None)]
assert u['pushed'] and u['n'] == 1 and u['secs'] == 0 and not u['win'] and u['pnl'] == -55.0, u
m = by[('mid', None, None, 42.5)]
assert m['n'] == 1 and not m['pushed'] and not m['win'] and m['pnl'] == round(118 - 116.0, 2), m
print('flickers: one entry per line, best moment kept, pushed marked, graded')

# 2. through the desk, with a fake Supabase that keeps suggestions and alerts
db = {'alerts': {}, 'results': {}, 'suggestions': []}
def fake_claim(table, row, on_conflict):
    key = tuple(row[k] for k in on_conflict.split(','))
    if key in db[table]:
        return False
    db[table][key] = copy.deepcopy(row)
    return True
def fake_write(table, rows, on_conflict=None, ignore_duplicates=False):
    if table in ('results', 'alerts'):
        for r in rows:
            db[table][r['game_id'] if table == 'results' else (r['game_id'], r['slot'])] = copy.deepcopy(r)
    if table == 'suggestions':
        db['suggestions'].extend(copy.deepcopy(rows))
    return True
def fake_read(table, params):
    if table == 'alerts':
        gid = params['game_id'].split('.', 1)[1]
        return sorted([r for (g_, _), r in db['alerts'].items() if g_ == gid], key=lambda r: r['sent_at'])
    if table == 'suggestions':
        gid = params['game_id'].split('.', 1)[1]
        rows = [r for r in db['suggestions'] if r['game_id'] == gid]
        if 'taken_at' in params:
            at = params['taken_at'].split('.', 1)[1]
            rows = [r for r in rows if r['taken_at'] == at]
        if 'phase' in params:
            rows = [r for r in rows if r['phase'] in params['phase'][4:-1].split(',')]
        return sorted(rows, key=lambda r: r['taken_at'])
    return []
store.enabled, store.claim, store.write, store.read = (lambda: True), fake_claim, fake_write, fake_read

def set_over_425(desk, ask):
    for mk in desk.events('nfl', 'total')[0]['markets']:
        if mk['floor_strike'] == 42.5:
            mk['yes_ask_dollars'] = f'{ask:.4f}'

d = watch.Desk(cfg, {}, FIX)
ASK0 = float(next(mk['yes_ask_dollars'] for mk in d.events('nfl', 'total')[0]['markets'] if mk['floor_strike'] == 42.5))   # the fixture's own ask (68c)
d.run_pass()                                   # first look: nothing clears at the fixture asks, the push is a read
rec = d.state['games']['401']
assert rec['slots'] == {'half': 'read'} and not rec.get('play_sheet') and len(pushes) == 1 and pushes[0][0].startswith('UPDATE'), (rec.get('slots'), pushes)
n0 = len(db['suggestions'])
# the ask on Over 42.5 drops to 40c for one look
d._events = {}; d._db_evals = {}
set_over_425(d, 0.40)
g = d.games('nfl')[0]
d.evaluate(g, rec)
assert len(pushes) == 1, 'a second push went out inside the same slot'
row = db['suggestions'][-1]
cleared = [x for x in row['singles'] if x['ok']]
assert cleared and cleared[0]['line'] == 42.5 and cleared[0]['since'] == row['taken_at'], cleared[:1]
assert rec['clear'].get('single over 42.5', {}).get('n') == 1
# and back up: nothing clears again
d._events = {}; d._db_evals = {}
set_over_425(d, ASK0)
d.evaluate(g, rec)
assert not [x for x in db['suggestions'][-1]['singles'] if x['ok']]
# the final: 51, the over 42.5 would have won. The record is the read's what-if; the flicker is graded on its own
final = copy.deepcopy(g); final.update(state='post', status='STATUS_FINAL'); final['away']['score'], final['home']['score'] = 27, 24
d.settle(final, rec)
res = db['results']['401']
assert res['plays_cost'] == 0 and res['sheet']['kind'] == 'update', res['sheet'].get('kind')
fl = res['flickers']
ov = [f for f in fl if f['kind'] == 'single' and f['line'] == 42.5]
assert len(ov) == 1 and ov[0]['n'] == 1 and not ov[0]['pushed'] and ov[0]['price_c'] == 40 and ov[0]['win'] and ov[0]['pnl'] > 0, ov
assert all(not f['pushed'] for f in fl), 'nothing was pushed as a play, so nothing can be marked pushed'
print('desk: a line that cleared for one look is graded as cleared-not-pushed, and the row carries since')
print('flickers: ok')
