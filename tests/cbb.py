"""College basketball checks, no network:
1. The cbb model block loads and prices like the study says (scripts/fit_cbb.py): second half about
   8.0 + 0.428 x the total + 0.115 x the first-half points, sd 1.42 x sqrt(mu), calibrated; the football and NBA
   blocks price exactly as before.
2. ESPN's two-half forms: the half is the end of period 1 (STATUS_HALFTIME, or the second half at a full clock before
   the first basket), approaching under 5:00 of the first half, live through the second half with no second window,
   the end of the game never a break; the 35-minute floor on an early half; Kalshi's series and codes; the Odds API key.
3. The fixtures in tests/fixtures_cbb run end to end: the halftime game is priced off the games-table line with the
   50/50 center blend and pushed once as a shadow PLAY (silent, flagged, nothing counted against the day's cap); the
   second half at a full clock is priced as the half and pushed as a silent read; the live game and the pregame
   game are left alone; the final grades the shadow play apart from the live record.
4. The per-number rule for college middles (3.4c) is the same in held.py and the app; config.json carries the sport."""
import sys, os, re, json, csv, copy, math, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine, feeds, watch, notify, held

# 1. the model
m = engine.HalfModel('cbb', 150.5, -17.5, 41, 30)
c = engine.MODEL['cbb']['coef']
assert abs(m.mu_model - (c[0] + c[1] * 150.5 + c[2] * 71 + c[3] * 11 + c[4] * 11)) < 1e-6, m.mu_model
assert 78 < m.mu_model < 82 and abs(m.sd - 1.4226 * math.sqrt(m.mu)) < 1e-6, (m.mu_model, m.sd)
assert m.mu == m.mu_model and m.center is None and m.center_w == 1.0
assert 0.47 < m.p_over_2h(math.floor(m.mu) + 0.5) < 0.51, m.p_over_2h(math.floor(m.mu) + 0.5)
assert 0.18 < m.p_over_2h(math.floor(m.mu) + 10.5) < 0.22, m.p_over_2h(math.floor(m.mu) + 10.5)
assert 0.76 < m.p_over_2h(math.floor(m.mu) - 9.5) < 0.80, m.p_over_2h(math.floor(m.mu) - 9.5)
assert m.spot().startswith('no strong lean')
assert 'mismatch' in engine.HalfModel('cbb', 150.5, -24.5, 40, 36).spot(), 'a 20+ point favorite up 4 at the half is the mismatch spot'
assert 'fast first half' in engine.HalfModel('cbb', 140.5, -3.5, 42, 38).spot()
assert 'blowout' in engine.HalfModel('cbb', 150.5, -3.5, 50, 25).spot()
# the center blend: at weight 0 the ladder's median is the market line; at 50 the mean sits halfway
c0 = engine.HalfModel('cbb', 150.5, -17.5, 41, 30, center=81.5, center_w=0.0)
assert abs(c0.median - 81.5) < 1e-6 and abs(c0.p_over_2h(81.5) - 0.5) < 0.003, (c0.mu, c0.median)
c5 = engine.HalfModel('cbb', 150.5, -17.5, 41, 30, center=81.5, center_w=0.5)
assert abs(c5.mu - (0.5 * c5.mu_model + 0.5 * c0.mu)) < 1e-9 and c5.center_w == 0.5
nfl = engine.HalfModel('nfl', 55.5, -3.5, 7, 13)
assert (round(nfl.mu, 4), round(nfl.sd, 4)) == (round(engine.HalfModel('nfl', 55.5, -3.5, 7, 13, center=20.0, center_w=1.0).mu, 4), round(nfl.sd, 4)), 'football changed'
nba = engine.HalfModel('nba', 230.0, -5.5, 60, 55)
assert abs(nba.mu_model - (5.3 + 0.4738 * 230 + 0.0006 * 115 + 0.0007 * 5 + 0.0125 * 5)) < 0.01, 'the NBA block changed'
assert len(engine.MODEL['cbb']['z']) == 201 and engine.MODEL['cbb']['n'] == 38737 and engine.MODEL['cbb']['k'] == 1.4226
print(f"model: mu {m.mu:.1f}, sd {m.sd:.1f}, P(over fair+10) {100*m.p_over_2h(math.floor(m.mu) + 10.5):.0f}%; football and NBA unchanged")

