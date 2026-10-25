"""The NFL bad-weather haircut (tail study, Oct 24): the venue lookup, the Open-Meteo parse, the call, the shift
through HalfModel and the push line. No network: fixtures and hand-built responses only."""
import sys, os, json, math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine, weather, feeds

CFG = dict(pts=-1.0, wind_mph=16, precip_in=0.01)

# 1. venues: home stadium by ESPN abbreviation, neutral sites by name, unknown -> None
g = dict(id='1', home=dict(abbr='PIT'), neutral=False, venue=dict(name='Acrisure Stadium', indoor=False))
assert weather.venue_for(g)[0] == 'Acrisure Stadium' and weather.venue_for(g)[3] == 'outdoors'
assert weather.venue_for(dict(id='2', home=dict(abbr='DET'), neutral=False))[3] == 'dome'
assert weather.venue_for(dict(id='3', home=dict(abbr='DAL'), neutral=False))[3] == 'retractable'
assert weather.venue_for(dict(id='4', home=dict(abbr='JAX'), neutral=True, venue=dict(name='Tottenham Hotspur Stadium')))[0] == 'Tottenham Hotspur Stadium'
assert weather.venue_for(dict(id='5', home=dict(abbr='JAX'), neutral=True, venue=dict(name='Somewhere New'))) is None
assert weather.venue_for(dict(id='6', home=dict(abbr='XXX'), neutral=False)) is None
assert weather.venue_for(dict(id='7', home=dict(abbr='PIT'), neutral=False, venue=dict(name='Acrisure Stadium', indoor=True)))[3] == 'dome', 'ESPN indoor wins over the table'
for abbr, (nm, lat, lon, roof) in weather.STADIUMS.items():
    assert -90 < lat < 90 and -180 < lon < 180 and roof in ('outdoors', 'dome', 'retractable'), abbr
print('weather: venues')

# 2. the parse and the call
def obs(**kw):
    cur = dict(time='2026-10-25T18:00', temperature_2m=50.0, precipitation=0.0, rain=0.0, showers=0.0, snowfall=0.0, wind_speed_10m=8.0, wind_gusts_10m=12.0, weather_code=2)
    cur.update(kw)
    return weather.parse(dict(current=cur))
assert weather.parse({}) is None and weather.parse(dict(current={})) is None
o = obs()
assert o['temp_f'] == 50.0 and o['wind_mph'] == 8.0 and o['precip_in'] == 0.0 and o['code'] == 2
assert weather.judge(o, 'outdoors', CFG) == (False, 'dry, 8 mph')
assert weather.judge(obs(precipitation=0.03, rain=0.03, weather_code=61), 'outdoors', CFG) == (True, 'rain')
assert weather.judge(obs(snowfall=0.2, weather_code=73), 'outdoors', CFG) == (True, 'snow')
assert weather.judge(obs(wind_speed_10m=16.0), 'outdoors', CFG) == (True, '16 mph wind')
assert weather.judge(obs(wind_speed_10m=15.9), 'outdoors', CFG)[0] is False, 'under 16 is not windy'
assert weather.judge(obs(precipitation=0.1, rain=0.1, wind_speed_10m=22.0, weather_code=63), 'outdoors', CFG) == (True, 'rain, 22 mph wind')
assert weather.judge(obs(weather_code=80), 'outdoors', CFG) == (True, 'rain'), 'a shower code counts even before the gauge moves'
assert weather.judge(obs(precipitation=0.5, rain=0.5, wind_speed_10m=30, weather_code=65), 'dome', CFG) == (False, 'dome')
assert weather.judge(obs(precipitation=0.5, rain=0.5, wind_speed_10m=30, weather_code=65), 'retractable', CFG) == (False, 'roof'), 'a roof never gets the haircut'
assert weather.judge(obs(wind_speed_10m=None), 'outdoors', CFG) == (False, 'dry')
print('weather: parse and judge')

# 3. for_game under fixtures: the BUF @ LAR fixture (SoFi, a dome) and the same reading at an open-air stadium
FIX = os.path.join(ROOT, 'tests', 'fixtures')
games = feeds.parse_espn(json.load(open(os.path.join(FIX, 'espn_nfl.json'))), 'nfl')
g401 = next(x for x in games if x['id'] == '401')
assert 'venue' in g401, 'parse_espn keeps the venue'
wx = weather.for_game(g401, CFG, FIX)
assert wx and wx['roof'] == 'dome' and wx['bad'] is False and wx['shift'] == 0.0 and wx['wind_mph'] == 18.3, wx
g_open = dict(g401, home=dict(g401['home'], abbr='BUF'))
wx2 = weather.for_game(g_open, CFG, FIX)
assert wx2 and wx2['roof'] == 'outdoors' and wx2['bad'] and wx2['why'] == 'rain, 18 mph wind' and wx2['shift'] == -1.0, wx2
assert weather.for_game(dict(g401, id='402'), CFG, FIX) is None, 'no fixture file: no reading'
assert weather.for_game(g401, None, FIX) is None, 'no config block: nothing read'
assert weather.text(wx) is None and weather.text(wx2) == 'Weather: rain, 18 mph wind. Model -1.0.'
print('weather: for_game on fixtures')

