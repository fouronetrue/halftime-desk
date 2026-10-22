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
import feeds, watch

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
print('match: same pair within 90 minutes, nothing else')

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
print('odds: ok')
