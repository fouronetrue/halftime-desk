"""College basketball halftime spots for live betting: what the second half does, against the desk's own cbb model
and against the naive numbers a live bettor carries (half the pregame total, the pregame spread), by game state at
the half, travel, time-zone shift, rest and tip time.

  python scripts/study_cbb_spots.py data/cbb_games.csv data/cbb_travel.csv [--era 2016]

Every cell prints n, the second-half points minus the model's fair (with its standard error and z), the over
share against the model's fair line, the over share against half the closing total (the pace line), the
favorite's second-half margin minus the 2H margin model fit here (with z), the share of second halves the
favorite wins, and the favorite's full-game cover rate against the closing spread. A lean is real at |z| 3 or
more on a cell with a few hundred games; 2 to 3 is a watch item; under 2 is noise however it reads. The
write-up is claude/cbb-live-angles.md.
"""
import csv, math, sys, collections, os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine

GAMES, TRAVEL = sys.argv[1], sys.argv[2]
ERA = int(sys.argv[sys.argv.index('--era') + 1]) if '--era' in sys.argv else 2016


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


travel = {r['game_id']: r for r in csv.DictReader(open(TRAVEL))}
G = []
for r in csv.DictReader(open(GAMES)):
    if not r.get('game_id') or r['home_spread'] in ('', None):
        continue
    g = dict(game_id=r['game_id'], date=r['date'], season=int(r['season']), post=r.get('season_type') == '3', neutral=int(r['neutral'] or 0),
             away=r['away'], home=r['home'], h1a=int(r['h1a']), h1h=int(r['h1h']), fa=int(r['fa']), fh=int(r['fh']),
             total=float(r['total']), home_spread=float(r['home_spread']), h2_total=num(r['h2_total']), h2_spread_fav=num(r['h2_spread_fav']))
    g['h1'] = g['h1a'] + g['h1h']; g['ft'] = g['fa'] + g['fh']; g['h2'] = g['ft'] - g['h1']
    if g['h2'] < 20 or g['h1'] < 20 or g['total'] < 100 or g['total'] > 200 or g['season'] < ERA:
        continue
    home_fav_by = -g['home_spread']
    g['home_fav'] = home_fav_by > 0
    g['pick'] = home_fav_by == 0
    g['fav_by'] = abs(home_fav_by)
    g['hm'] = g['h1h'] - g['h1a']                       # home halftime margin
    g['favm'] = g['hm'] if home_fav_by >= 0 else -g['hm']   # the favorite's halftime margin
    g['fm2'] = (g['fh'] - g['h1h']) - (g['fa'] - g['h1a'])   # home second-half margin
    g['fav_m2'] = g['fm2'] if home_fav_by >= 0 else -g['fm2']
    g['fav_final_m'] = (g['fh'] - g['fa']) if home_fav_by >= 0 else (g['fa'] - g['fh'])
    g['fav_cover'] = g['fav_final_m'] > g['fav_by']
    g['fav_wins'] = g['fav_final_m'] > 0
    g['pace'] = g['h1'] - g['total'] / 2
    m = engine.HalfModel('cbb', g['total'], g['home_spread'], g['h1h'], g['h1a'])
    g['mu'] = m.mu
    g['resid'] = g['h2'] - m.mu
    g['over_model'] = g['h2'] > m.mu
    g['over_pace'] = g['h2'] > g['total'] / 2
    t = travel.get(g['game_id']) or {}
    g['away_miles'] = num(t.get('away_miles')); g['home_miles'] = num(t.get('home_miles'))
    g['away_shift'] = num(t.get('away_tz_shift')); g['home_shift'] = num(t.get('home_tz_shift'))
    g['away_rest'] = num(t.get('away_rest_days')); g['home_rest'] = num(t.get('home_rest_days'))
    g['tip'] = num(t.get('tip_local_hour')); g['conf'] = t.get('conf') == '1'
    g['month'] = int(g['date'][5:7])
    G.append(g)
print(f'{len(G)} games from {ERA} on')

# the 2H margin model the sides cells are judged against: favorite's second-half margin on the spread and the
# favorite's halftime margin (the NBA's shrink is -0.52 + 0.614 x spread - 0.268 x halftime margin)
X = np.array([[1.0, g['fav_by'], g['favm'], 1.0 if g['home_fav'] else -1.0 if not g['pick'] else 0.0] for g in G]); y = np.array([g['fav_m2'] for g in G], float)
mcoef, *_ = np.linalg.lstsq(X, y, rcond=None)
for g, pred in zip(G, X @ mcoef):
    g['m2_pred'] = pred
    g['m2_resid'] = g['fav_m2'] - pred