# 2. feeds
g = dict(sport='cbb', state='in', status='STATUS_IN_PROGRESS', period=1, clock_s=feeds.parse_clock('12:00'))
assert feeds.phase(g) == 'live'
g['clock_s'] = feeds.parse_clock('4:59'); assert feeds.phase(g) == 'approaching'
g['clock_s'] = 0; assert feeds.phase(g) == 'approaching', 'the first half at 0:00 is still approaching until ESPN says halftime'
g.update(status='STATUS_HALFTIME', period=2); assert feeds.phase(g) == 'half'
g.update(status='STATUS_IN_PROGRESS', period=2, clock_s=feeds.parse_clock('20:00')); assert feeds.phase(g) == 'half', 'the second half at a full clock is still the half'
g['clock_s'] = feeds.parse_clock('19:40'); assert feeds.phase(g) == 'live'
g['clock_s'] = feeds.parse_clock('4:30'); assert feeds.phase(g) == 'live', 'the end of the game is not a break'
g['clock_s'] = 0; assert feeds.phase(g) == 'live'
g.update(period=3, clock_s=feeds.parse_clock('3:00')); assert feeds.phase(g) == 'live', 'overtime is live'
g.update(state='post', status='STATUS_FINAL'); assert feeds.phase(g) == 'post'
assert feeds.half_period('cbb') == 1 and feeds.half_period('nba') == 2 and feeds.half_period('nfl') == 2
half = dict(sport='cbb', state='in', status='STATUS_HALFTIME', period=2, clock_s=0, home=dict(score=41, linescores=[41]), away=dict(score=30, linescores=[30]))
assert feeds.half_score(half) == (30, 41)
h2 = dict(half, status='STATUS_IN_PROGRESS', period=2, clock_s=1200); assert feeds.half_score(h2) == (30, 41)
late = dict(half, status='STATUS_IN_PROGRESS', period=2, clock_s=700, home=dict(score=50, linescores=[41, 9]), away=dict(score=36, linescores=[30, 6]))
assert feeds.half_score(late) == (30, 41), 'after the half the first linescore is the half'
empty = dict(half, home=dict(score=0, linescores=[]), away=dict(score=0, linescores=[]))
assert feeds.half_score(empty) is None, 'no linescore for the first half is no evidence it was played'
import datetime as dt
now = dt.datetime(2026, 11, 2, 23, 40, tzinfo=dt.timezone.utc)
early = dict(sport='cbb', start_utc='2026-11-02T23:00:00+00:00')
assert feeds.break_too_early(early, {}, 'half', now) is None, 'a college half 40 minutes after the listed start is a half'
assert feeds.break_too_early(dict(early, sport='nba'), {}, 'half', now), 'an NBA half 40 minutes in is too early'
assert feeds.break_too_early(early, {}, 'half', now - dt.timedelta(minutes=10)), 'a college half 30 minutes in is too early'
nfl_g = dict(sport='nfl', state='in', status='STATUS_IN_PROGRESS', period=3, clock_s=feeds.parse_clock('14:20')); assert feeds.phase(nfl_g) == 'early3'
nba_g = dict(sport='nba', state='in', status='STATUS_IN_PROGRESS', period=3, clock_s=0); assert feeds.phase(nba_g) == 'q3end', 'the NBA keeps its windows'
assert feeds.ESPN['cbb'].endswith('/basketball/mens-college-basketball/scoreboard?groups=50&limit=400')
assert feeds.SERIES['cbb'] == {'total': 'KXNCAAMBTOTAL', 'spread': 'KXNCAAMBSPREAD'} and feeds.ODDS_SPORT['cbb'] == 'basketball_ncaab'
assert feeds.KALSHI_CODES['cbb']['TA&M'] == 'TXAM' and feeds.PERIOD_SECONDS['cbb'] == 1200
assert feeds.ticker_date('KXNCAAMBTOTAL-26NOV03WOFTENN') == ('2026-11-03', 'WOFTENN')
assert feeds.kalshi_url('KXNCAAMBTOTAL-26NOV03WOFTENN') == 'https://kalshi.com/markets/kxncaambtotal/event/kxncaambtotal-26nov03woftenn'
print('feeds: two halves, one window, the 35-minute floor, series and codes')

