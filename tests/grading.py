"""Grading is of what was pushed, and both watchers grade the same push.
1. grade_sheet: the first single is the play, the rest are backups; a middle-led push grades the middle as the
   play; a read grades its resting middle as a what-if only.
2. The Oct 17-19 bug: watcher A pushes the PLAY at the half; watcher B first sees the game in Q3 with nothing
   clearing and its push is claimed as an update. Before, B graded its own empty sheet and its results row
   overwrote A's (ARI @ LAR showed +0 on three winning unders). Now both grade the first PLAY alert's sheet.
3. An alert pushed before sheets were kept is rebuilt from its suggestions row."""
import sys, os, copy, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, store, notify, feeds

FIX = os.path.join(ROOT, 'tests', 'fixtures')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = watch.load_json(watch.CONFIG_PATH, {})
notify.push = lambda title, body, priority='default', tags='football': ['test']

# 1. the grading rule
sh = dict(lead='single', total=55.5, spread=-3.5, h1a=13, h1h=7, fair=47.5, mkt=45.5,
          singles=[dict(kind='over', line=42.5, price_c=59, contracts=121, cost=73.0), dict(kind='under', line=51.5, price_c=66, contracts=82, cost=55.5)],
          mid=dict(a_line=42.5, a_price=59, b_line=48.5, b_price=45, pairs=118, cost=123.5), rest_mid=None)
g = watch.grade_sheet(sh, 52)          # over 42.5 wins, under 51.5 loses, middle 43 to 48 misses
assert g['lead'] == 'single' and g['win'] is True and g['pnl'] == 48.0 and g['cost'] == 73.0, g
assert [o['win'] for o in g['options']] == [True, False] and g['options'][0]['play'] and not g['options'][1]['play']
assert g['mid_hit'] is False and g['mid_pnl'] == round(118 - 123.5, 2) and g['n_plays'] == 3
assert g['detail'].startswith('over 42.5@59 W +48; alt under 51.5@66 L -56; mid 42.5/48.5 miss -6'), g['detail']
g = watch.grade_sheet(dict(sh, lead='mid'), 46)   # middle-led push, final inside the window
assert g['lead'] == 'mid' and g['win'] is True and g['pnl'] == round(2 * 118 - 123.5, 2) and g['cost'] == 123.5, g
g = watch.grade_sheet(dict(lead='rest', singles=[], mid=None, rest_mid=dict(a_line=44.5, a_price=55, b_line=49.5, b_price=58, pairs=57, cost=64.41), h1a=3, h1h=20, total=46.5, spread=-7), 47)
assert g['pnl'] == 0 and g['cost'] == 0 and g['win'] is None and g['rest_hit'] is True and g['rest_pnl'] == round(114 - 64.41, 2), g
print('grade: first single is the play, middle-led grades the middle, a read grades the what-if only')

# 2. two watchers, one record. A fake Supabase: claims land in alerts, reads come back, results rows are kept.
db = {'alerts': {}, 'results': {}, 'suggestions': []}
def fake_claim(table, row, on_conflict):
    key = tuple(row[k] for k in on_conflict.split(','))
    if key in db[table]:
        return False
    db[table][key] = copy.deepcopy(row)
    return True
def fake_write(table, rows, on_conflict=None, ignore_duplicates=False):
    if table == 'results':
        for r in rows:
            db['results'][r['game_id']] = copy.deepcopy(r)
    if table == 'alerts':
        for r in rows:
            db['alerts'][(r['game_id'], r['slot'])] = copy.deepcopy(r)
    if table == 'suggestions':
        db['suggestions'].extend(copy.deepcopy(rows))
    return True
def fake_read(table, params):
    if table == 'alerts':
        gid = params['game_id'].split('.', 1)[1]
        return sorted([r for (g_, _), r in db['alerts'].items() if g_ == gid], key=lambda r: r['sent_at'])
    if table == 'suggestions':
        gid, at = params['game_id'].split('.', 1)[1], params['taken_at'].split('.', 1)[1]
        return [r for r in db['suggestions'] if r['game_id'] == gid and r['taken_at'] == at][:1]
    return []
store.enabled, store.claim, store.write, store.read = (lambda: True), fake_claim, fake_write, fake_read