print(f"2H margin model: favorite's second-half margin = {mcoef[0]:+.2f} {mcoef[1]:+.3f} x spread {mcoef[2]:+.3f} x halftime margin "
      f"{mcoef[3]:+.3f} x (home favorite +1, away favorite -1) (resid sd {np.std(y - X @ mcoef):.1f}); a home favorite down 10 at the half with a "
      f"5-point spread is expected to win the second half by {mcoef[0] + mcoef[1] * 5 - mcoef[2] * 10 + mcoef[3]:+.1f}")
print("   (the home term says the home team's edge is spread over the game unevenly: the first half carries more of it than half the spread, the second half less)")
print(f"favorite's halftime margin on average: {np.mean([g['favm'] for g in G]):+.2f} (half the spread would be {np.mean([g['fav_by'] for g in G]) / 2:+.2f})")


def z_of(vals):
    v = np.array(vals, float)
    n = len(v)
    if n < 2:
        return 0.0, 0.0, n
    mean = v.mean(); se = v.std(ddof=1) / math.sqrt(n)
    return mean, se, (mean / se if se else 0.0)


def cell(name, pred, gs=None, sides=True):
    gs = [g for g in (gs if gs is not None else G) if pred(g)]
    n = len(gs)
    if n == 0:
        print(f"{name:58s} n     0")
        return
    mean, se, z = z_of([g['resid'] for g in gs])
    om = np.mean([g['over_model'] for g in gs]); op = np.mean([g['over_pace'] for g in gs])
    flag = ' <<<' if abs(z) >= 3 and n >= 200 else ' <' if abs(z) >= 2 and n >= 200 else ''
    line = f"{name:58s} n {n:6d}  2H vs model {mean:+5.2f} ({se:.2f}, z {z:+4.1f}){flag:4s} over: model {100*om:4.1f}% pace {100*op:4.1f}%"
    if sides:
        mm, mse, mz = z_of([g['m2_resid'] for g in gs])
        fw = np.mean([g['fav_m2'] > 0 for g in gs]) / max(1e-9, np.mean([g['fav_m2'] != 0 for g in gs]))
        fc = np.mean([g['fav_cover'] for g in gs]) / max(1e-9, np.mean([g['fav_final_m'] != g['fav_by'] for g in gs]))
        flag2 = ' <<<' if abs(mz) >= 3 and n >= 200 else ' <' if abs(mz) >= 2 and n >= 200 else ''
        line += f" | fav 2H margin vs model {mm:+5.2f} (z {mz:+4.1f}){flag2:4s} fav wins 2H {100*fw:4.1f}% covers game {100*fc:4.1f}%"
    print(line)


def H(title):
    print(); print('=' * 110); print(title); print('=' * 110)


H('A. HOME FAVORITES TRAILING AT THE HALF (the deficit is the home team\'s)')
for lo, hi in [(0.5, 3), (3.5, 7), (7.5, 10.5), (11, 14.5), (15, 99)]:
    cell(f"home fav {lo}-{hi}, trailing", lambda g, lo=lo, hi=hi: g['home_fav'] and lo <= g['fav_by'] <= hi and g['hm'] < 0)
    for dlo, dhi in [(1, 5), (6, 10), (11, 99)]:
        cell(f"   ... down {dlo}-{dhi}", lambda g, lo=lo, hi=hi, dlo=dlo, dhi=dhi: g['home_fav'] and lo <= g['fav_by'] <= hi and -dhi <= g['hm'] <= -dlo)

H('B. HOME FAVORITES LEADING AT THE HALF, BY SPREAD AND LEAD')
for lo, hi in [(0.5, 3), (3.5, 6), (6.5, 10.5), (11, 14.5), (15, 99)]:
    for llo, lhi in [(1, 5), (6, 9), (10, 14), (15, 19), (20, 99)]:
        cell(f"home fav {lo}-{hi}, up {llo}-{lhi}", lambda g, lo=lo, hi=hi, llo=llo, lhi=lhi: g['home_fav'] and lo <= g['fav_by'] <= hi and llo <= g['hm'] <= lhi)

