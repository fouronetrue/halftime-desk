"""NBA checks, no network:
1. The NBA model block loads and prices like the study says: second half about 5.3 + 0.474 x the total, sd
   1.29 x sqrt(mu), P(over) at fair+10 about 21 percent.
2. A market center blends in at center_model_pct (25 for the NBA): mu = 0.25 x model + 0.75 x center; the
   football models ignore the center (weight 1.0) and price exactly as before.
3. ESPN's NBA clock forms parse; the Q3 slot is the first 30 seconds; Kalshi's NBA codes match ESPN's.
4. The fixtures in tests/fixtures_nba run end to end: the halftime game is priced off the games-table line,
   centered on the ladder, pushed once as a PLAY, and the pregame game captures its line and its Kalshi event.
5. The per-number rule for NBA middles (2.9c) is the same in held.py and the app."""
import sys, os, re, json, tempfile, math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine, feeds, watch, notify, held

# 1. the model
m = engine.HalfModel('nba', 230.0, -5.5, 60, 55)
assert abs(m.mu_model - (5.3 + 0.4738 * 230 + 0.0006 * 115 + 0.0007 * 5 + 0.0125 * 5)) < 0.01, m.mu_model
assert m.mu == m.mu_model and m.center is None and m.center_w == 1.0
assert abs(m.sd - 1.2883 * math.sqrt(m.mu)) < 1e-6
assert 0.47 < m.p_over_2h(math.floor(m.mu) + 0.5) < 0.51, m.p_over_2h(math.floor(m.mu) + 0.5)
assert 0.19 < m.p_over_2h(math.floor(m.mu) + 10.5) < 0.23, m.p_over_2h(math.floor(m.mu) + 10.5)
assert 0.75 < m.p_over_2h(math.floor(m.mu) - 9.5) < 0.79, m.p_over_2h(math.floor(m.mu) - 9.5)
assert 'no lean' in m.spot()
assert 'blowout' in engine.HalfModel('nba', 230.0, -5.5, 70, 48).spot()
nfl = engine.HalfModel('nfl', 55.5, -3.5, 7, 13)
assert (round(nfl.mu, 2), round(nfl.sd, 2)) == (round(engine.HalfModel('nfl', 55.5, -3.5, 7, 13, center=20.0, center_w=1.0).mu, 2), round(nfl.sd, 2)), 'football changed'
print(f"model: mu {m.mu:.1f}, sd {m.sd:.1f}, P(over fair+10) {100*m.p_over_2h(math.floor(m.mu) + 10.5):.0f}%")

# 2. the center blend
c = engine.HalfModel('nba', 230.0, -5.5, 60, 55, center=111.5, center_w=0.25)
assert abs(c.mu - (0.25 * c.mu_model + 0.75 * 111.5)) < 1e-9 and c.center == 111.5 and c.center_w == 0.25
assert engine.HalfModel('nba', 230.0, -5.5, 60, 55, center=111.5, center_w=0.0).mu == 111.5
assert engine.HalfModel('nba', 230.0, -5.5, 60, 55, center=111.5, center_w=1.0).mu == c.mu_model
print('center: 25 percent model, 75 percent market')

# 3. feeds
for s, want in [('7:34', 454), ('7:34.0', 454), ('0:00', 0), ('45.3', 45), (':45.3', 45), ('0.0', 0), ('', None), ('end', None)]:
    assert feeds.parse_clock(s) == want, (s, feeds.parse_clock(s), want)
