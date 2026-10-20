"""Runs the fixtures through the watcher twice, once with the Supabase mirror off and once with it on (writes
captured in memory, nothing sent), and checks that:
  1. every push title and body is identical either way (the mirror never touches the PLAY/UPDATE text),
  2. games, suggestions, quote_snapshots, alerts and results rows come out with uniform keys per table,
  3. the timestamps line up: a suggestions row, its quote rows and its alert all share taken_at.
Also grades a synthetic final to exercise settle(), writing to a scratch results file, not log/results.csv.
Pass --dump FILE to write the captured rows as JSON (handy for loading into a local Postgres)."""
import sys, os, json, csv, copy, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, store, notify, feeds

FIX = os.path.join(ROOT, 'tests', 'fixtures')
pushes = []
notify.push = lambda title, body, priority='default', tags='football': (pushes.append((title, body, priority)) or ['test'])
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = watch.load_json(watch.CONFIG_PATH, {})


def run(mirror):
    captured = {}
    store.enabled = lambda: mirror
    store.write = lambda table, rows, on_conflict=None, ignore_duplicates=False: captured.setdefault(table, []).extend(copy.deepcopy(rows)) or True
    store.read = lambda table, params: []
    store.claim = lambda table, row, on_conflict: True
    pushes.clear()
    desk = watch.Desk(cfg, {}, FIX)
    desk.run_pass()
    # a synthetic final for the fixture game that was priced at the half: exercise settle() and the results mirror
    for sport in cfg.get('sports', ['nfl', 'cfb']):
        for g in desk.games(sport):
            rec = desk.state['games'].get(g['id'])
            if rec and rec.get('sheet'):
                g2 = dict(g, state='post')
                g2['away'] = dict(g['away'], score=g['away']['score'] + 14)
                g2['home'] = dict(g['home'], score=g['home']['score'] + 17)
                desk.settle(g2, rec)
    return list(pushes), captured, desk.state


p_off, c_off, _ = run(False)
p_on, c_on, state = run(True)
assert p_off == p_on and p_on, 'push text changed when the mirror was on'
assert not c_off, 'mirror off wrote rows'
for table in ('games', 'suggestions', 'quote_snapshots', 'alerts', 'results'):
    rows = c_on.get(table) or []
    assert rows, f'no {table} rows captured'
    keys = {tuple(sorted(r)) for r in rows}
    if table == 'games':
        # Two shapes, two writes: a game with a pregame line carries the pre_* columns, a game without carries
        # none of them, so a watcher with no line on record never nulls out the other watcher's line.
        lined = [r for r in rows if 'pre_total' in r]
        unlined = [r for r in rows if 'pre_total' not in r]
        assert lined and unlined, 'expected games rows both with and without a pregame line'
        assert all(r['pre_total'] for r in lined) and not any(k.startswith('pre_') for r in unlined for k in r), 'games rows mix pre_* columns'
        assert len({tuple(sorted(r)) for r in lined}) == 1 and len({tuple(sorted(r)) for r in unlined}) == 1, f'games rows have different keys: {keys}'
    else:
        assert len(keys) == 1, f'{table} rows have different keys: {keys}'
    for r in rows:
        json.dumps(store.clean(r))   # must be JSON-serializable
sug = c_on['suggestions'][0]
# the priced game's line came from the games table (tests/fixtures/supabase_games.json), never from the feed at the half
assert sug['total'] == 55.5 and sug['home_spread'] == -3.5 and state['games'][sug['game_id']]['pre'].get('restored'), 'pregame line not restored from the games table'
assert (sug['away_score'], sug['home_score']) == (sug['half_away'], sug['half_home']), 'a priced row must carry the halftime score as its live score'
half_q = [q for q in c_on['quote_snapshots'] if q['phase'] != 'pre']
pre_q = [q for q in c_on['quote_snapshots'] if q['phase'] == 'pre']
assert half_q and all(q['taken_at'] == sug['taken_at'] and q['game_id'] == sug['game_id'] for q in half_q)
# pregame line history: upcoming games only, no model numbers, and never for the game priced at the half
assert pre_q and all(q['p_over'] is None and q['game_id'] != sug['game_id'] for q in pre_q), 'pregame history rows look wrong'
assert c_on['alerts'][0]['suggestion_at'] == sug['taken_at'] and c_on['alerts'][0]['body'] == p_on[0][1]
assert c_on['results'][0]['game_id'] == sug['game_id'] and c_on['results'][0]['sheet']
assert state['games'][sug['game_id']]['half_at'] == sug['taken_at'] and state['games'][sug['game_id']]['kalshi_total_event'] == sug['event_ticker']
csv_rows = list(csv.DictReader(open(watch.RESULTS_PATH)))
assert len(csv_rows) == 2 and csv_rows[0]['game'] == c_on['results'][0]['game'], 'results.csv and the results row disagree'
print(f"mirror: {len(c_on['games'])} games, {len(c_on['suggestions'])} suggestions, {len(half_q)} quotes, {len(pre_q)} pregame quotes, "
      f"{len(c_on['alerts'])} alerts, {len(c_on['results'])} results; push text identical with the mirror on and off")
if '--dump' in sys.argv:
    out = sys.argv[sys.argv.index('--dump') + 1]
    json.dump(store.clean(c_on), open(out, 'w'), default=str, indent=1)
    print(f'rows written to {out}')
print('mirror: ok')