H('C. AWAY FAVORITES (the margin is the favorite\'s)')
for lo, hi in [(0.5, 3), (3.5, 7), (7.5, 10.5), (11, 99)]:
    cell(f"away fav {lo}-{hi}, trailing", lambda g, lo=lo, hi=hi: not g['home_fav'] and not g['pick'] and lo <= g['fav_by'] <= hi and g['favm'] < 0)
    cell(f"   ... down 6+", lambda g, lo=lo, hi=hi: not g['home_fav'] and not g['pick'] and lo <= g['fav_by'] <= hi and g['favm'] <= -6)
    cell(f"away fav {lo}-{hi}, up 1-9", lambda g, lo=lo, hi=hi: not g['home_fav'] and not g['pick'] and lo <= g['fav_by'] <= hi and 1 <= g['favm'] <= 9)
    cell(f"away fav {lo}-{hi}, up 10-14", lambda g, lo=lo, hi=hi: not g['home_fav'] and not g['pick'] and lo <= g['fav_by'] <= hi and 10 <= g['favm'] <= 14)
    cell(f"away fav {lo}-{hi}, up 15+", lambda g, lo=lo, hi=hi: not g['home_fav'] and not g['pick'] and lo <= g['fav_by'] <= hi and g['favm'] >= 15)

H('D. DOGS BY THE SIZE OF THE HALFTIME NUMBER (dog = the side getting points; its margin is -favm)')
for who, pred0 in [('home dog', lambda g: not g['home_fav'] and not g['pick']), ('away dog', lambda g: g['home_fav'])]:
    for lo, hi in [(0.5, 7), (7.5, 14.5), (15, 99)]:
        for name, p in [('leading 1-5', lambda g: -5 <= g['favm'] <= -1), ('leading 6-10', lambda g: -10 <= g['favm'] <= -6), ('leading 11+', lambda g: g['favm'] <= -11),
                        ('trailing 1-9', lambda g: 1 <= g['favm'] <= 9), ('trailing 10-14', lambda g: 10 <= g['favm'] <= 14), ('trailing 15-19', lambda g: 15 <= g['favm'] <= 19),
                        ('trailing 20-24', lambda g: 20 <= g['favm'] <= 24), ('trailing 25+', lambda g: g['favm'] >= 25)]:
            cell(f"{who} +{lo}-{hi}, {name}", lambda g, pred0=pred0, lo=lo, hi=hi, p=p: pred0(g) and lo <= g['fav_by'] <= hi and p(g))

H('E. PACE: FIRST-HALF POINTS MINUS HALF THE CLOSING TOTAL')
for lo, hi in [(-99, -15), (-15, -10), (-10, -6), (-6, -3), (-3, 0), (0, 3), (3, 6), (6, 10), (10, 15), (15, 99)]:
    cell(f"pace [{lo},{hi})", lambda g, lo=lo, hi=hi: lo <= g['pace'] < hi, sides=False)
print('   the same, by the closing total')
for tlo, thi in [(100, 130), (130, 140), (140, 150), (150, 160), (160, 200)]:
    for lo, hi in [(-99, -10), (-10, -3), (-3, 3), (3, 10), (10, 99)]:
        cell(f"total {tlo}-{thi}, pace [{lo},{hi})", lambda g, lo=lo, hi=hi, tlo=tlo, thi=thi: tlo <= g['total'] < thi and lo <= g['pace'] < hi, sides=False)
print('   pace and the margin together')
for name, p in [('slow (pace -8 or less), close (within 5)', lambda g: g['pace'] <= -8 and abs(g['hm']) <= 5),
                ('slow, blowout 15+', lambda g: g['pace'] <= -8 and abs(g['hm']) >= 15),
                ('fast (pace +8 or more), close', lambda g: g['pace'] >= 8 and abs(g['hm']) <= 5),
                ('fast, blowout 15+', lambda g: g['pace'] >= 8 and abs(g['hm']) >= 15)]:
    cell(name, p, sides=False)

H('F. CLOSE GAMES, BLOWOUTS, SITE, MONTH, CONFERENCE')
cell('tied at the half', lambda g: g['hm'] == 0)
cell('within 2 at the half', lambda g: abs(g['hm']) <= 2)
for lo, hi in [(15, 19), (20, 24), (25, 29), (30, 99)]:
    cell(f"blowout {lo}-{hi}, favorite leading", lambda g, lo=lo, hi=hi: lo <= g['favm'] <= hi)
    cell(f"blowout {lo}-{hi}, dog leading", lambda g, lo=lo, hi=hi: -hi <= g['favm'] <= -lo)
