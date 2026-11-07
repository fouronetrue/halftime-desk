"""The Georgia State read of Nov 7, 2026, replayed offline (claude/scorecard-readout-nov07.md): at the horn ESPN
carried Georgia State at 36 for one read of a 26-14 half. One read priced it (fair 75.5 against a ladder at 67,
no book line in hand) and pushed "over 70.5 at 38c"; a minute later ESPN read 26 and the desk went quiet. Four
guards now stand in the way, in order:
1. the break score must agree with the period scores (feeds.scores_add_up);
2. it is priced only after a second read of the scoreboard a few seconds later says the same (Desk.confirm_break);
3. nothing is priced while the model's own number sits further from Kalshi's line than config score_hold_pts
   (Desk.score_hold): the ladder is priced on the real score, so that gap is a wrong score, not an edge;
4. a score that goes down, or changes while ESPN still shows halftime within three minutes of the read, is a
   correction: the push on it is voided, a SCRATCH goes out, and the break is read again (Desk.scratch).
Plus the floor: no single under config single_min_price_c (40c) is a play; pairs keep the 15-85 band."""
import sys, os, copy, json, tempfile, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, feeds, store, notify, engine

FIX = os.path.join(ROOT, 'tests', 'fixtures_nba')
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = dict(watch.load_json(watch.CONFIG_PATH, {}), sports=['nba'])
assert cfg.get('single_min_price_c') == 40 and cfg.get('break_confirm_seconds') and (cfg.get('score_hold_pts') or {}).get('cfb') == 6, 'config.json: the Nov 7 guards'
pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': (pushes.append((title, body, priority)) or ['test'])
captured = {}
store.enabled = lambda: True
store.write = lambda table, rows, on_conflict=None, ignore_duplicates=False: captured.setdefault(table, []).extend(copy.deepcopy(rows)) or True
store.read = lambda table, params: []
store.claim = lambda table, row, on_conflict: True
ESPN0 = json.load(open(os.path.join(FIX, 'espn_nba.json')))
TIP = {e['id']: dt.datetime.fromisoformat(e['date'].replace('Z', '+00:00')) for e in ESPN0['events']}
feeds.clock_now = lambda: dt.datetime.now(dt.timezone.utc)   # real time: the fixture games are weeks old, so no break is too early, and the read stamps agree with the clock

# 1. the score must add up to the periods
g = dict(sport='cfb', state='in', status='STATUS_HALFTIME', period=2, clock_s=0, home=dict(score=14, linescores=[14, 0]), away=dict(score=26, linescores=[10, 16]))
assert feeds.half_score(g) == (26, 14)
g['away']['score'] = 36                                                     # the live number says 36, the quarters say 26
assert feeds.scores_add_up(g, 2) is False and feeds.half_score(g) is None, 'a score the quarters do not add to is not the half'
g['away']['linescores'] = [10]                                              # quarters not all listed: nothing to check against
assert feeds.scores_add_up(g, 2) is True
g3 = dict(sport='nba', state='in', status='STATUS_END_PERIOD', period=3, clock_s=0, home=dict(score=90, linescores=[30, 27, 29]), away=dict(score=82, linescores=[27, 27, 28]))
assert feeds.third_score(g3) is None and feeds.third_score(dict(g3, home=dict(score=86, linescores=[30, 27, 29]))) == (82, 86)
print('scratch: the score must agree with the period scores')

