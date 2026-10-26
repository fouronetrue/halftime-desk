"""The quarter-break misreads of Oct 24 (claude/breaks-oct25.md), replayed offline:
  MIA @ CHA: the end of the first quarter (31-31) priced as the half, under 216.5 at 17c, -$132
  GS @ PHX: the start of the third (54-57, the halftime score) priced as the end of the third, under 213.5 at
            18c, -$132; then 57-59 and 57-61 priced the same way while the clock still read 0:00
  DEN @ OKC: early third (48-46) priced as the end of the third (won by luck)
ESPN marks a quarter break with the next period's number and a 0:00 clock. Four guards now stand in the way:
1. a break needs evidence the period was played: the desk saw its clock running, or a linescore with points;
2. a break cannot come before it could have happened: the half 50 minutes after the listed start, the end of
   the third 30 minutes after the half was read;
3. the break score is captured once, so a score that moves while ESPN still shows the break stops the pricing;
4. the NBA never prices without a usable market center (a rejected center is the surest sign of a bad read)."""
import sys, os, copy, json, tempfile, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, feeds, store, notify, engine

FIX = os.path.join(ROOT, 'tests', 'fixtures_nba')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = dict(watch.load_json(watch.CONFIG_PATH, {}), sports=['nba'])
assert cfg.get('require_center') == ['nba'], cfg.get('require_center')
pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': (pushes.append((title, body)) or ['test'])
captured = {}
store.enabled = lambda: True
store.write = lambda table, rows, on_conflict=None, ignore_duplicates=False: captured.setdefault(table, []).extend(copy.deepcopy(rows)) or True
store.read = lambda table, params: []
store.claim = lambda table, row, on_conflict: True
# the fixture games are dated Oct 20, 2026 (their Kalshi events carry that date); the test moves the wall clock
# instead of the games: tip(gid) is a game's listed start, at(gid, m) a clock m minutes after it
ESPN0 = json.load(open(os.path.join(FIX, 'espn_nba.json')))
TIP = {e['id']: dt.datetime.fromisoformat(e['date'].replace('Z', '+00:00')) for e in ESPN0['events']}
def clock_at(gid, minutes):
    feeds.clock_now = lambda: TIP[gid] + dt.timedelta(minutes=minutes)
    return feeds.clock_now()
now = dt.datetime.now(dt.timezone.utc)
feeds.clock_now = lambda: now
iso = lambda minutes_ago: (now - dt.timedelta(minutes=minutes_ago)).strftime('%Y-%m-%dT%H:%M:%SZ')

# 1. the unit rules
g = dict(sport='nba', state='in', status='STATUS_HALFTIME', period=2, clock_s=0, home=dict(score=31, linescores=[31]), away=dict(score=31, linescores=[31]))
assert feeds.half_score(g) is None, 'end of the first (one linescore) reported as halftime is not the half'
g['home']['linescores'], g['away']['linescores'] = [31, 0], [31, 0]
assert feeds.half_score(g) is None, 'a 0-0 second period listed early is not evidence'
assert feeds.half_score(g, dict(seen={'2': True})) == (31, 31), 'the clock seen running in the second is evidence'
g['home']['linescores'], g['away']['linescores'] = [30, 36], [31, 27]
g['home']['score'], g['away']['score'] = 66, 58
assert feeds.half_score(g) == (58, 66), 'points in the second period are evidence'
g3 = dict(sport='nba', state='in', status='STATUS_IN_PROGRESS', period=3, clock_s=0, home=dict(score=57, linescores=[30, 27]), away=dict(score=54, linescores=[27, 27]))
assert feeds.third_score(g3) is None and feeds.half_score(g3) == (54, 57), 'period 3 at 0:00 with two linescores is the start of the third: the half, not its end'
g3['home']['linescores'].append(0); g3['away']['linescores'].append(0)
assert feeds.third_score(g3) is None
g3['home']['linescores'][2] = 2; g3['home']['score'] = 59
assert feeds.third_score(g3) == (54, 59), 'a basket in the third makes period 3 played (the time guard is the second gate)'
assert feeds.third_score(dict(g3, home=dict(score=57, linescores=[30, 27, 0]), away=dict(score=54, linescores=[27, 27, 0])), dict(seen={'3': True})) == (54, 57)
r = {}
feeds.note_clock(dict(sport='nba', state='in', period=2, clock_s=0), r); assert not r.get('seen'), '0:00 is not a running clock'
feeds.note_clock(dict(sport='nba', state='in', period=2, clock_s=720), r); assert not r.get('seen'), '12:00 is not a running clock'
feeds.note_clock(dict(sport='nba', state='in', period=2, clock_s=433), r); assert r['seen'] == {'2': True}
feeds.note_clock(dict(sport='nfl', state='in', period=3, clock_s=850), r); assert r['seen'] == {'2': True, '3': True}
feeds.note_clock(dict(sport='nfl', state='pre', period=0, clock_s=None), r); assert r['seen'] == {'2': True, '3': True}
assert feeds.break_too_early(dict(start_utc=iso(44)), {}, 'half').startswith('half reported 44 min')
assert feeds.break_too_early(dict(start_utc=iso(72)), {}, 'half') is None
assert feeds.break_too_early(dict(start_utc=iso(90)), dict(half_at=(now - dt.timedelta(minutes=16)).isoformat()), 'q3').startswith('end of 3rd reported 16 min after the half')
assert feeds.break_too_early(dict(start_utc=iso(90)), dict(half_at=(now - dt.timedelta(minutes=47)).isoformat()), 'q3') is None
assert feeds.break_too_early(dict(start_utc=iso(90)), {}, 'q3').startswith('end of 3rd reported 90 min after the listed start')
assert feeds.break_too_early(dict(start_utc=iso(100)), {}, 'q3') is None
assert feeds.break_too_early(dict(start_utc=None), {}, 'half') is None, 'no start time: the other guards carry it'
print('breaks: the evidence rule, the clock witness, the time guard')


