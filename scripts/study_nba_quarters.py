"""python scripts/study_nba_quarters.py (needs numpy). Quarter by quarter: where the points come from, what the third and fourth quarters do by game state, whether a
road team on a long trip fades in the fourth or a home team on a home stand finishes stronger, and what an
end-of-third-quarter pricing window would have to know. Regular season and playoffs, 2007-08 through 2025-26."""
import csv, math, os, datetime as dt
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
raw = list(csv.DictReader(open(os.path.join(ROOT, 'data', 'nba_games.csv'))))
LOC = dict(atl=(33.757, -84.396), bkn=(40.683, -73.975), bos=(42.366, -71.062), cha=(35.225, -80.839), chi=(41.881, -87.674), cle=(41.496, -81.688),
           dal=(32.790, -96.810), den=(39.749, -105.008), det=(42.341, -83.055), gs=(37.768, -122.388), hou=(29.751, -95.362), ind=(39.764, -86.156),
           lac=(34.043, -118.267), lal=(34.043, -118.267), mem=(35.138, -90.051), mia=(25.781, -80.187), mil=(43.045, -87.917), min=(44.979, -93.276),
           no=(29.949, -90.082), ny=(40.751, -73.994), okc=(35.463, -97.515), orl=(28.539, -81.384), phi=(39.901, -75.172), phx=(33.446, -112.071),
           por=(45.532, -122.667), sa=(29.427, -98.438), sac=(38.580, -121.500), tor=(43.643, -79.379), utah=(40.768, -111.901), wsh=(38.898, -77.021))
def miles(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))
G = []
for r in raw:
    try:
        q = {k: int(r[k]) for k in ('h1a', 'h1h', 'q3a', 'q3h', 'q4a', 'q4h', 'ota', 'oth')}
        total = float(r['total']); hs = float(r['home_spread'])
    except Exception:
        continue
    g = dict(date=dt.date.fromisoformat(r['date']), season=int(r['season']), playoffs=r['playoffs'] == '1', away=r['away'], home=r['home'],
             q3=q['q3a'] + q['q3h'], q4=q['q4a'] + q['q4h'], ot=q['ota'] + q['oth'],
             q3a=q['q3a'], q3h=q['q3h'], q4a=q['q4a'], q4h=q['q4h'], total=total)
    g['h1'] = q['h1a'] + q['h1h']; g['h2'] = g['q3'] + g['q4'] + g['ot']; g['thru3'] = g['h1'] + g['q3']
    g['hm1'] = q['h1h'] - q['h1a']; g['hm3'] = g['hm1'] + q['q3h'] - q['q3a']
    g['m3'] = q['q3h'] - q['q3a']; g['m4'] = q['q4h'] - q['q4a']
    g['hs'] = hs   # home spread, minus = home favored
    g['home_fav'] = g['hs'] < 0; g['fav_by'] = abs(g['hs'])
    G.append(g)
G.sort(key=lambda g: g['date'])
# schedule state per team: rest, consecutive road games and trip miles for the away side, consecutive home games for the home side
last = {}
for g in G:
    for side, team in (('a', g['away']), ('h', g['home'])):
        key = (g['season'], team); st = last.get(key); here = LOC[g['home']]
        if st is None or g['playoffs']:
            rest, streak, trip, stand = 7, 0, 0.0, 0
        else:
            rest = min(7, (g['date'] - st['date']).days)
            streak = st['streak'] + 1 if side == 'a' else 0
            trip = st['trip'] + miles(st['loc'], here) if side == 'a' else 0.0
            stand = st['stand'] + 1 if side == 'h' else 0
        g[side + '_rest'] = rest; g[side + '_streak'] = streak; g[side + '_trip'] = trip; g[side + '_stand'] = stand
        last[key] = dict(date=g['date'], loc=here, streak=streak, trip=trip, stand=stand)
R = [g for g in G if not g['playoffs'] and g['season'] >= 2013]
P = print
def pct(x): return f"{100*x:5.1f}%"

P('=' * 96)
P('A. THE FOUR QUARTERS (regular season 2012-13 on, n', len(R), ')')
for k, label in (('h1', 'first-half quarter (average of Q1 and Q2)'), ('q3', 'Q3'), ('q4', 'Q4')):
    v = np.array([g[k] / (2 if k == 'h1' else 1) for g in R], float)
    P(f"   {label}: mean {v.mean():5.1f}  sd {v.std():4.1f}  share of regulation {100*v.mean()/np.mean([g['h1']+g['q3']+g['q4'] for g in R]):4.1f}%")