g = dict(sport='nba', state='in', status='STATUS_IN_PROGRESS', period=3, clock_s=feeds.parse_clock('11:40'))
assert feeds.phase(g) == 'live', 'the NBA has no early-Q3 slot; its second window is the end of the third'
g['clock_s'] = feeds.parse_clock('4:59'); assert feeds.phase(g) == 'approaching3'
g['clock_s'] = 0; assert feeds.phase(g) == 'q3end'
g.update(status='STATUS_END_PERIOD', clock_s=feeds.parse_clock('0.0')); assert feeds.phase(g) == 'q3end'
g.update(status='STATUS_IN_PROGRESS', period=4, clock_s=feeds.parse_clock('11:45')); assert feeds.phase(g) == 'early4'
g['clock_s'] = feeds.parse_clock('11:20'); assert feeds.phase(g) == 'live'
g.update(period=2, clock_s=feeds.parse_clock('4:59')); assert feeds.phase(g) == 'approaching'
nfl = dict(sport='nfl', state='in', status='STATUS_IN_PROGRESS', period=3, clock_s=feeds.parse_clock('14:20')); assert feeds.phase(nfl) == 'early3'
nfl.update(clock_s=0); assert feeds.phase(nfl) == 'live', 'football keeps its own phases'
assert feeds.ESPN['nba'].endswith('/basketball/nba/scoreboard') and feeds.SERIES['nba'] == {'total': 'KXNBATOTAL', 'spread': 'KXNBASPREAD'}
print('feeds: clock forms, the end-of-third window, series')

# 4. the fixtures run
FIX = os.path.join(ROOT, 'tests', 'fixtures_nba')
pushes = []
notify.push = lambda title, body, priority='default', tags='football': (pushes.append((title, body, priority)) or ['test'])
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv'); watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = dict(watch.load_json(watch.CONFIG_PATH, {}), sports=['nba'])
assert cfg.get('center_model_pct', {}).get('nba') == 25, 'config.json: center_model_pct.nba should be 25'
d = watch.Desk(cfg, {}, FIX)
d.run_pass()
rec = d.state['games']['501']
assert rec['pre'] == dict(rec['pre'], total=221.5, home_spread=-1.5) and rec['pre'].get('restored'), 'line not restored from the games table'
assert rec['kalshi_total_event'] == 'KXNBATOTAL-26OCT20BOSDET' and rec['half'] == {'away': 58, 'home': 61}
sh = rec['sheet']
assert sh['center'] == 111.5 and sh['center_w'] == 0.25 and abs(sh['mu'] - (0.25 * sh['mu_model'] + 0.75 * 111.5)) < 0.02, sh
assert sh['mkt'] == 230.5 and sh['fair'] == 229.5, sh
halfp = [p for p in pushes if '(half' in p[0]]
assert len(halfp) == 1 and halfp[0][0] == 'PLAY: Celtics 58, Pistons 61 (half, NBA)' and halfp[0][2] == 'high', pushes
body = halfp[0][1]
assert body.index('MIDDLE (clears') < body.index('SINGLE') and 'RESTING MIDDLE' in body and 'WIDER MIDDLE' in body, body
assert 'Buy OVER 236.5' in body and 'No lean' in body, body
assert sh['mid'] and sh['rest_mid'] is None, 'a cleared middle is graded as the play; the resting what-if belongs to an UPDATE'
assert rec['slots'] == {'half': 'play'}
assert rec['pace'] and rec['pace']['poss'] == round(((49 - 7 + 7 + 0.44 * 9) + (47 - 5 + 8 + 0.44 * 10)) / 2, 2) and rec['pace']['home']['fouls'] == 10, rec.get('pace')
assert sh['pace']['poss'] == rec['pace']['poss'], 'the sheet should carry the first-half box'
spm = rec['spread_half']
assert spm['half_home_margin'] == 3 and spm['pregame_home_spread'] == -1.5 and spm['mkt_home_spread'] is not None and spm['event_ticker'] == 'KXNBASPREAD-26OCT20BOSDET', spm
mm, nv = engine.expected_margin('nba', -1.5, 61, 58)
assert (spm['model_home_margin'], spm['naive_home_margin']) == (mm, nv) and abs(nv - 3.75) < 1e-9 and abs(mm - (3 + (-0.52 + 0.614 * 1.5 - 0.268 * 3))) < 0.01, spm
assert -4 <= spm['mkt_home_spread'] <= -2, spm   # the fixture ladder has Detroit by about 2.8
assert sh['spread_half'] == spm
# the shrink, both ways: a favorite down 15 wins the second half by about 7, a favorite up 20 loses it by about 1.5
m_down, _ = engine.expected_margin('nba', -5.0, 40, 55); m_up, _ = engine.expected_margin('nba', -5.0, 60, 40)
assert abs((m_down + 15) - (-0.52 + 0.614 * 5 + 0.268 * 15)) < 0.01 and 6 < m_down + 15 < 8, m_down
assert -3.5 < m_up - 20 < -0.5, m_up
m_big, _ = engine.expected_margin('nba', -5.0, 70, 40)
assert m_big - 30 == m_up - 20 + (22 - 20) * -0.268 + 0 or abs((m_big - 30) - (-0.52 + 0.614 * 5 - 0.268 * 22)) < 0.01, m_big
assert engine.expected_margin('nfl', -3.5, 7, 13) == (None, None)
assert feeds.parse_box_stats({}) is None and feeds.parse_box_stats({'boxscore': {'teams': [{'homeAway': 'home', 'statistics': []}]}}) is None
pre = d.state['games']['502']
assert pre['pre'].get('total') == 231.5 and pre['pre'].get('home_spread') == -5.5 and pre.get('kalshi_total_event') == 'KXNBATOTAL-26OCT20PHINYK', pre
assert pre['mkt']['line'] == 231.5
# a second pass pushes nothing new (one push for the half game, one for the end-of-third game, see 6 below)
d._events = {}; d.run_pass()
assert len(pushes) == 2, [p[0] for p in pushes]
# the same ladder with the stale strike repaired: an UPDATE that still leads with middles
import json, shutil
fix = json.load(open(os.path.join(FIX, 'kalshi_KXNBATOTAL.json')))
for mk in fix['events'][0]['markets']:
    if mk['floor_strike'] == 236.5:
        mk['yes_bid_dollars'], mk['yes_ask_dollars'], mk['no_bid_dollars'], mk['no_ask_dollars'] = '0.3200', '0.3400', '0.6600', '0.6800'
