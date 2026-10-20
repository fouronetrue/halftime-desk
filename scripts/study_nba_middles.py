"""Middles: does anything at the half tell you how tight the second half will be, and which numbers to play?
Uses the market's own 2H line as the center where it exists (2007-2023), the model's center otherwise."""
import csv, math, os
import numpy as np
rows = list(csv.DictReader(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'nba_games.csv'))))
G = []
for r in rows:
    g = dict(season=int(r['season']), playoffs=int(r['playoffs']), h1a=int(r['h1a']), h1h=int(r['h1h']), fa=int(r['fa']), fh=int(r['fh']),
             ot=int(r['ota']) + int(r['oth']), total=float(r['total']), home_spread=float(r['home_spread']),
             L=float(r['h2_total']) if r['h2_total'] else None)
    g['h1'] = g['h1a'] + g['h1h']; g['h2'] = g['fa'] + g['fh'] - g['h1']; g['hm'] = abs(g['h1h'] - g['h1a'])
    g['fav_by'] = abs(g['home_spread']); g['pace'] = g['h1'] - g['total'] / 2
    G.append(g)
GL = [g for g in G if g['L'] is not None and g['season'] >= 2013]
print(f"games with a 2H line, 2012-13 on: {len(GL)}")
D = np.array([g['h2'] - g['L'] for g in GL])   # miss from the market's own line
print(f"all: sd of the miss {np.std(D):.2f}, mean {np.mean(D):+.2f}; within 1 (2-number window at the line) {100*np.mean(np.abs(D) <= 1):.1f}%, "
      f"within 2 (4 numbers) {100*np.mean(np.abs(D) <= 2):.1f}%, within 3 (6) {100*np.mean(np.abs(D) <= 3):.1f}%, within 5 (10) {100*np.mean(np.abs(D) <= 5):.1f}%")

def row(name, pred):
    idx = [i for i, g in enumerate(GL) if pred(g)]
    d = D[idx]
    if len(d) < 150:
        return
    ot = np.mean([GL[i]['ot'] > 0 for i in idx])
    print(f"  {name:36s} n {len(d):5d}  sd {np.std(d):5.2f}  mean {np.mean(d):+5.2f}  |miss|<=1 {100*np.mean(np.abs(d)<=1):4.1f}%  <=2 {100*np.mean(np.abs(d)<=2):4.1f}%  <=3 {100*np.mean(np.abs(d)<=3):4.1f}%  <=5 {100*np.mean(np.abs(d)<=5):4.1f}%  OT {100*ot:3.1f}%")

print('\n1. HALFTIME MARGIN (close games carry the overtime tail)')
for lo, hi in [(0, 2), (3, 5), (6, 9), (10, 14), (15, 19), (20, 24), (25, 99)]:
    row(f"margin {lo}-{hi}", lambda g, lo=lo, hi=hi: lo <= g['hm'] <= hi)
print('\n2. FIRST-HALF PACE vs the pregame total (first-half points minus total/2)')
for lo, hi in [(-99, -15), (-15, -8), (-8, -3), (-3, 3), (3, 8), (8, 15), (15, 99)]:
    row(f"pace {lo} to {hi}", lambda g, lo=lo, hi=hi: lo <= g['pace'] < hi)
print('\n3. THE 2H LINE ITSELF (level)')
for lo, hi in [(80, 95), (95, 100), (100, 105), (105, 110), (110, 115), (115, 125), (125, 150)]:
    row(f"2H line {lo}-{hi}", lambda g, lo=lo, hi=hi: lo <= g['L'] < hi)
print('\n4. PREGAME SPREAD')
for lo, hi in [(0, 3), (3.5, 7), (7.5, 10.5), (11, 99)]:
    row(f"spread {lo}-{hi}", lambda g, lo=lo, hi=hi: lo <= g['fav_by'] <= hi)
print('\n5. PLAYOFFS, SEASON')
row('regular season', lambda g: g['playoffs'] == 0)
row('playoffs', lambda g: g['playoffs'] == 1)
for s in range(2013, 2024):
    row(f"{s-1}-{str(s)[2:]}", lambda g, s=s: g['season'] == s)
print('\n6. MARGIN x PACE (the two tells together)')
for name, pm in [('close (0-5)', lambda g: g['hm'] <= 5), ('mid (6-14)', lambda g: 6 <= g['hm'] <= 14), ('blowout (15+)', lambda g: g['hm'] >= 15)]:
    for pn, pp in [('slow 1H (pace < -5)', lambda g: g['pace'] < -5), ('normal', lambda g: -5 <= g['pace'] <= 5), ('fast 1H (pace > 5)', lambda g: g['pace'] > 5)]:
        row(f"{name}, {pn}", lambda g, pm=pm, pp=pp: pm(g) and pp(g))

print('\n7. WHERE THE FINAL LANDS: miss from the line, in numbers (share of games), pooled')
for k in range(-6, 7):
    sel = np.abs(D - k) <= 0.5 if False else (np.round(D) == k)
    print(f"   line{k:+d}: {100*np.mean(sel):4.2f}%", end='')
print()
# the line is x.5 in most games; look at the final total's parity and last digit for key-number effects
ft = np.array([g['fa'] + g['fh'] for g in G])
print(f"   final total even {100*np.mean(ft % 2 == 0):.1f}%  (no key numbers if ~50)")
print('   last digit of the final total: ' + ' '.join(f"{d}:{100*np.mean(ft % 10 == d):.1f}%" for d in range(10)))

print('\n8. OVERTIME AND THE MIDDLE: a game that goes to OT misses any window near fair by 20+')
for name, pred in [('margin 0-2', lambda g: g['hm'] <= 2), ('margin 3-5', lambda g: 3 <= g['hm'] <= 5), ('margin 6-9', lambda g: 6 <= g['hm'] <= 9), ('margin 10-14', lambda g: 10 <= g['hm'] <= 14), ('margin 15+', lambda g: g['hm'] >= 15)]:
    idx = [i for i, g in enumerate(GL) if pred(g)]
    d = D[idx]; reg = np.array([GL[i]['ot'] == 0 for i in idx])
    print(f"   {name:12s} n {len(d):5d}  P(OT) {100*np.mean(~reg):4.1f}%  |miss|<=2 all {100*np.mean(np.abs(d)<=2):4.1f}%  regulation games only {100*np.mean(np.abs(d[reg])<=2):4.1f}%   mean miss when OT {np.mean(d[~reg]):+5.1f}")

print('\n9. VALUE OF A WINDOW AT THE 2H LINE, IN CENTS A PAIR (hit share) BY MARGIN, FOR KALSHI-SIZED WINDOWS')
print('   window = numbers strictly between two strikes 2, 4, 6, 8 points apart, centered on the line')
for name, pred in [('close (0-5)', lambda g: g['hm'] <= 5), ('mid (6-14)', lambda g: 6 <= g['hm'] <= 14), ('blowout (15+)', lambda g: g['hm'] >= 15), ('all', lambda g: True)]:
    idx = [i for i, g in enumerate(GL) if pred(g)]
    d = D[idx]
    print(f"   {name:14s} " + '  '.join(f"{w}-wide {100*np.mean(np.abs(d) <= w/2 - 0.5 + 0.49):4.1f}%" for w in (2, 4, 6, 8)))
