"""Schedule and travel: back-to-backs, games in a tight window, road trips, miles, rest advantage. Do they move
the second half beyond the pregame total, and beyond the market's own 2H line?"""
import csv, math, os, datetime as dt
import numpy as np
rows = list(csv.DictReader(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'nba_games.csv'))))
LOC = dict(atl=(33.757, -84.396), bkn=(40.683, -73.975), bos=(42.366, -71.062), cha=(35.225, -80.839), chi=(41.881, -87.674), cle=(41.496, -81.688),
           dal=(32.790, -96.810), den=(39.749, -105.008), det=(42.341, -83.055), gs=(37.768, -122.388), hou=(29.751, -95.362), ind=(39.764, -86.156),
           lac=(34.043, -118.267), lal=(34.043, -118.267), mem=(35.138, -90.051), mia=(25.781, -80.187), mil=(43.045, -87.917), min=(44.979, -93.276),
           no=(29.949, -90.082), ny=(40.751, -73.994), okc=(35.463, -97.515), orl=(28.539, -81.384), phi=(39.901, -75.172), phx=(33.446, -112.071),
           por=(45.532, -122.667), sa=(29.427, -98.438), sac=(38.580, -121.500), tor=(43.643, -79.379), utah=(40.768, -111.901), wsh=(38.898, -77.021))
def loc(team, season):
    if team == 'okc' and season == 2008:
        return (47.622, -122.354)   # Seattle
    return LOC[team]
def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))

G = []
for r in rows:
    g = dict(date=dt.date.fromisoformat(r['date']), season=int(r['season']), playoffs=int(r['playoffs']), away=r['away'], home=r['home'],
             h1a=int(r['h1a']), h1h=int(r['h1h']), fa=int(r['fa']), fh=int(r['fh']), ot=int(r['ota']) + int(r['oth']),
             total=float(r['total']), home_spread=float(r['home_spread']), L=float(r['h2_total']) if r['h2_total'] else None)
    g['h1'] = g['h1a'] + g['h1h']; g['h2'] = g['fa'] + g['fh'] - g['h1']
    g['h2a'] = g['fa'] - g['h1a']; g['h2h'] = g['fh'] - g['h1h']
    hfb = -g['home_spread']; g['fav_by'] = abs(hfb); m1 = g['h1h'] - g['h1a']; g['favm'] = m1 if hfb >= 0 else -m1
    G.append(g)
G.sort(key=lambda g: g['date'])
# per-team schedule state, regular season only (playoff series are their own rhythm)
last = {}    # (season, team) -> dict(date, loc, road_streak, trip_miles, dates list)
for g in G:
    for side, team in (('a', g['away']), ('h', g['home'])):
        key = (g['season'], team)
        st = last.get(key)
        here = loc(g['home'], g['season'])
        if st is None:
            rest, g7, travel, streak, trip = 7, 0, 0.0, 0, 0.0
        else:
            rest = (g['date'] - st['date']).days
            g7 = sum(1 for d in st['dates'] if 0 < (g['date'] - d).days <= 7)
            travel = miles(st['loc'], here)
            streak = st['streak'] + 1 if side == 'a' else 0
            trip = (st['trip'] + travel) if side == 'a' else 0.0
        g[side + '_rest'] = min(rest, 7); g[side + '_g7'] = g7; g[side + '_travel'] = travel; g[side + '_streak'] = streak; g[side + '_trip'] = trip
        g[side + '_prev_streak'] = st['streak'] if st else 0
        dates = (st['dates'] if st else []) + [g['date']]
        last[key] = dict(date=g['date'], loc=here, streak=streak, trip=trip, dates=dates[-10:])
reg = [g for g in G if g['playoffs'] == 0]
train = [g for g in reg if g['season'] >= 2013]
# base model: the engine shape, so residuals are what the desk would miss
X = lambda gs: np.array([[1.0, g['total'], g['h1'], abs(g['favm']), g['favm'], (g['fav_by'] if g['favm'] < 0 else 0.0)] for g in gs])
coef, *_ = np.linalg.lstsq(X(train), np.array([g['h2'] for g in train], float), rcond=None)
for g in train:
    g['res'] = g['h2'] - max(8.0, float(X([g])[0] @ coef))
    g['miss'] = None if g['L'] is None else g['h2'] - g['L']
GL = [g for g in train if g['L'] is not None]
print(f"regular-season games 2012-13 on: {len(train)}, with a 2H line: {len(GL)}")
print(f"base: 2H residual sd {np.std([g['res'] for g in train]):.2f}")

def row(name, pred, team=None):
    gs = [g for g in train if pred(g)]
    if len(gs) < 200:
        return
    res = np.array([g['res'] for g in gs]); gl = [g for g in gs if g['miss'] is not None]
    miss = np.array([g['miss'] for g in gl]) if gl else np.array([0.0])
    over = np.mean(miss > 0) / max(1e-9, np.mean(miss != 0)) if gl else float('nan')
    tot = np.mean([g['total'] for g in gs])
    extra = ''
    if team:   # the team's own 2H points vs the opponent's, as a share of the 2H
        own = np.mean([g['h2' + team] for g in gs]); opp = np.mean([g['h2' + ('h' if team == 'a' else 'a')] for g in gs])
        extra = f"  own 2H {own:5.1f} vs opp {opp:5.1f}"
    se = np.std(res) / math.sqrt(len(res))
    print(f"  {name:44s} n {len(gs):5d}  pregame total {tot:6.1f}  2H resid {np.mean(res):+5.2f} (se {se:.2f})  vs 2H line: n {len(gl):5d} miss {np.mean(miss):+5.2f} over {100*over:4.1f}%{extra}")

