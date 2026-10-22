"""The Oct 17 fixes (claude/desk-issues-oct17.md), no network:
1. A game with no pregame line on record is skipped at the half. The feed's odds block is the live line by then
   and is never read; the only source is the games table (restore_pregame).
2. The moment the live score differs from the halftime score, nothing is priced, logged or written, and
   nothing is pushed. While the score still matches, early Q3 prices and the row carries the live score.
3. store.write survives a column the schema does not have yet: it drops the column, says so once, and writes.
4. scripts/save_run.py appends this run's CSV rows to main's copy of the file, keeps CRLF, never keeps a
   conflict marker, and takes state.json whole.
5. portfolio.py never prints a dollar figure to the sync log."""
import sys, os, copy, json, shutil, tempfile, csv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import watch, store, notify, feeds
import save_run

FIX = os.path.join(ROOT, 'tests', 'fixtures')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = watch.load_json(watch.CONFIG_PATH, {})
pushes = []
notify.push = lambda title, body, priority='default', tags='football': (pushes.append(title) or ['test'])
captured = {}
store.enabled = lambda: True
store.write = lambda table, rows, on_conflict=None, ignore_duplicates=False: captured.setdefault(table, []).extend(copy.deepcopy(rows)) or True
store.read = lambda table, params: []
store.claim = lambda table, row, on_conflict: True


def log_rows():
    try:
        return list(csv.DictReader(open(watch.LOG_PATH, newline='')))
    except FileNotFoundError:
        return []


# 1. no line on record: the fixtures without supabase_games.json
bare = os.path.join(scratch, 'bare')
shutil.copytree(FIX, bare)
os.remove(os.path.join(bare, 'supabase_games.json'))
d = watch.Desk(cfg, {}, bare)
d.run_pass()
rec = d.state['games']['401']
assert feeds.espn_lines(d.games('nfl')[0])[1] == 55.5, 'fixture lost its odds block'   # the feed has a line; it must not be used
assert not pushes and not captured.get('suggestions') and not log_rows(), 'priced a half with no pregame line on record'
assert rec.get('noted_no_line') and not (rec.get('pre') or {}).get('total'), rec
assert not any('pre_total' in r for r in captured['games'] if r['id'] == '401'), 'wrote a pregame line it never had'
print('lines: no line on record means skip; the live line was never read')

# 2. the score moves after the half
captured.clear(); pushes.clear()
d = watch.Desk(cfg, {}, FIX)
d.run_pass()                                        # BUF @ LAR priced at the half (13-7) off the restored line
assert len(pushes) == 1 and 'Bills 13, Rams 7 (half' in pushes[0] and len(captured['suggestions']) == 1 and len(log_rows()) == 1, pushes
rec = d.state['games']['401']
g = copy.deepcopy(d.games('nfl')[0])
g.update(status='STATUS_IN_PROGRESS', period=3, clock='14:20', clock_s=860)
g['away']['linescores'], g['home']['linescores'] = [3, 10, 0], [7, 0, 0]
assert feeds.phase(g) == 'early3'
d._db_evals.clear()
rec['phase'] = 'early3'
d.evaluate(g, rec)                                  # Q3, score unchanged: priced, pushed once more (the q3 slot)
assert len(captured['suggestions']) == 2 and len(log_rows()) == 2 and len(pushes) == 2, (len(captured['suggestions']), len(log_rows()), pushes)
s = captured['suggestions'][-1]
assert s['phase'] == 'early3' and (s['away_score'], s['home_score']) == (13, 7) == (s['half_away'], s['half_home'])
g['home']['score'], g['home']['linescores'] = 14, [7, 0, 7]   # the Rams score at 13:20 of Q3
d._db_evals.clear()
for _ in range(3):
    d.evaluate(g, rec)
assert len(captured['suggestions']) == 2 and len(log_rows()) == 2 and len(pushes) == 2, 'priced, logged or pushed after the score moved'
assert rec['moved'] == {'away': 13, 'home': 14} and rec['moved_at'] and rec['half'] == {'away': 13, 'home': 7}
print('stale: nothing priced, logged or pushed once the score moves')

# 3. a column the schema does not have yet
import importlib
importlib.reload(store)
calls = []
class R:
    def __init__(self, code, text=''):
        self.status_code, self.text = code, text
def fake_post(url, params=None, data=None, headers=None, timeout=None):
    calls.append(json.loads(data))
    if any('away_score' in r for r in calls[-1]):
        return R(400, '{"code":"PGRST204","message":"Could not find the \'away_score\' column of \'suggestions\' in the schema cache"}')
    return R(201)
store.requests = type('Q', (), {'post': staticmethod(fake_post)})
store.enabled = lambda: True
assert store.write('suggestions', [dict(game_id='1', away_score=3, mu=1.0), dict(game_id='2', away_score=4, mu=2.0)], on_conflict='taken_at,game_id') is True
assert len(calls) == 2 and all('away_score' not in r for r in calls[1]) and [r['mu'] for r in calls[1]] == [1.0, 2.0], calls
print('store: a missing column is dropped and the row still lands')

# 4. save_run: append-only merge, CRLF kept, markers dropped, snapshot taken whole
base = b'time,game\r\n1,a\r\n2,b\r\n'
ours = base + b'3,c\r\n4,d\r\n'
main = base + b'3,x\r\n'                                            # main moved: another run added a row
assert save_run.merge_append(main, base, ours) == main + b'3,c\r\n4,d\r\n'
assert save_run.merge_append(b'', base, ours) == ours                 # main has no file yet
assert save_run.merge_append(main, base, base) == main                # this run added nothing
assert save_run.merge_append(main, b'', ours) == main + b'3,c\r\n4,d\r\n'          # file created this run: header once, rows main has not again
assert save_run.merge_append(base[:-2], base, ours) == base + b'3,c\r\n4,d\r\n'        # main lacks the final newline
assert save_run.merge_append(main, base, ours + b'3,c\r\n') == main + b'3,c\r\n4,d\r\n'   # a row ours has twice lands once
# the header upgrade: ours was rewritten under a wider header with the old rows padded, plus a new wide row and a
# stray header among the rows (the Oct 22 results.csv). main is widened once; nothing lands twice.
wide = b'time,game,q3\r\n1,a,\r\n2,b,\r\ntime,game,q3\r\n5,e,x\r\n'
got = save_run.merge_append(main, base, wide)
assert got == b'time,game,q3\r\n1,a,\r\n2,b,\r\n3,x,\r\n5,e,x\r\n', got
assert save_run.merge_append(got, wide, wide) == got                                       # the same run saved twice adds nothing
assert save_run.merge_append(got, b'', b'time,game,q3\r\n1,a,\r\n"6,f",g,\r\n') == got + b'"6,f",g,\r\n'   # a quoted comma is one field
odd = b'3,c\r\n<<<<<<< Updated upstream\r\n=======\r\n4,d\r\n>>>>>>> Stashed changes\r\n'
assert save_run.strip_markers('t', odd) == b'3,c\r\n4,d\r\n'
assert save_run.added_rows(b'1\n2\n', b'0\n1\n2\n3\n') == b'0\n3\n'    # base not a prefix: the rows base lacks
print('save_run: rows appended to main, markers dropped')

# 5. no balance in the sync log line
src = open(os.path.join(ROOT, 'portfolio.py')).read()
for bad in ("balance $", "portfolio $", "['balance']}", "['portfolio_value']}"):
    assert bad not in src, f'portfolio.py prints a dollar figure ({bad})'
print('portfolio: the sync line carries no dollar figure')
print('fixes: ok')