P(f"   OT: {100*np.mean([g['ot'] > 0 for g in R]):.1f}% of games, {np.mean([g['ot'] for g in R if g['ot'] > 0]):.1f} points when it happens")
P('   by season (Q3 and Q4 means):')
P('   ' + '  '.join(f"{s-1}-{str(s)[2:]} {np.mean([g['q3'] for g in R if g['season']==s]):.1f}/{np.mean([g['q4'] for g in R if g['season']==s]):.1f}" for s in sorted({g['season'] for g in R})))
P('   Q4 scores 1.5 to 2 points less than Q3 every season: the bench in blowouts and the clock-killing in close games both cut it, and the foul game does not make it back.')

P()
P('B. THIRD AND FOURTH QUARTER BY HALFTIME MARGIN, AND THE FAVORITE\'S Q3 AND Q4 MARGINS')
P('   fav half margin    n     Q3 pts  Q4 pts   fav Q3 margin  fav Q4 margin   (the shrink, split by quarter)')
for lo, hi in [(-99, -15), (-15, -8), (-8, -3), (-3, 3), (3, 8), (8, 15), (15, 20), (20, 99)]:
    gs = [g for g in R if lo <= (g['hm1'] if g['home_fav'] else -g['hm1']) < hi]
    f3 = np.mean([(g['m3'] if g['home_fav'] else -g['m3']) for g in gs]); f4 = np.mean([(g['m4'] if g['home_fav'] else -g['m4']) for g in gs])
    P(f"   {lo:>4} to {hi:<4}    {len(gs):5d}   {np.mean([g['q3'] for g in gs]):5.1f}   {np.mean([g['q4'] for g in gs]):5.1f}    {f3:+6.2f}        {f4:+6.2f}")
P('   Read: the shrink is a fourth-quarter thing. A favorite up 20 at the half plays Q3 about even and loses Q4 by 2; a favorite down')
P('   15 wins Q3 by 3 and Q4 by 4. Q3 is the starters; Q4 is whoever the score says.')

P()
P('C. FOURTH QUARTER POINTS BY THE MARGIN AFTER THREE (what an end-of-Q3 window would price)')
P('   margin after 3    n     Q4 pts  sd    OT%    Q4 + OT pts')
for lo, hi in [(0, 2), (3, 5), (6, 9), (10, 14), (15, 19), (20, 24), (25, 99)]:
    gs = [g for g in R if lo <= abs(g['hm3']) <= hi]
    P(f"   {lo:>2}-{hi:<3}         {len(gs):5d}   {np.mean([g['q4'] for g in gs]):5.1f}  {np.std([g['q4'] for g in gs]):4.1f}  {100*np.mean([g['ot']>0 for g in gs]):4.1f}   {np.mean([g['q4']+g['ot'] for g in gs]):5.1f}")
X = np.array([[1.0, g['total'], g['thru3'], abs(g['hm3']), min(abs(g['hm3']), 5)] for g in R]); y = np.array([g['q4'] + g['ot'] for g in R], float)
c, *_ = np.linalg.lstsq(X, y, rcond=None); res = y - X @ c
P(f"   Q4+OT points ~ {c[0]:+.2f} + {c[1]:.3f} x total + {c[2]:.3f} x points through three + {c[3]:+.3f} x |margin after 3| + {c[4]:+.3f} x min(|margin|, 5); resid sd {res.std():.2f}")
P('   Read: a close game after three scores about a point less in regulation Q4 than a blowout (the clock-killing beats the foul game) and')
P('   goes to overtime one time in ten, which adds 2.3 expected points. Net, the remaining points are about one point higher in a close game')
P('   than a 20-point one, almost all of it the overtime tail. A Q3-end window needs that tail; the halftime model does not, because the')
P('   Q3 that follows the half washes it out.')

P()
P("D. NICK'S ASKS: THE ROAD TEAM LATE IN A TRIP, THE HOME TEAM ON A HOME STAND, QUARTER BY QUARTER")
P('   Own points by quarter for the team in the situation, and the quarter margin (own minus opponent). Pregame total shown because the book moves it.')
def row(name, pred, side):
    gs = [g for g in R if pred(g)]
    if len(gs) < 200: return
    o3 = np.mean([g['q3' + side] for g in gs]); o4 = np.mean([g['q4' + side] for g in gs])
    m3 = np.mean([(g['m3'] if side == 'h' else -g['m3']) for g in gs]); m4 = np.mean([(g['m4'] if side == 'h' else -g['m4']) for g in gs])
    q3 = np.mean([g['q3'] for g in gs]); q4 = np.mean([g['q4'] for g in gs])
    P(f"   {name:46s} n {len(gs):5d}  total {np.mean([g['total'] for g in gs]):6.1f}  own Q3 {o3:5.1f} Q4 {o4:5.1f}  margin Q3 {m3:+5.2f} Q4 {m4:+5.2f}  game Q3 {q3:5.1f} Q4 {q4:5.1f}")