cell('neutral site', lambda g: g['neutral'] == 1)
cell('conference game', lambda g: g['conf'])
cell('non-conference', lambda g: not g['conf'])
for mo in (11, 12, 1, 2, 3):
    cell(f"month {mo}", lambda g, mo=mo: g['month'] == mo)
cell('postseason', lambda g: g['post'])
print('   the combined cells the write-up leans on')
cell('small home fav (0.5-6) leading at the half', lambda g: g['home_fav'] and g['fav_by'] <= 6 and g['hm'] > 0)
cell('small home fav (0.5-6) leading 1-14', lambda g: g['home_fav'] and g['fav_by'] <= 6 and 1 <= g['hm'] <= 14)
cell('15+ point favorite, dog within 14 at the half (mismatch)', lambda g: g['fav_by'] >= 15 and g['favm'] <= 14)
cell('15+ point favorite, dog within 14, home favorite', lambda g: g['fav_by'] >= 15 and g['favm'] <= 14 and g['home_fav'])
cell('15+ point favorite, dog within 14, away favorite', lambda g: g['fav_by'] >= 15 and g['favm'] <= 14 and not g['home_fav'] and not g['pick'])
cell('15+ point favorite, up 20+ (the rout)', lambda g: g['fav_by'] >= 15 and g['favm'] >= 20)
cell('any favorite up 25+ at the half', lambda g: g['favm'] >= 25)
cell('any favorite up 20-24', lambda g: 20 <= g['favm'] <= 24)
cell('fast first half (pace +6 or more) and a 15+ margin', lambda g: g['pace'] >= 6 and abs(g['hm']) >= 15)
cell('slow first half (pace -6 or less) and a 15+ margin', lambda g: g['pace'] <= -6 and abs(g['hm']) >= 15)
cell('either team on 1 day rest', lambda g: (g['away_rest'] is not None and g['away_rest'] <= 1.5) or (g['home_rest'] is not None and g['home_rest'] <= 1.5))
cell('neither team on 1 day rest', lambda g: g['away_rest'] is not None and g['home_rest'] is not None and g['away_rest'] > 1.5 and g['home_rest'] > 1.5)
cell('November', lambda g: g['month'] == 11)
cell('March and the postseason', lambda g: g['month'] == 3 or g['post'])

H('G. TRAVEL: THE AWAY TEAM\'S MILES AND TIME-ZONE SHIFT (non-neutral games; margin cells are the favorite\'s)')
print('   first, does the market already price travel: the away team\'s halftime margin and full-game result vs the spread')
for name, p in [('away miles 0-100', lambda g: g['away_miles'] is not None and g['away_miles'] <= 100),
                ('away miles 100-300', lambda g: g['away_miles'] is not None and 100 < g['away_miles'] <= 300),
                ('away miles 300-600', lambda g: g['away_miles'] is not None and 300 < g['away_miles'] <= 600),
                ('away miles 600-1000', lambda g: g['away_miles'] is not None and 600 < g['away_miles'] <= 1000),
                ('away miles 1000-2000', lambda g: g['away_miles'] is not None and 1000 < g['away_miles'] <= 2000),
                ('away miles 2000+', lambda g: g['away_miles'] is not None and g['away_miles'] > 2000),
                ('away shift 0 (same zone)', lambda g: g['away_shift'] == 0),
                ('away shift -1 (one zone west)', lambda g: g['away_shift'] == -1),
                ('away shift -2 (two zones west)', lambda g: g['away_shift'] == -2),
                ('away shift -3 or more west', lambda g: g['away_shift'] is not None and g['away_shift'] <= -3),
                ('away shift +1 (one zone east)', lambda g: g['away_shift'] == 1),
                ('away shift +2 (two zones east)', lambda g: g['away_shift'] == 2),
                ('away shift +3 or more east', lambda g: g['away_shift'] is not None and g['away_shift'] >= 3)]:
    gs = [g for g in G if g['neutral'] == 0 and p(g)]
    if not gs:
        continue
    am = [-(g['hm']) for g in gs]                                   # the away team's halftime margin
    af = [-(g['fh'] - g['fa']) for g in gs]                         # the away team's final margin
    asp = [g['home_spread'] for g in gs]                            # the away team's spread (minus = away favored... home_spread minus = home favored, so the away line is -home_spread)
    away_line = [-s for s in asp]                                   # the away team's closing line (minus = away favored)
    cover = np.mean([(f + l) > 0 for f, l in zip(af, away_line)]) / max(1e-9, np.mean([(f + l) != 0 for f, l in zip(af, away_line)]))
    m2 = [-(g['fm2']) for g in gs]                                  # the away team's second-half margin
    exp_half = [l / 2 for l in [-x for x in away_line]]             # half of what the market expects the away team to win by (minus the line)
    d1 = np.array(am) - np.array([-l / 2 for l in away_line])       # halftime margin vs half the line
    d2 = np.array(m2) - np.array([-l / 2 for l in away_line])       # second-half margin vs half the line
    print(f"{name:34s} n {len(gs):6d}  away 1H margin vs half the line {d1.mean():+5.2f} (z {d1.mean()/(d1.std(ddof=1)/math.sqrt(len(gs))):+4.1f})  "
          f"2H margin vs half the line {d2.mean():+5.2f} (z {d2.mean()/(d2.std(ddof=1)/math.sqrt(len(gs))):+4.1f})  away covers {100*cover:4.1f}%  "
          f"2H pts vs model {np.mean([g['resid'] for g in gs]):+5.2f}")