def cheap_over(desk):
    """The fixture's asks clear nothing; drop Over 42.5 to 40c so a single clears and the push is a PLAY."""
    for mk in desk.events('nfl', 'total')[0]['markets']:
        if mk['floor_strike'] == 42.5:
            mk['yes_ask_dollars'] = '0.4000'
A = watch.Desk(cfg, {}, FIX)
cheap_over(A)
A.run_pass()                                           # A pushes the PLAY at the half for BUF @ LAR
recA = A.state['games']['401']
assert recA['slots'] == {'half': 'play'} and recA['play_sheet']['kind'] == 'play' and recA['play_sheet']['singles'], recA.get('slots')
assert db['alerts'][('401', 'half')]['sheet']['singles'] == recA['play_sheet']['singles'], 'the alert row must carry the pushed sheet'

# B comes along in Q3 with the asks moved: nothing clears, so its push is an update, and it never saw the half push
B = watch.Desk(cfg, {}, FIX)
gB = copy.deepcopy(B.games('nfl')[0])
gB.update(status='STATUS_IN_PROGRESS', period=3, clock='14:30', clock_s=870)
gB['away']['linescores'], gB['home']['linescores'] = [3, 10, 0], [7, 0, 0]
ev = B.events('nfl', 'total')[0]
for mk in ev['markets']:
    mk['yes_ask_dollars'], mk['no_ask_dollars'] = '0.9000', '0.9000'   # every ask at 90c: nothing can clear
recB = B.state['games'].setdefault('401', dict(sport='nfl', name=gB['name'], date=gB['date_et'], first_seen=watch.now_iso()))
recB['phase'] = 'early3'
B.restore_pregame([gB])
B.evaluate(gB, recB)
assert recB['slots'] == {'q3': 'read'} and 'play_sheet' not in recB and recB['sheet']['kind'] == 'update' and not recB['sheet']['singles'], recB.get('slots')

# the final: 51 points, the over 42.5 won. Both watchers settle; both rows must be the PLAY's grade
final = copy.deepcopy(A.games('nfl')[0]); final.update(state='post', status='STATUS_FINAL')
final['away']['score'], final['home']['score'] = 27, 24
B.settle(final, recB)
rowB = copy.deepcopy(db['results']['401'])
A.settle(final, recA)
rowA = copy.deepcopy(db['results']['401'])
assert rowB['plays_cost'] > 0 and rowB['plays_pnl'] > 0 and rowB['sheet']['kind'] == 'play', rowB
for k in ('plays_cost', 'plays_pnl', 'mid_pnl', 'plays', 'n_plays', 'half', 'total', 'fair', 'mkt'):
    assert rowA[k] == rowB[k], (k, rowA[k], rowB[k])
assert rowA['sheet']['singles'] == recA['play_sheet']['singles']
print('record: a watcher that never saw the PLAY grades it anyway, from the alerts table')

# 3. an alert from before sheets were kept: rebuilt from its suggestions row
old = db['alerts'][('401', 'half')]
old['sheet'] = None
db['suggestions'] = [dict(game_id='401', taken_at=old['suggestion_at'], total=55.5, home_spread=-3.5, half_away=13, half_home=7, mu=27.4, sd=10.2,
                          fair_line=47.5, market_line=45.5,
                          singles=[dict(kind='over', line=42.5, price_c=59, contracts=121, cost=73.0, ok=True, edge=0.05),
                                   dict(kind='over', line=42.5, price_c=60, contracts=100, cost=61.0, ok=True, edge=0.04),
                                   dict(kind='under', line=51.5, price_c=66, contracts=82, cost=55.5, ok=False, edge=0.01)],
                          mids=[dict(a=dict(line=42.5, price_c=59), b=dict(line=48.5, price_c=45), pairs=118, cost=123.5, ok=True, ev=0.03)])]
C = watch.Desk(cfg, {}, FIX)
recC = dict(sport='nfl', name='x', half_at='t', slots={'half': 'elsewhere'})
C.settle(final, recC)
row = db['results']['401']
assert row['sheet'].get('rebuilt') and [s['line'] for s in row['sheet']['singles']] == [42.5] and row['sheet']['mid']['pairs'] == 118, row['sheet']
assert row['plays_cost'] == 73.0 and row['plays_pnl'] == 48.0 and row['mid_pnl'] == round(118 - 123.5, 2), row
print('rebuilt: an old alert grades from its suggestions row, one single per line, best first')
print('grading: ok')