# 4. the shift through HalfModel: the model's own mean moves by the shift, the blend by its share
m0 = engine.HalfModel('nfl', 44.5, -3.0, 10, 7)
m1 = engine.HalfModel('nfl', 44.5, -3.0, 10, 7, shift=-1.0)
assert abs((m0.mu_model - m1.mu_model) - 1.0) < 1e-9 and abs((m0.mu - m1.mu) - 1.0) < 1e-9
assert m1.sd < m0.sd, 'sd follows the mean (k sqrt(mu))'
assert m1.p_over_2h(24.5) < m0.p_over_2h(24.5)
c0 = engine.HalfModel('nfl', 44.5, -3.0, 10, 7, center=24.5, center_w=0.5)
c1 = engine.HalfModel('nfl', 44.5, -3.0, 10, 7, center=24.5, center_w=0.5, shift=-1.0)
assert abs((c0.mu - c1.mu) - 0.5) < 1e-9, 'with the sharp line at half weight the blended number moves half a point'
assert engine.HalfModel('nfl', 44.5, -3.0, 10, 7, shift=0.0).mu == m0.mu and engine.HalfModel('nfl', 44.5, -3.0, 10, 7).shift == 0.0
# the floor still holds
lo = engine.HalfModel('nfl', 24.0, -3.0, 0, 0, shift=-30.0)
assert lo.mu_model == 8.0
print('weather: HalfModel shift')

# 5. the push line sits on the Fair line
rows = engine.price_lines(m1, [38.5, 41.5, 44.5, 47.5])
quotes = {l: dict(y=50, n=52) for l in (38.5, 41.5, 44.5, 47.5)}
sug = engine.suggest(rows, quotes, margin=0.03, trust=0.5, bankroll=3000, max_risk=75, max_cost=225)
sizing = dict(bankroll=3000, max_risk=75, max_cost=225, margin=0.03, mid_loss=15)
kind, head, body = engine.order_sheet(m1, dict(away='BUF', home='LAR', h1a=7, h1h=13, sharp=24.5, weather=weather.text(wx2)), rows, sug, sizing)
assert body.split('\n')[0] == f"Fair {engine.fair_line(m1):.1f}. Book 44.5. Weather: rain, 18 mph wind. Model -1.0.", body.split('\n')[0]
kind, head, body = engine.order_sheet(m1, dict(away='BUF', home='LAR', h1a=7, h1h=13, sharp=24.5, weather=None), rows, sug, sizing)
assert 'Weather' not in body
print('weather: push line')
print('weather: ok')

# 6. through the desk, offline: BUF @ LAR at the half reads the fixture (SoFi: a dome, no haircut), the record and
# the suggestions row carry the reading, and a second pass inside 45 minutes does not read again
import copy, tempfile
import watch, store, notify
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv')
watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = watch.load_json(watch.CONFIG_PATH, {})
assert cfg['weather']['nfl'] == dict(pts=-1.0, wind_mph=16, precip_in=0.01), cfg['weather']
cfg['sports'] = ['nfl']
pushes = []
notify.push = lambda title, body, priority='default', tags='football', url=None, url_title='Open market': (pushes.append((title, body)) or ['test'])
captured = {}
store.enabled = lambda: True
store.write = lambda table, rows, on_conflict=None, ignore_duplicates=False: captured.setdefault(table, []).extend(copy.deepcopy(rows)) or True
store.read = lambda table, params: []
store.claim = lambda table, row, on_conflict: True
d = watch.Desk(cfg, {}, FIX)
d.run_pass()
rec = d.state['games']['401']
assert rec.get('weather') and rec['weather']['roof'] == 'dome' and rec['weather']['bad'] is False and rec['weather']['shift'] == 0.0, rec.get('weather')
row = captured['suggestions'][0]
assert row['weather'] == rec['weather'] and row['mu_model'] == round(engine.HalfModel('nfl', 55.5, -3.5, 7, 13).mu_model, 2), 'no haircut in a dome'
assert 'Weather' not in pushes[0][1]
calls = []
weather.for_game = lambda *a, **k: calls.append(1)
d._db_evals.clear()
d.evaluate(d.games('nfl')[0], rec)
assert not calls, 'a reading under 45 minutes old is reused'
rec['weather']['at'] = '2026-01-01T00:00:00+00:00'
d._db_evals.clear()
d.evaluate(d.games('nfl')[0], rec)
assert calls, 'a stale reading is refreshed'
print('weather: through the desk on fixtures')
# the open-air case through the desk: same fixture reading at Highmark (rain, 18 mph) takes a point off the model
weather.for_game = lambda g, c, f=None: dict(at=watch.now_iso(), venue='Highmark Stadium', roof='outdoors', temp_f=48.2, precip_in=0.04, snow_in=0.0, wind_mph=18.3, gust_mph=27.0, code=61, obs_at='x', bad=True, why='rain, 18 mph wind', shift=-1.0)
captured.clear(); pushes.clear()
d = watch.Desk(cfg, {}, FIX)
d.run_pass()
row = captured['suggestions'][0]
assert row['mu_model'] == round(engine.HalfModel('nfl', 55.5, -3.5, 7, 13).mu_model - 1.0, 2), row['mu_model']
assert pushes and pushes[0][1].split('\n')[0].endswith('Weather: rain, 18 mph wind. Model -1.0.'), pushes[0][1].split('\n')[0]
assert row['weather']['bad'] and row['weather']['shift'] == -1.0
print('weather: the haircut reaches the number and the push')
print('weather: ok')