# 2. the floor: a single under 40c clears the edge and is still not a play; a pair may use the leg
rows = [dict(line=50.5, p_over=0.55, p_under=0.42, p_push=0.03), dict(line=54.5, p_over=0.30, p_under=0.68, p_push=0.02)]
quotes = {50.5: dict(y=35, n=66), 54.5: dict(y=20, n=80)}
sug = engine.suggest(rows, quotes, 'taker', 0.03, 1.0, 3000, 75, 225, (15, 85), None, single_band=(40, 85))
over = next(s for s in sug['singles'] if s['kind'] == 'over' and s['line'] == 50.5)
assert over['edge'] > 0.03 and not over['ok'] and over['floor'] and over['contracts'] == 0, over
assert all(not s['ok'] for s in sug['singles'] if s['price_c'] < 40), [s for s in sug['singles'] if s['ok']]
mid = next((m for m in sug['mids'] if m['a']['line'] == 50.5 and m['b']['line'] == 54.5), None)
assert mid is not None and mid['a']['price_c'] == 35, 'the 35c leg still builds a middle'
sug2 = engine.suggest(rows, quotes, 'taker', 0.03, 1.0, 3000, 75, 225, (15, 85), None)
assert next(s for s in sug2['singles'] if s['kind'] == 'over' and s['line'] == 50.5)['ok'], 'without a single band the 15-85 band decides'
print('scratch: the 40c floor on singles, pairs keep the band')


def desk_with(events_fn, state=None):
    fx = tempfile.mkdtemp()
    for f in os.listdir(FIX):
        src = json.load(open(os.path.join(FIX, f)))
        if f == 'espn_nba.json':
            events_fn(src)
        json.dump(src, open(os.path.join(fx, f), 'w'))
    return watch.Desk(cfg, state if state is not None else {}, fx)


def set_game(espn, gid, **kw):
    ev = next(e for e in espn['events'] if e['id'] == gid)
    comp = ev['competitions'][0]
    if 'status' in kw:
        ev['status'] = kw['status']
    for side in ('home', 'away'):
        if side in kw:
            c = next(x for x in comp['competitors'] if x['homeAway'] == side)
            c['score'] = str(kw[side][0]); c['linescores'] = [{'value': v} for v in kw[side][1]]
    return ev


# 3. the replay: BOS @ DET at the half, the home score carried ten too high (71 for 61, quarters agreeing), priced and pushed
pushes.clear(); captured.clear()
d = desk_with(lambda e: set_game(e, '501', home=(71, [30, 41]), away=(58, [27, 31])))
d.run_pass()
rec = d.state['games']['501']
assert rec.get('half') == {'away': 58, 'home': 71} and rec.get('break_read_at') and rec['slots'].get('half') in ('play', 'read'), (rec.get('half'), rec.get('slots'))
first = [p for p in pushes if '(half' in p[0]]
assert len(first) == 1 and 'Pistons 71' in first[0][0], [p[0] for p in pushes]
kind = rec['slots']['half']
# ESPN corrects it to 61 while the game still shows halftime: the push is void, a SCRATCH goes out, the break is re-armed
pushes.clear(); captured.clear()
d2 = desk_with(lambda e: None, d.state)
d2.run_pass()
rec = d2.state['games']['501']
sc = [p for p in pushes if p[0].startswith('SCRATCH')]
assert len(sc) == 1 and sc[0][2] == 'high' and 'Pistons 61' in sc[0][0] and '58-71' in sc[0][1] and 'sell it back' in sc[0][1], pushes
assert rec.get('scratched') and rec['scratched'][0]['bad'] == {'away': 58, 'home': 71} and rec['scratched'][0]['real'] == {'away': 58, 'home': 61} and rec['scratched'][0]['kind'] == kind
void = [a for a in captured.get('alerts', []) if a['game_id'] == '501' and a['slot'] == 'half']
assert void and void[-1]['sheet'].get('void', '').startswith('bad half score 58-71') and void[-1]['sheet']['lead'] == 'rest' and not void[-1]['sheet']['singles'], void
gr = watch.grade_sheet(void[-1]['sheet'], 230)
assert gr['n_plays'] == 0 and gr['pnl'] == 0 and gr['detail'].startswith('void (bad half score'), gr
# the same pass re-reads nothing (the scratch returns); the next pass prices the real half and pushes again
assert not rec.get('half') and not rec.get('slots') and 'play_sheet' not in rec and 'sheet' not in rec, (rec.get('half'), rec.get('slots'))
pushes.clear(); captured.clear()
d2.run_pass()
rec = d2.state['games']['501']
again = [p for p in pushes if '(half' in p[0]]
assert rec.get('half') == {'away': 58, 'home': 61} and rec['slots'].get('half') in ('play', 'read') and len(again) == 1 and 'Pistons 61' in again[0][0], (rec.get('half'), rec.get('slots'), [p[0] for p in pushes])
fresh = [a for a in captured.get('alerts', []) if a['game_id'] == '501' and a['slot'] == 'half']
assert fresh and not fresh[-1]['sheet'].get('void'), 'the fresh push replaces the void row'
print('scratch: a corrected score voids the push, sends a SCRATCH, and the real half still prices')