print('\n1. REST (days since the previous game, 7 = a week or more / first game)')
for d in (1, 2, 3, 4, 7):
    row(f"away on {d} day(s) rest", lambda g, d=d: g['a_rest'] == d, 'a')
for d in (1, 2, 3, 4, 7):
    row(f"home on {d} day(s) rest", lambda g, d=d: g['h_rest'] == d, 'h')
row('both on a back-to-back', lambda g: g['a_rest'] == 1 and g['h_rest'] == 1)
row('away b2b, home 2+ days', lambda g: g['a_rest'] == 1 and g['h_rest'] >= 2, 'a')
row('home b2b, away 2+ days', lambda g: g['h_rest'] == 1 and g['a_rest'] >= 2, 'h')
row('away b2b, home 3+ days (big rest edge)', lambda g: g['a_rest'] == 1 and g['h_rest'] >= 3, 'a')
print('\n2. TIGHT WINDOWS (games in the previous 7 days)')
for n in (1, 2, 3, 4):
    row(f"away played {n} in the last 7 days", lambda g, n=n: g['a_g7'] == n, 'a')
for n in (1, 2, 3, 4):
    row(f"home played {n} in the last 7 days", lambda g, n=n: g['h_g7'] == n, 'h')
row('away 4 in 7 AND on a b2b', lambda g: g['a_g7'] >= 4 and g['a_rest'] == 1, 'a')
print('\n3. ROAD TRIPS (consecutive away games, this one included) AND MILES')
for k in (1, 2, 3, 4, 5):
    row(f"away team's {k}{'th' if k > 3 else ['st','nd','rd'][k-1]} straight road game" + (' or later' if k == 5 else ''), lambda g, k=k: (g['a_streak'] == k) if k < 5 else (g['a_streak'] >= 5), 'a')
for lo, hi in [(0, 1), (1, 500), (500, 1000), (1000, 1500), (1500, 9999)]:
    row(f"away team traveled {lo}-{hi} miles since last game", lambda g, lo=lo, hi=hi: lo <= g['a_travel'] < hi, 'a')
for lo, hi in [(0, 1), (1, 1000), (1000, 2500), (2500, 5000), (5000, 99999)]:
    row(f"away team trip miles so far {lo}-{hi}", lambda g, lo=lo, hi=hi: lo <= g['a_trip'] < hi, 'a')
row('home team first game back from a 3+ game trip', lambda g: g['h_prev_streak'] >= 3, 'h')
row('home team first game back from a 5+ game trip', lambda g: g['h_prev_streak'] >= 5, 'h')
row('away b2b after 1,000+ miles', lambda g: g['a_rest'] == 1 and g['a_travel'] >= 1000, 'a')
print('\n4. TIRED TEAM AT THE HALF (away on a b2b against a home team with 2+ days): does the second half fade?')
row('   ... tired away team leading at the half', lambda g: g['a_rest'] == 1 and g['h_rest'] >= 2 and g['h1a'] > g['h1h'], 'a')
row('   ... tired away team trailing at the half', lambda g: g['a_rest'] == 1 and g['h_rest'] >= 2 and g['h1a'] < g['h1h'], 'a')
row('   ... tired away team trailing by 10+ at the half', lambda g: g['a_rest'] == 1 and g['h_rest'] >= 2 and g['h1a'] <= g['h1h'] - 10, 'a')
row('   home b2b vs rested away, home leading at half', lambda g: g['h_rest'] == 1 and g['a_rest'] >= 2 and g['h1h'] > g['h1a'], 'h')
row('   home b2b vs rested away, home trailing at half', lambda g: g['h_rest'] == 1 and g['a_rest'] >= 2 and g['h1h'] < g['h1a'], 'h')
print('\n5. DOES THE PREGAME TOTAL ALREADY PRICE REST? mean total and mean actual full-game total by away rest')
for d in (1, 2, 3, 7):
    gs = [g for g in train if g['a_rest'] == d]
    print(f"   away rest {d}: n {len(gs):5d}  total {np.mean([g['total'] for g in gs]):6.1f}  actual {np.mean([g['fa'] + g['fh'] for g in gs]):6.1f}  diff {np.mean([g['fa'] + g['fh'] - g['total'] for g in gs]):+5.2f}")
print('\n6. REGRESSION: 2H residual on the schedule features together (t-stats)')
F = np.array([[1.0, g['a_rest'] == 1, g['h_rest'] == 1, g['a_g7'] >= 4, g['h_g7'] >= 4, g['a_streak'] >= 4, g['a_travel'] / 1000, g['a_trip'] / 1000, g['h_prev_streak'] >= 4] for g in train], float)
y = np.array([g['res'] for g in train])
c, *_ = np.linalg.lstsq(F, y, rcond=None); r = y - F @ c
s2 = np.sum(r ** 2) / (len(y) - F.shape[1]); cov = s2 * np.linalg.inv(F.T @ F)
names = ['const', 'away b2b', 'home b2b', 'away 4 in 7', 'home 4 in 7', 'away 4th+ road game', 'away miles/1000', 'away trip miles/1000', 'home back from 4+ trip']
for i, n in enumerate(names):
    print(f"   {n:24s} {c[i]:+6.3f}  t {c[i] / math.sqrt(cov[i, i]):+5.2f}")