print('   rest, from the away team\'s side')
for name, p in [('away on 1 day rest', lambda g: g['away_rest'] is not None and g['away_rest'] <= 1.5),
                ('home on 1 day rest', lambda g: g['home_rest'] is not None and g['home_rest'] <= 1.5),
                ('away rested 3+ days more than home', lambda g: g['away_rest'] is not None and g['home_rest'] is not None and g['away_rest'] - g['home_rest'] >= 3),
                ('home rested 3+ days more than away', lambda g: g['away_rest'] is not None and g['home_rest'] is not None and g['home_rest'] - g['away_rest'] >= 3),
                ('away 1000+ miles on 1-2 days rest', lambda g: g['away_miles'] is not None and g['away_miles'] >= 1000 and g['away_rest'] is not None and g['away_rest'] <= 2.5)]:
    gs = [g for g in G if g['neutral'] == 0 and p(g)]
    if not gs:
        continue
    am = np.array([-(g['hm']) for g in gs], float); af = np.array([-(g['fh'] - g['fa']) for g in gs], float); m2 = np.array([-(g['fm2']) for g in gs], float)
    line = np.array([-g['home_spread'] for g in gs], float)
    cover = np.mean((af + line) > 0) / max(1e-9, np.mean((af + line) != 0))
    d1 = am - (-line / 2); d2 = m2 - (-line / 2)
    print(f"{name:34s} n {len(gs):6d}  away 1H margin vs half the line {d1.mean():+5.2f} (z {d1.mean()/(d1.std(ddof=1)/math.sqrt(len(gs))):+4.1f})  "
          f"2H margin vs half the line {d2.mean():+5.2f} (z {d2.mean()/(d2.std(ddof=1)/math.sqrt(len(gs))):+4.1f})  away covers {100*cover:4.1f}%  "
          f"2H pts vs model {np.mean([g['resid'] for g in gs]):+5.2f}")
print('   the second half for the traveling team, by what the half looked like (favorite cells)')
for name, p in [('away team 2+ zones west, trailing at half', lambda g: g['away_shift'] is not None and g['away_shift'] <= -2 and g['hm'] > 0),
                ('away team 2+ zones west, leading at half', lambda g: g['away_shift'] is not None and g['away_shift'] <= -2 and g['hm'] < 0),
                ('away team 2+ zones east, trailing at half', lambda g: g['away_shift'] is not None and g['away_shift'] >= 2 and g['hm'] > 0),
                ('away team 2+ zones east, leading at half', lambda g: g['away_shift'] is not None and g['away_shift'] >= 2 and g['hm'] < 0),
                ('away team 1000+ miles, trailing at half', lambda g: g['away_miles'] is not None and g['away_miles'] >= 1000 and g['hm'] > 0),
                ('away team 1000+ miles, leading at half', lambda g: g['away_miles'] is not None and g['away_miles'] >= 1000 and g['hm'] < 0),
                ('away team 1000+ miles and an away favorite', lambda g: g['away_miles'] is not None and g['away_miles'] >= 1000 and not g['home_fav'] and not g['pick']),
                ('away team 1000+ miles and an away dog of 10+', lambda g: g['away_miles'] is not None and g['away_miles'] >= 1000 and g['home_fav'] and g['fav_by'] >= 10)]:
    cell(name, lambda g, p=p: g['neutral'] == 0 and p(g))