row('away team, any', lambda g: True, 'a')
row('away team, 1st road game', lambda g: g['a_streak'] == 1, 'a')
row('away team, 3rd straight road game', lambda g: g['a_streak'] == 3, 'a')
row('away team, 4th straight road game', lambda g: g['a_streak'] == 4, 'a')
row('away team, 5th+ straight road game', lambda g: g['a_streak'] >= 5, 'a')
row('away team, trip miles 3,000+', lambda g: g['a_trip'] >= 3000, 'a')
row('away team on a back-to-back', lambda g: g['a_rest'] == 1, 'a')
row('away b2b and 3rd+ road game', lambda g: g['a_rest'] == 1 and g['a_streak'] >= 3, 'a')
row('away team with 3+ days rest', lambda g: g['a_rest'] >= 3, 'a')
row('home team, any', lambda g: True, 'h')
row('home team, 1st game of a home stand', lambda g: g['h_stand'] == 1, 'h')
row('home team, 3rd straight home game', lambda g: g['h_stand'] == 3, 'h')
row('home team, 4th+ straight home game', lambda g: g['h_stand'] >= 4, 'h')
row('home favorite, 4th+ straight home game', lambda g: g['h_stand'] >= 4 and g['home_fav'], 'h')
row('home favorite, 1st game of a home stand', lambda g: g['h_stand'] == 1 and g['home_fav'], 'h')
row('home team on a back-to-back', lambda g: g['h_rest'] == 1, 'h')
row('rested home (3+) vs away on a b2b', lambda g: g['h_rest'] >= 3 and g['a_rest'] == 1, 'h')
row('home on a b2b vs rested away (3+)', lambda g: g['h_rest'] == 1 and g['a_rest'] >= 3, 'h')
P('   Read it against the "any" rows: a road team late in a trip or on a back-to-back is a third of a point worse in Q3 and a fifth of a')
P('   point worse in Q4, not worse late than early; a home favorite deep in a home stand is a third of a point better in each quarter,')
P('   and is also a bigger favorite. The pregame total and spread already carry it. Nothing a quarter market would not have priced.')

P()
P('E. REGRESSION: THE FOURTH-QUARTER MARGIN AND TOTAL ON THE SCHEDULE, HOLDING THE SPREAD AND THE MARGIN AFTER THREE')
F = np.array([[1.0, -g['hs'], g['hm3'], g['a_rest'] == 1, g['h_rest'] == 1, g['a_streak'] >= 4, g['a_trip'] / 1000, g['h_stand'] >= 4] for g in R], float)
for name, yv in (('home Q4 margin', np.array([g['m4'] for g in R], float)), ('Q4 total', np.array([g['q4'] for g in R], float))):
    cc, *_ = np.linalg.lstsq(F, yv, rcond=None); rr = yv - F @ cc
    s2 = np.sum(rr ** 2) / (len(yv) - F.shape[1]); cov = s2 * np.linalg.inv(F.T @ F)
    P(f"   {name}:")
    for i, n in enumerate(['const', 'home pregame margin', 'home margin after 3', 'away b2b', 'home b2b', 'away 4th+ road game', 'away trip miles/1000', 'home 4th+ home game']):
        P(f"      {n:22s} {cc[i]:+6.3f}  t {cc[i]/math.sqrt(cov[i,i]):+5.2f}")

P()
P('F. QUARTER TOTALS AS A MARKET: how tight they are, and what moves them')
for k in ('q3', 'q4'):
    v = np.array([g[k] for g in R], float)
    P(f"   {k.upper()} total: sd {v.std():.1f}; within 2 of the mean {pct(np.mean(np.abs(v - v.mean()) <= 2))}, within 4 {pct(np.mean(np.abs(v - v.mean()) <= 4))}")
Xq = np.array([[1.0, g['total'], g['h1']] for g in R]); y3 = np.array([g['q3'] for g in R], float)
c3, *_ = np.linalg.lstsq(Xq, y3, rcond=None)
P(f"   Q3 points ~ {c3[0]:+.2f} + {c3[1]:.3f} x total + {c3[2]:.3f} x first-half points; resid sd {np.std(y3 - Xq @ c3):.2f}  (the first half carries almost nothing into Q3 either)")
Xq4 = np.array([[1.0, g['total'], g['thru3'], abs(g['hm3'])] for g in R]); y4 = np.array([g['q4'] for g in R], float)
c4, *_ = np.linalg.lstsq(Xq4, y4, rcond=None)
P(f"   Q4 points ~ {c4[0]:+.2f} + {c4[1]:.3f} x total + {c4[2]:.3f} x points through three + {c4[3]:+.3f} x |margin after 3|; resid sd {np.std(y4 - Xq4 @ c4):.2f}")
P('   Kalshi has no NBA quarter or half markets that this study could find (totals, spreads and win margins are full-game); sportsbooks')
P('   post quarter lines. The one structural Q4 input is the margin after three (a point of regulation scoring, the overtime tail), and')
P('   every book that posts a Q4 line knows it.')