clean = tempfile.mkdtemp()
for f in os.listdir(FIX):
    shutil.copy(os.path.join(FIX, f), clean)
json.dump(fix, open(os.path.join(clean, 'kalshi_KXNBATOTAL.json'), 'w'))
pushes.clear()
d = watch.Desk(cfg, {}, clean); d.run_pass()
halfp = [p for p in pushes if '(half' in p[0]]
assert len(halfp) == 1 and halfp[0][0].startswith('UPDATE: Celtics 58, Pistons 61') and halfp[0][2] == 'default', pushes
body = halfp[0][1]
assert 'No single or middle clears' in body and 'Closest middle at the asks' in body and 'RESTING MIDDLE' in body and 'WIDER MIDDLE' in body, body
assert ' shares for $' in body and body.count('Buy OVER') == 2 and body.count('Buy UNDER') == 2, body
sh = d.state['games']['501']['sheet']
assert sh['rest_mid']['b_line'] - sh['rest_mid']['a_line'] < 6 <= sh['rest_mid_wide']['b_line'] - sh['rest_mid_wide']['a_line'], (sh['rest_mid'], sh['rest_mid_wide'])
assert f"Buy OVER {sh['rest_mid']['a_line']:.1f} at {sh['rest_mid']['a_price']}c ({sh['rest_mid']['pairs']} shares" in body, 'the graded resting middle must be the one the push posted first'
print('middles: PLAY leads with the middle, UPDATE carries the closest middle and a tight and a wide resting middle')
print('fixtures: halftime game priced off the games-table line, centered on the ladder, one PLAY, first-half box and spread ladder kept; pregame game captured (NY matched NYK)')

