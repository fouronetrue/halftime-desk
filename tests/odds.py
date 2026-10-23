"""The Odds API feed, no network:
1. parse_odds_api: Pinnacle's close when it has both numbers, else the median across the books; the home spread
   is minus when the home team is favored; a book with neither market is skipped.
2. match_odds: the row whose teams and start match an ESPN game; nothing for a different day or a different pair.
3. Desk.odds_lines: no key means no call; a kickoff within three hours earns one call, not two; the closing read
   runs inside 25 minutes once 20 minutes have passed; the quota floor and the daily cap hold.
4. capture_pregame: the sharp line wins, ESPN's number and every book's stay beside it, and without a row ESPN's
   line is used as before."""
import sys, os, time, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import feeds, watch, engine

# 1. parsing
events = [
    dict(id='e1', commence_time='2026-10-25T17:00:00Z', home_team='Pittsburgh Steelers', away_team='Green Bay Packers', bookmakers=[
        dict(key='pinnacle', markets=[dict(key='spreads', outcomes=[dict(name='Pittsburgh Steelers', point=-2.5), dict(name='Green Bay Packers', point=2.5)]),
                                      dict(key='totals', outcomes=[dict(name='Over', point=45.5), dict(name='Under', point=45.5)])]),
        dict(key='draftkings', markets=[dict(key='spreads', outcomes=[dict(name='Pittsburgh Steelers', point=-3.0), dict(name='Green Bay Packers', point=3.0)]),
                                        dict(key='totals', outcomes=[dict(name='Over', point=46.0), dict(name='Under', point=46.0)])]),
        dict(key='fanduel', markets=[dict(key='h2h', outcomes=[dict(name='Pittsburgh Steelers', price=-140)])]),
    ]),
    dict(id='e2', commence_time='2026-10-25T20:25:00Z', home_team='Denver Broncos', away_team='Dallas Cowboys', bookmakers=[
        dict(key='draftkings', markets=[dict(key='spreads', outcomes=[dict(name='Denver Broncos', point=3.5), dict(name='Dallas Cowboys', point=-3.5)]),
                                        dict(key='totals', outcomes=[dict(name='Over', point=48.5), dict(name='Under', point=48.5)])]),
        dict(key='fanduel', markets=[dict(key='spreads', outcomes=[dict(name='Denver Broncos', point=3.0), dict(name='Dallas Cowboys', point=-3.0)]),
                                     dict(key='totals', outcomes=[dict(name='Over', point=49.0), dict(name='Under', point=49.0)])]),
        dict(key='betmgm', markets=[dict(key='spreads', outcomes=[dict(name='Denver Broncos', point=3.5), dict(name='Dallas Cowboys', point=-3.5)]),
                                    dict(key='totals', outcomes=[dict(name='Over', point=48.0), dict(name='Under', point=48.0)])]),
        dict(key='pinnacle', markets=[dict(key='totals', outcomes=[dict(name='Over', point=48.5), dict(name='Under', point=48.5)])]),
    ]),
    dict(id='e3', commence_time='2026-10-25T20:25:00Z', home_team='Nobody', away_team='Nothing', bookmakers=[]),
]
rows = feeds.parse_odds_api(events)
assert len(rows) == 2, rows
pit, den = rows
assert (pit['home_spread'], pit['total'], pit['source']) == (-2.5, 45.5, 'pinnacle'), pit
assert pit['books']['draftkings'] == (-3.0, 46.0) and 'fanduel' not in pit['books'], pit['books']
assert (den['home_spread'], den['total'], den['source']) == (3.5, 48.5, 'median4'), den     # Pinnacle had no spread: the median (its total still counts)
assert den['books']['pinnacle'] == (None, 48.5)
print('parse: Pinnacle first, median when Pinnacle is quiet, home spread minus when favored')

# 2. matching
def game(home, away, start, abbrs=('PIT', 'GB')):
    return dict(start_utc=start, sport='nfl', home=dict(name=home, abbr=abbrs[0]), away=dict(name=away, abbr=abbrs[1]))