# 4. a score that goes up while ESPN shows halftime: a correction inside three minutes of the read, a moved score after
rec = d2.state['games']['501']
g = copy.deepcopy([x for x in d2.games('nba') if x['id'] == '501'][0])
g['home']['score'] = 64; g['home']['linescores'][1] = 33
assert d2.score_corrected(g, rec, 'half', (58, 64), rec['half']) is True
rec['break_read_at'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
assert d2.score_corrected(g, rec, 'half', (58, 64), rec['half']) is False, 'five minutes on, a higher score is a score'
assert d2.score_corrected(dict(g, status='STATUS_END_PERIOD', period=3), rec, 'q3', (58, 64), dict(away=58, home=61)) is False, 'a quarter break that sticks while the game plays on is not a correction (Oct 24)'
assert d2.score_corrected(dict(g, status='STATUS_END_PERIOD', period=3), rec, 'q3', (58, 60), dict(away=58, home=61)) is True, 'a score that goes down always is'
print('scratch: up within three minutes of the read is a correction, up later is a score, down always is a correction')

# 5. the second read: a scoreboard that says something else three seconds later prices nothing until the two agree
pushes.clear(); captured.clear()
d3 = desk_with(lambda e: set_game(e, '501', home=(71, [30, 41]), away=(58, [27, 31])))
calls = []
real_games = d3.games
def flaky(sport):
    gs = real_games(sport)
    calls.append(1)
    if len(calls) == 2:                                   # the confirming read: the real score this once
        for x in gs:
            if x['id'] == '501':
                x['home']['score'], x['home']['linescores'] = 61, [30, 31]
    return gs
d3.games = flaky
d3.run_pass()
rec = d3.state['games']['501']
assert not rec.get('half') and str(rec.get('noted_unconfirmed', '')).startswith('break score 58-71 not confirmed (second read 58-61)') and not [p for p in pushes if '(half' in p[0]], (rec.get('half'), rec.get('noted_unconfirmed'))
d3.run_pass()                                             # both reads say 71 now: priced (the fixture is wrong, but consistently so)
assert d3.state['games']['501'].get('half') == {'away': 58, 'home': 71}
print('scratch: one read is not a break')

# 6. the hold: the model's own number far from Kalshi's line prices nothing, whatever cleared
pushes.clear(); captured.clear()
d4 = desk_with(lambda e: None)
real_line = feeds.kalshi_total_line
feeds.kalshi_total_line = lambda ev: real_line(ev) + 12
try:
    d4.run_pass()
    rec = d4.state['games']['501']
    assert rec.get('half') == {'away': 58, 'home': 61} and not rec.get('slots') and str(rec.get('noted_hold', '')).startswith('model ') and 'holding' in rec.get('noted_hold', ''), (rec.get('slots'), rec.get('noted_hold'))
    assert not [p for p in pushes if '(half' in p[0]] and not [r for r in captured.get('suggestions', []) if r['game_id'] == '501']
finally:
    feeds.kalshi_total_line = real_line
d4.run_pass()                                             # the ladder back where it was: the hold lifts and the half prices
assert d4.state['games']['501'].get('slots', {}).get('half') in ('play', 'read')
print('scratch: the hold prices nothing while the model is far from the ladder')
print('scratch: ok')