H('H. REST AND TIP TIME')
for name, p in [('away on 1 day rest', lambda g: g['away_rest'] is not None and g['away_rest'] <= 1.5),
                ('away on 2 days rest', lambda g: g['away_rest'] is not None and 1.5 < g['away_rest'] <= 2.5),
                ('away on 3-4 days rest', lambda g: g['away_rest'] is not None and 2.5 < g['away_rest'] <= 4.5),
                ('away on 5+ days rest', lambda g: g['away_rest'] is not None and g['away_rest'] > 4.5),
                ('home on 1 day rest', lambda g: g['home_rest'] is not None and g['home_rest'] <= 1.5),
                ('home on 5+ days rest', lambda g: g['home_rest'] is not None and g['home_rest'] > 4.5),
                ('away rested 3+ days more than home', lambda g: g['away_rest'] is not None and g['home_rest'] is not None and g['away_rest'] - g['home_rest'] >= 3),
                ('home rested 3+ days more than away', lambda g: g['away_rest'] is not None and g['home_rest'] is not None and g['home_rest'] - g['away_rest'] >= 3),
                ('both on 1 day rest (tournament)', lambda g: g['away_rest'] is not None and g['home_rest'] is not None and g['away_rest'] <= 1.5 and g['home_rest'] <= 1.5)]:
    cell(name, p)
for name, p in [('tip before noon local', lambda g: g['tip'] is not None and g['tip'] < 12), ('tip noon to 3 pm', lambda g: g['tip'] is not None and 12 <= g['tip'] < 15),
                ('tip 3 to 6 pm', lambda g: g['tip'] is not None and 15 <= g['tip'] < 18), ('tip 6 to 8 pm', lambda g: g['tip'] is not None and 18 <= g['tip'] < 20),
                ('tip 8 pm or later', lambda g: g['tip'] is not None and g['tip'] >= 20),
                ('away body clock before noon (local tip plus the shift)', lambda g: g['tip'] is not None and g['away_shift'] is not None and g['tip'] - g['away_shift'] < 12),
                ('away body clock 10 pm or later', lambda g: g['tip'] is not None and g['away_shift'] is not None and g['tip'] - g['away_shift'] >= 22)]:
    cell(name, lambda g, p=p: g['neutral'] == 0 and p(g))

H('I. THE 2H LINE SEASONS ONLY (2007-11, the market\'s own second-half total): over share vs the 2H line by spot')
L = [g for g in [dict(x) for x in []]]   # placeholder so the block reads the same with --era 2008


def line_cell(name, pred):
    gs = [g for g in G if g['h2_total'] is not None and abs(g['h2_total'] - g['total'] / 2) < 20 and pred(g)]
    if len(gs) < 100:
        return
    d = np.array([g['h2'] - g['h2_total'] for g in gs])
    over = np.mean(d > 0) / max(1e-9, np.mean(d != 0))
    print(f"{name:58s} n {len(gs):6d}  2H minus the 2H line {d.mean():+5.2f} (z {d.mean()/(d.std(ddof=1)/math.sqrt(len(gs))):+4.1f})  over {100*over:4.1f}%")


if ERA <= 2011:
    for name, p in [('home fav trailing', lambda g: g['home_fav'] and g['hm'] < 0), ('home fav 0.5-6 up 10+', lambda g: g['home_fav'] and g['fav_by'] <= 6 and g['hm'] >= 10),
                    ('dog up 10+', lambda g: g['favm'] <= -10), ('fav up 20+', lambda g: g['favm'] >= 20), ('pace -10 or less', lambda g: g['pace'] <= -10),
                    ('pace +10 or more', lambda g: g['pace'] >= 10), ('within 2', lambda g: abs(g['hm']) <= 2), ('spread 20+, fav up under 10', lambda g: g['fav_by'] >= 20 and g['favm'] < 10),
                    ('away 2+ zones west', lambda g: g['away_shift'] is not None and g['away_shift'] <= -2), ('away 2+ zones east', lambda g: g['away_shift'] is not None and g['away_shift'] >= 2)]:
        line_cell(name, p)
else:
    print('   (run with --era 2008 to see these; the 2H lines are 2007-11 only)')