def desk_with(events_fn, games_rows=None):
    """A fixture folder with the NBA scoreboard rewritten by events_fn(espn dict)."""
    fx = tempfile.mkdtemp()
    for f in os.listdir(FIX):
        src = json.load(open(os.path.join(FIX, f)))
        if f == 'espn_nba.json':
            events_fn(src)
        if f == 'supabase_games.json' and games_rows is not None:
            src = games_rows
        json.dump(src, open(os.path.join(fx, f), 'w'))
    return watch.Desk(cfg, {}, fx)


def set_game(espn, gid, **kw):
    ev = next(e for e in espn['events'] if e['id'] == gid)
    comp = ev['competitions'][0]
    if 'date' in kw:
        ev['date'] = kw['date']
    if 'status' in kw:
        ev['status'] = kw['status']
    for side in ('home', 'away'):
        if side in kw:
            c = next(x for x in comp['competitors'] if x['homeAway'] == side)
            c['score'] = str(kw[side][0]); c['linescores'] = [{'value': v} for v in kw[side][1]]
    return ev


# 2. MIA @ CHA: 31-31, "halftime", 44 minutes after the tip, one linescore each: nothing priced, nothing pushed
pushes.clear(); captured.clear()
clock_at('501', 44)
d = desk_with(lambda e: set_game(e, '501', status={'period': 2, 'displayClock': '0:00', 'type': {'state': 'in', 'name': 'STATUS_HALFTIME', 'shortDetail': 'Halftime'}},
                                 home=(31, [31]), away=(31, [31])))
d.run_pass()
rec = d.state['games']['501']
assert not rec.get('half') and not [p for p in pushes if '(half' in p[0]] and not [r for r in captured.get('suggestions', []) if r['game_id'] == '501'] and rec['phase'] == 'approaching', (rec.get('half'), rec.get('phase'), [p[0] for p in pushes])
# the same report an hour after the tip, with the second period's points on the board: the real half, priced as before
pushes.clear(); captured.clear()
clock_at('501', 72)
d = desk_with(lambda e: None)
d.run_pass()
rec = d.state['games']['501']
assert rec.get('half') == {'away': 58, 'home': 61} and rec['slots'] == {'half': 'play'} and len([p for p in pushes if '(half' in p[0]]) == 1, (rec.get('half'), rec.get('slots'), [p[0] for p in pushes])
print('breaks: the end of the first is not the half; the real half still prices')

# 3. GS @ PHX: period 3 at 0:00 sixteen minutes after the half was read, two linescores: the start of the third, not its end
pushes.clear(); captured.clear()
t = clock_at('503', 90)
d = desk_with(lambda e: set_game(e, '503', status={'period': 3, 'displayClock': '0:00', 'type': {'state': 'in', 'name': 'STATUS_IN_PROGRESS', 'shortDetail': '0:00 - 3rd'}},
                                 home=(57, [30, 27]), away=(54, [27, 27])))