# 6. the end-of-third window: OKC at SA, 82-85 after three, priced off the games-table line with the end-of-third model,
# pushed once as slot q3, and graded next to the half on the results row
pushes.clear()
d = watch.Desk(cfg, {}, FIX); d.run_pass()
rec3 = d.state['games']['503']
assert rec3['third'] == {'away': 82, 'home': 85} and rec3.get('sheet_q3') and rec3['slots'].get('q3') == 'play', (rec3.get('third'), rec3.get('slots'))
p3 = [p for p in pushes if 'end of 3rd' in p[0]]
assert len(p3) == 1 and p3[0][0] == 'PLAY: Thunder 82, Spurs 85 (end of 3rd, NBA)' and p3[0][2] == 'high' and 'first timeout of the 4th' in p3[0][1], p3
assert 'Buy OVER 230.5 at 15c' in p3[0][1] and 'overtime 9%' in p3[0][1] and 'RESTING MIDDLE' in p3[0][1], p3[0][1]
sh3 = rec3['sheet_q3']
assert sh3['stage'] == 'q3' and sh3['h1a'] == 82 and sh3['h1h'] == 85 and sh3['fair'] and sh3['mkt'] == 223.5 and sh3['center'] == 223.5 - 167, sh3
assert abs(sh3['mu'] - (0.25 * sh3['mu_model'] + 0.75 * sh3['center'])) < 0.02
m3 = engine.LateModel('nba', 229.5, -1.5, 85, 82)
assert m3.p_ot == 0.089 and 'close game' in m3.spot() and abs(m3.mu_model - (m3.mu_reg_model + 0.089 * 24.3)) < 1e-9
assert 0.17 < m3.p_over_2h(math.floor(m3.median) + 10.5) < 0.21 and m3.sd > engine.LateModel('nba', 229.5, -1.5, 105, 72).sd + 1.5, 'the overtime tail widens a close game'
# a second pass pushes nothing new; a basket in the first seconds of the 4th stops the pricing
d._events = {}; d.run_pass(); assert len([p for p in pushes if 'end of 3rd' in p[0]]) == 1
import copy
g3 = copy.deepcopy([x for x in d.games('nba') if x['id'] == '503'][0])
g3.update(status='STATUS_IN_PROGRESS', period=4, clock='11:50', clock_s=710); g3['home']['score'] = 87; g3['home']['linescores'].append(2)
assert feeds.phase(g3) == 'early4' and feeds.third_score(g3) == (82, 85)
n_before = len(pushes); d.evaluate_q3(g3, rec3)
assert len(pushes) == n_before and rec3.get('moved_q3') == {'away': 82, 'home': 87}, 'priced after the score moved'
# the final grades the half and the end of the third on one row, after upgrading an old-format results.csv
import csv
with open(watch.RESULTS_PATH, 'w', newline='') as f:
    w = csv.writer(f); w.writerow(watch.RESULTS_COLUMNS[:20]); w.writerow(['2026-10-20T00:00:00+00:00', 'nfl', 'A @ B', '2026-10-19', '7-3', 45.5, -3.0, 44.5, 45.5, 'A 20, B 21', 41, 3.5, 4.5, 1, 50, -50, '', 'over 44.5@55 L -50', '', ''])
gf = copy.deepcopy(g3); gf.update(state='post', status='STATUS_FINAL', period=4, clock='0:00', clock_s=0); gf['home']['score'], gf['away']['score'] = 112, 108
gf['home']['linescores'], gf['away']['linescores'] = [28, 30, 27, 27], [26, 29, 27, 26]
d.settle(gf, rec3)
rows = list(csv.DictReader(open(watch.RESULTS_PATH)))
assert len(rows) == 2 and rows[0]['q3_score'] == '' and rows[0]['plays_pnl'] == '-50', rows[0]
r = rows[1]
assert r['half'] == '' and r['q3_score'] == '82-85' and r['final_total'] == '220' and float(r['q3_plays_cost']) > 0 and r['q3_plays'].startswith('mid 230.5/232.5 miss') or r['q3_plays'].startswith('over 230.5@15 L'), r
assert rec3['settled']['q3_plays_pnl'] is not None and rec3['settled']['plays_pnl'] is None
sc = watch.scorecard(watch.RESULTS_PATH)
assert 'end of 3rd (NBA): 1 graded, 1 with a play' in sc, sc
print('end of 3rd: priced, pushed once, stopped at the first basket, graded in the q3 columns next to an upgraded CSV header')

# 5. the per-number rule in both places
js = open(os.path.join(ROOT, 'app', 'lib', 'desk.js')).read()
mm = re.search(r"sport === 'nba' \? (0\.\d+)", js)
assert mm and float(mm.group(1)) == held.PER_NUMBER['nba'] == 0.029, 'NBA per-number rule differs between held.py and the app'
assert held.SPORT_OF['KXNBATOTAL'] == 'nba'
cfg_file = watch.load_json(watch.CONFIG_PATH, {})
assert 'nba' in cfg_file['sports'] and cfg_file['read_push'].get('nba')
assert len(engine.MODEL['nba']['z']) == 201 and engine.MODEL['nba']['n'] == 12849
print('nba: ok')