assert feeds.match_odds(game('Pittsburgh Steelers', 'Green Bay Packers', '2026-10-25T17:00:00+00:00'), rows) is pit
assert feeds.match_odds(game('Pittsburgh Steelers', 'Green Bay Packers', '2026-10-25T17:30:00Z'), rows) is pit   # a half hour off is fine
assert feeds.match_odds(game('Pittsburgh Steelers', 'Green Bay Packers', '2026-10-26T17:00:00Z'), rows) is None  # a day off is not
assert feeds.match_odds(game('Denver Broncos', 'Green Bay Packers', '2026-10-25T17:00:00Z'), rows) is None        # wrong pair
assert feeds.match_odds(game('Ohio State Buckeyes', 'Penn State Nittany Lions', '2026-10-25T17:00:00Z'), rows) is None
assert feeds.match_odds(game('Pittsburgh Steelers', 'Green Bay Packers', None), rows) is None
# name forms: accents, the book's short names, and a school followed by a modifier is a different school
for a, b, want in [('San José State', 'San Jose State Spartans', 2), ('Massachusetts', 'UMass Minutemen', 2), ('App State', 'Appalachian State Mountaineers', 2),
                   ("Hawai'i", 'Hawaii Rainbow Warriors', 3), ('Miami (OH)', 'Miami (OH) RedHawks', 2), ('Miami', 'Miami (OH) RedHawks', 1),
                   ('Texas', 'Texas State Bobcats', 1), ('Texas', 'Texas Longhorns', 2), ('Louisiana', 'Louisiana Tech Bulldogs', 1),
                   ('Los Angeles Clippers', 'LA Clippers', 3), ('Oklahoma City Thunder', 'Oklahoma City Thunder', 3)]:
    assert abs(feeds.sim(a, b) - want) < 0.01, (a, b, feeds.sim(a, b))
print('match: same pair within 90 minutes, nothing else; accents and short names read, Texas is not Texas State')

# 3. the refresh policy
calls = []
def fake_lines(sport, key):
    calls.append(sport)
    return rows, dict(remaining=fake_lines.remaining, used=500 - fake_lines.remaining, last=2)
fake_lines.remaining = 300
feeds.odds_api_lines = fake_lines
cfg = watch.load_json(watch.CONFIG_PATH, {})
d = watch.Desk(cfg, {}, None)
now = time.time()
def pre_game(seconds_to_kick, gid='1'):
    start = dt.datetime.fromtimestamp(now + seconds_to_kick, dt.timezone.utc).replace(microsecond=0).isoformat()
    return dict(id=gid, sport='nfl', start_utc=start, state='pre', status='STATUS_SCHEDULED', period=0, clock='', clock_s=None, detail='',
                home=dict(name='Pittsburgh Steelers', abbr='PIT', score=0, linescores=[]), away=dict(name='Green Bay Packers', abbr='GB', score=0, linescores=[]),
                name='Green Bay Packers at Pittsburgh Steelers', short='GB @ PIT', date_et='2026-10-25', neutral=False, odds_details='PIT -3.0', over_under=46.0)
os.environ.pop('ODDS_API_KEY', None)
d.odds_lines('nfl', [pre_game(2 * 3600)])
assert calls == [], 'no key, no call'
os.environ['ODDS_API_KEY'] = 'test-key'
d.odds_lines('nfl', [pre_game(5 * 3600)])
assert calls == [], 'five hours out is too early'
d.odds_lines('nfl', [pre_game(2 * 3600)])
assert calls == ['nfl'] and d._odds_rows['nfl'] is rows and d.state['odds_api']['remaining'] == 300
d.odds_lines('nfl', [pre_game(2 * 3600)])
assert calls == ['nfl'], 'the early read is one call'
d.odds_lines('nfl', [pre_game(20 * 60)])
assert calls == ['nfl'], 'inside 25 minutes but the last call was seconds ago'
d.state['odds_api']['nfl']['at'] = now - 21 * 60
d.odds_lines('nfl', [pre_game(20 * 60)])
assert calls == ['nfl', 'nfl'], 'the closing read'
d.state['odds_api']['nfl']['at'] = now - 3 * 3600
d.state['odds_api']['remaining'] = 30
d.odds_lines('nfl', [pre_game(2 * 3600)])
assert calls == ['nfl', 'nfl'], 'under 40 credits only the closing read runs'
d.odds_lines('nfl', [pre_game(10 * 60)])
assert calls == ['nfl', 'nfl', 'nfl'], 'the closing read still runs under 40'
d.state['odds_api']['nfl']['at'] = now - 3 * 3600
d.state['odds_api']['remaining'] = 5
d.odds_lines('nfl', [pre_game(10 * 60)])
assert calls == ['nfl', 'nfl', 'nfl'], 'under 10 credits nothing runs'
d.state['odds_api']['remaining'] = 300
d.state['odds_api']['nfl'].update(calls=12, at=now - 3 * 3600)
d.odds_lines('nfl', [pre_game(10 * 60)])
assert calls == ['nfl', 'nfl', 'nfl'], 'twelve calls a day is the cap'
d.state['odds_api']['nfl'].update(calls=0, at=now - 3 * 3600)
def failing(sport, key):
    raise RuntimeError('HTTP 401')