# 3. the fixtures run
FIX = os.path.join(ROOT, 'tests', 'fixtures_cbb')
pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None: (pushes.append((title, body, priority)) or ['test'])
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv'); watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = dict(watch.load_json(watch.CONFIG_PATH, {}), sports=['cbb'])
assert cfg.get('center_model_pct', {}).get('cbb') == 50, 'config.json: center_model_pct.cbb should be 50'
assert cfg.get('sharp_model_pct', {}).get('cbb') == 50
assert (cfg.get('play_push') or {}).get('cbb') == 'min' and cfg['read_push'].get('cbb') == 'min', 'the shadow week: silent pushes'
d = watch.Desk(cfg, {}, FIX)
d.run_pass()
rec = d.state['games']['601']
assert rec['phase'] == 'half' and rec['half'] == {'away': 30, 'home': 41}
assert rec['pre'] == dict(rec['pre'], total=150.5, home_spread=-17.5) and rec['pre'].get('restored'), 'line not restored from the games table'
assert rec['kalshi_total_event'] == 'KXNCAAMBTOTAL-26NOV02WOFTENN' and rec['center_src'] == 'kalshi'
sh = rec['sheet']
c0 = engine.HalfModel('cbb', sh['total'], sh['spread'], sh['h1h'], sh['h1a'], center=sh['center'], center_w=0.0)
assert sh['center'] == 152.5 - 71 and sh['center_w'] == 0.5 and abs(sh['mu'] - (0.5 * sh['mu_model'] + 0.5 * c0.mu)) < 0.02, (sh['mu'], sh['mu_model'], c0.mu)
assert sh['mkt'] == 152.5 and sh['fair'] == 151.5 and sh['kind'] == 'play' and sh['shadow'] is True, sh
halfp = [p for p in pushes if 'Terriers' in p[0]]
assert len(halfp) == 1 and halfp[0][0] == 'PLAY: Terriers 30, Volunteers 41 (half, CBB)' and halfp[0][2] == 'min', pushes
body = halfp[0][1]
assert body.startswith('SHADOW (not live yet, graded only)') and 'Buy OVER 140.5' in body and 'KXNCAAMBTOTAL-26NOV02WOFTENN' in body, body
assert rec['slots'] == {'half': 'play'} and not rec.get('counted_day') and not d.state.get('day_spend'), 'a shadow play never counts against the day cap'
assert not rec.get('pace') and not rec.get('spread_half'), 'the NBA-only reads stay NBA-only'
rec4 = d.state['games']['604']
assert rec4['phase'] == 'half' and rec4['half'] == {'away': 24, 'home': 33} and rec4['slots'] == {'half': 'read'}, (rec4.get('phase'), rec4.get('slots'))
readp = [p for p in pushes if 'Dragons' in p[0]]
assert len(readp) == 1 and readp[0][0].startswith('UPDATE: Dragons 24, Cavaliers 33 (half, CBB)') and readp[0][2] == 'min' and 'REST A MIDDLE' in readp[0][1], readp
assert rec4['sheet']['kind'] == 'update' and not rec4['sheet'].get('shadow')
rec3 = d.state['games']['603']
assert rec3['phase'] == 'live' and not rec3.get('half') and not rec3.get('sheet'), 'a game in its second half is never priced'
pre = d.state['games']['602']
assert pre['phase'] == 'pre' and pre['pre'].get('total') == 151.5 and pre['pre'].get('home_spread') == -25.5 and pre.get('kalshi_total_event') == 'KXNCAAMBTOTAL-26NOV02MANUK', pre
assert pre['mkt']['line'] == 151.5
assert len(pushes) == 2, [p[0] for p in pushes]
d._events = {}; d.run_pass()
assert len(pushes) == 2, 'a second pass pushes nothing new'
# the first basket of the second half stops the pricing
g1 = copy.deepcopy([x for x in d.games('cbb') if x['id'] == '601'][0])
g1.update(status='STATUS_IN_PROGRESS', period=2, clock='19:41', clock_s=1181); g1['home']['score'] = 43; g1['home']['linescores'].append(2)
assert feeds.phase(g1) == 'live' and feeds.half_score(g1) == (30, 41)
n_before = len(pushes); d.evaluate(g1, rec)
assert len(pushes) == n_before and rec.get('moved') == {'away': 30, 'home': 43}, 'priced after the score moved'
# the final grades the shadow play, marked, and the scorecard keeps it apart from the live plays
gf = copy.deepcopy(g1); gf.update(state='post', status='STATUS_FINAL', period=2, clock='0:00', clock_s=0); gf['home']['score'], gf['away']['score'] = 78, 66
gf['home']['linescores'], gf['away']['linescores'] = [41, 37], [30, 36]
d.settle(gf, rec)
rows = list(csv.DictReader(open(watch.RESULTS_PATH)))
assert len(rows) == 1 and rows[0]['sport'] == 'cbb' and rows[0]['final_total'] == '144' and rows[0]['plays'].startswith('shadow spot mismatch_hanging -1.0 shadow; over 140.5@70 W'), rows[0]
assert float(rows[0]['plays_pnl']) > 0 and rows[0]['q3_score'] == ''
sc = watch.scorecard(watch.RESULTS_PATH)
assert 'none with a play' in sc and 'shadow plays (not live, graded only): 1, $+' in sc and 'middles called' not in sc, sc
# the same final with the play live (no play_push block): counted as a play, the cap charged
pushes.clear()
d2 = watch.Desk(dict(cfg, play_push={}), {}, FIX); d2.run_pass()
livep = [p for p in pushes if 'Terriers' in p[0]]
assert len(livep) == 1 and livep[0][2] == 'high' and not livep[0][1].startswith('SHADOW'), livep
assert d2.state['games']['601']['counted_day'] and d2.state['day_spend'], 'a live play counts against the day cap'
assert not d2.state['games']['601']['sheet'].get('shadow')
print('fixtures: halftime game priced off the games-table line, centered on the ladder, one silent shadow PLAY graded apart; the second half at a full clock is the half; live and pregame games left alone')