d.state['games'] = {'503': dict(sport='nba', half=dict(away=54, home=57), half_at=(t - dt.timedelta(minutes=16)).isoformat(), slots={'half': 'play'})}
d.run_pass()
rec = d.state['games']['503']
assert not rec.get('third') and not [p for p in pushes if 'end of 3rd' in p[0]] and rec['phase'] == 'approaching3', (rec.get('third'), rec.get('phase'))
# the clock stuck at 0:00 while the third is played: a basket makes the period "played" but the time guard holds
pushes.clear(); captured.clear()
t = clock_at('503', 92)
d = desk_with(lambda e: set_game(e, '503', status={'period': 3, 'displayClock': '0:00', 'type': {'state': 'in', 'name': 'STATUS_IN_PROGRESS', 'shortDetail': '0:00 - 3rd'}},
                                 home=(59, [30, 27, 2]), away=(57, [27, 27, 3])))
d.state['games'] = {'503': dict(sport='nba', half=dict(away=54, home=57), half_at=(t - dt.timedelta(minutes=18)).isoformat(), slots={'half': 'play'})}
d.run_pass()
rec = d.state['games']['503']
assert not rec.get('third') and not [p for p in pushes if 'end of 3rd' in p[0]] and rec['phase'] == 'approaching3', (rec.get('third'), rec.get('phase'))
# called straight (the backup's path), the stage guard says why and prices nothing
d.evaluate_q3([x for x in d.games('nba') if x['id'] == '503'][0], rec)
assert not rec.get('third') and rec.get('noted_early_q3', '').startswith('end of 3rd reported 18 min'), rec.get('noted_early_q3')
# the real end of the third, 47 minutes after the half: priced and pushed as before
pushes.clear(); captured.clear()
t = clock_at('503', 121)
d = desk_with(lambda e: None)
d.state['games'] = {'503': dict(sport='nba', half=dict(away=55, home=58), half_at=(t - dt.timedelta(minutes=47)).isoformat(), slots={'half': 'play'})}
d.run_pass()
rec = d.state['games']['503']
assert rec.get('third') == {'away': 82, 'home': 85} and rec['slots'].get('q3') == 'play', (rec.get('third'), rec.get('slots'))
print('breaks: the start of the third is not its end, a stuck clock is not a break; the real end of the third still prices')

# 4. the break score is captured once: ESPN still shows the break but the score moved (57-59 after 54-57)
pushes.clear(); captured.clear()
t = clock_at('503', 121)
d = desk_with(lambda e: None)
d.state['games'] = {'503': dict(sport='nba', half=dict(away=55, home=58), half_at=(t - dt.timedelta(minutes=47)).isoformat(), slots={'half': 'play'})}
d.run_pass()
rec = d.state['games']['503']
n_rows = len(captured.get('suggestions', []))
g3 = copy.deepcopy([x for x in d.games('nba') if x['id'] == '503'][0])
g3['home']['score'] = 87; g3['home']['linescores'][2] = 29      # ESPN: still period 3, 0:00, score moved
d._db_evals.clear()
d.evaluate_q3(g3, rec)
assert rec['third'] == {'away': 82, 'home': 85} and rec.get('moved_q3') == {'away': 82, 'home': 87} and len(captured.get('suggestions', [])) == n_rows, (rec.get('third'), rec.get('moved_q3'))
print('breaks: the break score is taken once; a moved score stops the pricing')

# 5. the NBA never prices without a market center: the ladder centered 60 points from the score (the misread's signature)
pushes.clear(); captured.clear()
fx = tempfile.mkdtemp()
for f in os.listdir(FIX):
    src = json.load(open(os.path.join(FIX, f)))
    if f == 'espn_nba.json':
        set_game(src, '501', home=(31, [15, 16]), away=(31, [16, 15]))   # a "half" of 62 points against a 221.5 total
    json.dump(src, open(os.path.join(fx, f), 'w'))
clock_at('501', 72)
d = watch.Desk(cfg, {}, fx)
d.run_pass()
rec = d.state['games']['501']
assert rec.get('half') == {'away': 31, 'home': 31} and rec.get('noted_no_center') and not rec.get('slots') and not [r for r in captured.get('suggestions', []) if r['game_id'] == '501'], (rec.get('half'), rec.get('noted_no_center'), rec.get('slots'))
assert not [p for p in pushes if '(half' in p[0]], pushes
cfg_fb = dict(cfg, require_center=[])
d = watch.Desk(cfg_fb, {}, fx)
d.run_pass()
assert d.state['games']['501'].get('slots'), 'with the guard off the model alone still prices (football behaviour)'
print('breaks: no market center, no NBA pricing')
print('breaks: ok')