feeds.odds_api_lines = failing
d.odds_lines('nfl', [pre_game(10 * 60)])
assert d.state['odds_api']['nfl'].get('failed_at'), 'a failed call is remembered'
feeds.odds_api_lines = fake_lines
d.odds_lines('nfl', [pre_game(10 * 60)])
assert calls == ['nfl', 'nfl', 'nfl'], 'twenty minutes of quiet after a failure'
print('policy: early read, closing read, quota floor, daily cap, back-off after a failure')

# 4. precedence in capture_pregame (the row's start moved onto the game's; Kalshi is not on the line here)
g = pre_game(2 * 3600)
pit['start_utc'] = g['start_utc']
d._odds_rows['nfl'] = rows
d.events = lambda sport, kind: []
rec = {}
d.capture_pregame(g, rec)
pre = rec['pre']
assert (pre['total'], pre['home_spread'], pre['source']) == (45.5, -2.5, 'odds:pinnacle'), pre
assert pre['espn'] == [-3.0, 46.0] and pre['books']['draftkings'] == [-3.0, 46.0], pre
d._odds_rows['nfl'] = []
rec2 = {}
d.capture_pregame(g, rec2)
assert (rec2['pre']['total'], rec2['pre']['home_spread'], rec2['pre']['source']) == (46.0, -3.0, 'espn'), rec2['pre']
assert 'books' not in rec2['pre']
print('pregame: the sharp line wins with ESPN kept beside it; ESPN alone otherwise')

# 5. the history pull: a historical snapshot parses to one 2H line per book; the event list matches on full names
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import odds_history as oh
snap = dict(id='h1', commence_time='2023-09-10T17:00:00Z', home_team='Washington Commanders', away_team='Arizona Cardinals', bookmakers=[
    dict(key='draftkings', markets=[dict(key='totals_h2', outcomes=[dict(name='Over', price=-110, point=20.5), dict(name='Under', price=-110, point=20.5)]),
                                    dict(key='totals', outcomes=[dict(name='Over', price=-105, point=41.5), dict(name='Under', price=-115, point=41.5)])]),
    dict(key='pinnacle', markets=[dict(key='totals_h2', outcomes=[dict(name='Over', price=-108, point=21.0), dict(name='Under', price=-104, point=21.0)])]),
    dict(key='fanduel', markets=[dict(key='spreads_h2', outcomes=[dict(name='Washington Commanders', price=-110, point=-1.5)])]),
])
books = oh.parse_h2(snap)
assert books == {'draftkings': [20.5, -110, -110], 'pinnacle': [21.0, -108, -104]}, books
assert oh.parse_h2({}) == {} and oh.parse_h2(None) == {}
row = dict(game_id='2023_01_ARI_WAS', kick_utc='2023-09-10T17:02:43.600Z', home_full='Washington Commanders', away_full='Arizona Cardinals')
evs = [dict(id='x', commence_time='2023-09-10T17:00:00Z', home_team='Washington Commanders', away_team='Arizona Cardinals'),
       dict(id='y', commence_time='2023-09-10T20:25:00Z', home_team='Washington Commanders', away_team='Arizona Cardinals'),
       dict(id='z', commence_time='2023-09-10T17:00:00Z', home_team='Washington Commanders', away_team='Dallas Cowboys')]
assert oh.match_event(row, evs)['id'] == 'x'
assert oh.match_event(dict(row, kick_utc='2023-09-10T20:30:00Z'), evs)['id'] == 'y'
assert oh.match_event(dict(row, away_full='Denver Broncos'), evs) is None
assert oh.iso_plus('2023-09-10T18:34:13.857Z', 7) == '2023-09-10T18:41:13Z'
api = oh.Api('k', 'nfl', max_credits=100, reserve=50)
assert api.allowed(10)
api.spent, api.remaining = 95, 1000
assert not api.allowed(10), 'the run budget'
api.spent, api.remaining = 0, 55
assert not api.allowed(10), 'the reserve for the live desk'
api.remaining = 60
assert api.allowed(10)
print('history: snapshot parsed per book, event matched by full names and start, budget and reserve hold')
# 6. the sharp second-half line at the half: read once, centered with sharp_model_pct, on the sheet and in the text;
#    the NBA keeps the market's weight; a bad read or no credits leaves the ladder where it was
h2_calls = []
def fake_h2(sport, event_id, key):
    h2_calls.append((sport, event_id))
    return {'draftkings': [24.5, -110, -110], 'fanduel': [25.0, -112, -108], 'pinnacle': [24.5, -106, -106]}, dict(remaining=fake_h2.remaining)