# 4. the per-number rule in both places; the sport in the config
js = open(os.path.join(ROOT, 'app', 'lib', 'desk.js')).read()
mm = re.search(r"sport === 'cbb' \? (0\.\d+)", js)
assert mm and float(mm.group(1)) == held.PER_NUMBER['cbb'] == 0.034, 'college per-number rule differs between held.py and the app'
assert held.SPORT_OF['KXNCAAMBTOTAL'] == 'cbb'
assert "series.includes('NCAAMB') ? 'cbb'" in js, 'the app must read the college series before the NBA one'
cfg_file = watch.load_json(watch.CONFIG_PATH, {})
assert 'cbb' in cfg_file['sports'] and cfg_file['read_push'].get('cbb') == 'min' and cfg_file['play_push'].get('cbb') == 'min'
assert 'cbb' in cfg_file['sharp_model_pct'] and cfg_file['rest_near_pts'].get('cbb') == 6.0
print('cbb: ok')

# 5. the matcher needs both schools (Nov 4, 2026: Saint Mary-of-the-Woods at Southern Indiana was priced off the
# North Dakota St. vs Saint Mary's ladder on one exact side)
smwc = dict(sport='cbb', date_et='2026-11-04', away=dict(abbr='SMWC', name="Saint Mary-of-the-Woods Pomeroys", loc='Saint Mary-of-the-Woods', short="St Mary's"),
            home=dict(abbr='USI', name='Southern Indiana Screaming Eagles', loc='Southern Indiana', short='S Indiana'))
ndsu = dict(sport='cbb', date_et='2026-11-04', away=dict(abbr='NDSU', name='North Dakota State Bison', loc='North Dakota State', short='N Dakota St'),
            home=dict(abbr='SMC', name="Saint Mary's Gaels", loc="Saint Mary's", short="Saint Mary's"))
evs = [dict(event_ticker='KXNCAAMBTOTAL-26NOV04NDSUSMC', title="North Dakota St. vs Saint Mary's: Point Total")]
assert feeds.match_event(smwc, evs) is None, 'one exact school name is not a match'
assert feeds.match_event(ndsu, evs)['event_ticker'] == 'KXNCAAMBTOTAL-26NOV04NDSUSMC'
txst = dict(sport='cfb', date_et='2026-11-07', away=dict(abbr='TXST', name='Texas State Bobcats', loc='Texas State', short='Texas State'),
            home=dict(abbr='OU', name='Oklahoma Sooners', loc='Oklahoma', short='Oklahoma'))
assert feeds.match_event(txst, [dict(event_ticker='KXNCAAFTOTAL-26NOV07TEXOU', title='Texas vs Oklahoma: Total Points')]) is None, 'a school modifier is not a match'
utc = dict(sport='cbb', date_et='2026-11-05', away=dict(abbr='UTC', name='Chattanooga Mocs', loc='Chattanooga', short='Chattanooga'),
           home=dict(abbr='PSU', name='Penn State Nittany Lions', loc='Penn State', short='Penn State'))
assert feeds.match_event(utc, [dict(event_ticker='KXNCAAMBTOTAL-26NOV05CHATPSU', title='Chattanooga vs Penn St.: Point Total')])['event_ticker'].endswith('CHATPSU')
print('matcher: both schools or nothing')