fake_h2.remaining = 9000
feeds.odds_api_h2 = fake_h2
os.environ['ODDS_API_KEY'] = 'test-key'
cfg = watch.load_json(watch.CONFIG_PATH, {})
d2 = watch.Desk(cfg, {}, None)
g2 = pre_game(0, gid='7')
rec = dict(pre=dict(total=46.0, home_spread=-3.0, source='espn', odds_event='ev-7'))
c, w, src = d2.market_center(g2, {}, 24, 'half', rec)
assert (c, w, src) == (24.5, 0.5, 'sharp'), (c, w, src)                 # Pinnacle's line, the model keeps 50
assert rec['h2']['source'] == 'pinnacle' and rec['h2']['n'] == 3 and h2_calls == [('nfl', 'ev-7')]
c, w, src = d2.market_center(g2, {}, 24, 'half', rec)
assert h2_calls == [('nfl', 'ev-7')], 'a second look inside four minutes is the cached one'
rec['h2']['at_s'] -= 300
d2.market_center(g2, {}, 24, 'half', rec)
assert len(h2_calls) == 2, 'one more read after four minutes'
rec['h2']['at_s'] -= 300
d2.market_center(g2, {}, 24, 'half', rec)
assert len(h2_calls) == 2, 'and never a third'
m = engine.HalfModel('nfl', 46.0, -3.0, 14, 10, center=c, center_w=w)
m0 = engine.HalfModel('nfl', 46.0, -3.0, 14, 10, center=c, center_w=0.0)
assert abs(m0.median - 24.5) < 1e-4 and abs(m.mu - (0.5 * m.mu_model + 0.5 * m0.mu)) < 1e-9     # the line is the median, the blend halfway
assert 'Book 2H 24.5.' in engine.describe(m, dict(away='GB', home='PIT', h1a=10, h1h=14, sharp=24.5), engine.price_lines(m, [44.5, 47.5], 'fg', 0.03), dict(singles=[], mids=[], revs=[]))
assert 'Book 2H' not in engine.describe(m, dict(away='GB', home='PIT', h1a=10, h1h=14), engine.price_lines(m, [44.5, 47.5], 'fg', 0.03), dict(singles=[], mids=[], revs=[]))
# the event id found at the half when the pregame line came from ESPN
rec3 = dict(pre=dict(total=46.0, home_spread=-3.0, source='espn'))
d2._odds_rows['nfl'] = rows
pit['start_utc'] = g2['start_utc']
assert d2.market_center(g2, {}, 24, 'half', rec3)[2] == 'sharp' and rec3['pre']['odds_event'] == 'e1'
# no event anywhere: the football ladder keeps the model's own center
rec4 = dict(pre=dict(total=46.0, home_spread=-3.0, source='espn'))
d2._odds_rows['nfl'] = []
assert d2.market_center(g2, {}, 24, 'half', rec4) == (None, 1.0, None)
# the NBA: the sharp line at the market's weight; without it, Kalshi's center as before
gn = dict(g2, sport='nba')
recn = dict(pre=dict(total=224.5, home_spread=-3.0, odds_event='ev-n'))
fake_h2_nba = lambda sport, event_id, key: ({'draftkings': [112.5, -110, -110]}, dict(remaining=9000))
feeds.odds_api_h2 = fake_h2_nba
assert d2.market_center(gn, {}, 110, 'half', recn) == (112.5, 0.0, 'sharp')     # the NBA: the sharp line is the center, the model only the shape
feeds.odds_api_h2 = fake_h2
# an empty read (no 2H line posted) falls through to Kalshi for the NBA and to the model for football
feeds.odds_api_h2 = lambda sport, event_id, key: ({}, dict(remaining=9000))
rec5 = dict(pre=dict(total=46.0, home_spread=-3.0, odds_event='ev-5'))
assert d2.market_center(g2, {}, 24, 'half', rec5) == (None, 1.0, None) and rec5['h2']['line'] is None
# a sharp line outside the plausible range is ignored
feeds.odds_api_h2 = lambda sport, event_id, key: ({'draftkings': [3.5, -110, -110]}, dict(remaining=9000))
rec6 = dict(pre=dict(total=46.0, home_spread=-3.0, odds_event='ev-6'))
assert d2.market_center(g2, {}, 24, 'half', rec6) == (None, 1.0, None)
# under ten credits nothing is read
feeds.odds_api_h2 = fake_h2
d2.state['odds_api'] = dict(remaining=5)
rec7 = dict(pre=dict(total=46.0, home_spread=-3.0, odds_event='ev-7b'))
assert d2.market_center(g2, {}, 24, 'half', rec7) == (None, 1.0, None) and 'h2' not in rec7
# the end of the third never asks
d2.state['odds_api'] = dict(remaining=9000)
rec8 = dict(pre=dict(total=224.5, home_spread=-3.0, odds_event='ev-8'))
before = len(h2_calls)
d2.market_center(gn, {}, 170, 'q3', rec8)
assert len(h2_calls) == before and 'h2' not in rec8
print('sharp: read once at the half, centered at the sport weight, on the text; NBA centered on the line itself; bad reads ignored')
print('odds: ok')
