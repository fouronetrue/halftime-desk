"""python scripts/study_nba_spreads.py (needs numpy; data/nba_games_h2.csv comes from scripts/build_nba_h2_spread.py over the
raw sportsbookreviewsonline season files, not kept in this repo). Oct 21 asks: how far the lines move at the half (totals and spreads), what that means for a pregame position
that gets a middle later, how favorites that trail at the half do on the spread (full game and second half),
and anything else the archive gives. games 2008-09 through 2019-20 with the market's 2H total and sided
2H spread; the full 24,437-game table for the rest."""
import csv, math, os
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = []
for r in csv.DictReader(open(os.path.join(ROOT, 'data', 'nba_games_h2.csv'))):
    r['h2_total'] = r['h2_total_raw']
    if abs(float(r['h2_total']) - float(r['total']) / 2) > 15:   # two rows with a garbage 2H total in the raw files
        continue
    g = dict(season=int(r['season']), playoffs=int(r['playoffs']), h1a=int(r['h1a']), h1h=int(r['h1h']), fa=int(r['fa']), fh=int(r['fh']),
             total=float(r['total']), hs=float(r['home_spread']), L=float(r['h2_total']), s2=float(r['h2_spread']), s2fav=r['h2_fav'], ot=int(r['ota']) + int(r['oth']))
    g['h1'] = g['h1a'] + g['h1h']; g['ft'] = g['fa'] + g['fh']; g['h2'] = g['ft'] - g['h1']
    hfb = -g['hs']; g['home_fav'] = hfb > 0; g['fav_by'] = abs(hfb)
    m1 = g['h1h'] - g['h1a']; g['hm1'] = m1; g['favm'] = m1 if hfb >= 0 else -m1
    m2 = (g['fh'] - g['h1h']) - (g['fa'] - g['h1a']); g['hm2'] = m2; g['fav2'] = m2 if hfb >= 0 else -m2
    g['favfinal'] = g['favm'] + g['fav2']
    # the 2H spread from the pregame favorite's view: positive = the pregame favorite lays it in the 2H
    fav_is_home = hfb >= 0
    g['s2_fav'] = g['s2'] if (g['s2fav'] == 'home') == fav_is_home else -g['s2']
    G.append(g)
P = print
def pct(x): return f"{100*x:5.1f}%"
def cover(margins, lines):
    m, l = np.array(margins, float), np.array(lines, float)
    return np.mean(m > l) / max(1e-9, np.mean(m != l))

P('=' * 90)
P('A. HOW FAR THE LINES MOVE AT THE HALF (market 2H lines, 2008-09 through 2019-20)')
mv = np.array([g['h1'] + g['L'] - g['total'] for g in G])          # implied full-game total at the half minus the pregame total
pace = np.array([g['h1'] - g['total'] / 2 for g in G])
P(f"   total: the full-game line at the half (half score + 2H line) minus the pregame total: mean {mv.mean():+.2f}, sd {mv.std():.2f}")
P(f"   |move| at least 4: {pct(np.mean(np.abs(mv) >= 4))}, 6: {pct(np.mean(np.abs(mv) >= 6))}, 8: {pct(np.mean(np.abs(mv) >= 8))}, 10: {pct(np.mean(np.abs(mv) >= 10))}, 15: {pct(np.mean(np.abs(mv) >= 15))}")
c = np.polyfit(pace, mv, 1)
P(f"   the move is the first half: line move = {c[1]:+.2f} + {c[0]:.3f} x (first-half points minus half the total); the 2H line itself moves only {np.std([g['L'] - (g['total'] / 2) for g in G]):.1f} sd around half the total")
smv = np.array([g['hm1'] + (g['s2'] if g['s2fav'] == 'home' else -g['s2']) + g['hs'] for g in G])   # implied home margin at the half minus the pregame home margin (-hs)
P(f"   spread: the implied full-game home margin at the half (half margin + 2H spread) minus the pregame margin: mean {smv.mean():+.2f}, sd {smv.std():.2f}")
P(f"   |move| at least 4: {pct(np.mean(np.abs(smv) >= 4))}, 6: {pct(np.mean(np.abs(smv) >= 6))}, 10: {pct(np.mean(np.abs(smv) >= 10))}, 15: {pct(np.mean(np.abs(smv) >= 15))}")
P('   For reference, NFL halftime line moves are about half this size in points on a total one third the size.')

P()
P('B. A PREGAME TOTAL THAT GETS A MIDDLE AT THE HALF')
P('   You bought OVER the pregame total T (at about 50c). At the half the line is T + k. You buy UNDER T + k (at about 50c).')
P('   k      how often   P(final lands in the window)   value of your OVER at the half   = what cashing out would pay')
for k in (4, 6, 8, 10, 12, 15):
    sel = [g for g in G if g['h1'] + g['L'] - g['total'] >= k]
    if not sel: continue
    hit = np.mean([g['total'] < g['ft'] < g['h1'] + g['L'] for g in sel])
    over_now = np.mean([g['ft'] > g['total'] for g in sel])
    P(f"   {k:>3}+   {pct(len(sel) / len(G))}      {pct(hit)}                      {100*over_now:5.1f}c                     {100*over_now - 50:+5.1f}c")
P('   Read: the window hits often, and that is exactly the value the first half already handed your OVER. Middling it = cashing out,')
P('   with the profit kept as a shot at both legs instead of taken now. Zero edge in the structure; the edge, if any, was in the pregame bet.')
P('   Same for a pregame UNDER with the line dropping. The halftime line is right (section C of the Oct 20 doc), so neither side is cheap.')

P()
P('C. THE SECOND-HALF MARGIN: THE HALFTIME LEAD SHRINKS')
P('   fav 2H margin ~ a + b x spread + c x (fav halftime margin), the same games:')
fb = np.array([g['fav_by'] for g in G]); fm = np.array([g['favm'] for g in G]); f2 = np.array([g['fav2'] for g in G], float)
X = np.column_stack([np.ones(len(G)), fb, fm]); c, *_ = np.linalg.lstsq(X, f2, rcond=None); res = f2 - X @ c
P(f"   a {c[0]:+.2f}, b {c[1]:+.3f} per point of pregame spread, c {c[2]:+.3f} per point of halftime margin; residual sd {res.std():.2f}")
P('   favorite halftime margin   n     2H spread on fav (market)   actual fav 2H margin   fav wins 2H   fav covers 2H spread   implied final margin (half + 2H line)   naive (half + spread/2)')
for lo, hi in [(-99, -15), (-15, -8), (-8, -3), (-3, 0), (0, 1), (1, 3), (3, 8), (8, 15), (15, 20), (20, 99)]:
    gs = [g for g in G if lo <= g['favm'] < hi]
    if not gs: continue
    s2 = np.mean([g['s2_fav'] for g in gs]); a2 = np.mean([g['fav2'] for g in gs])
    P(f"   {lo:>4} to {hi:<4}           {len(gs):5d}   {s2:+6.2f}                     {a2:+6.2f}              {pct(np.mean([g['fav2'] > 0 for g in gs]))}       {pct(cover([g['fav2'] for g in gs], [g['s2_fav'] for g in gs]))}              {np.mean([g['favm'] + g['s2_fav'] for g in gs]):+6.1f}                               {np.mean([g['favm'] + g['fav_by'] / 2 for g in gs]):+6.1f}")
P('   Read: a favorite down 15+ at the half wins the second half by 7 on average; a favorite up 15+ loses it by 1 (bench, foul game,')
P('   nothing to play for). The 2H spread market knows: it has the trailing favorite laying 7 to 8 and the leading favorite near pick.')

P()
P("D. NICK'S QUESTION: HOME FAVORITE LOSING AT THE HALF, NOW A DOG")
P('   home fav by   trailing by   n     wins game   covers pregame spread   covers 2H spread   dog (away) covers 2H')
for (lo, hi) in [(0.5, 3), (3.5, 7), (7.5, 10.5), (11, 99)]:
    for (tlo, thi) in [(1, 5), (6, 10), (11, 99)]:
        gs = [g for g in G if g['home_fav'] and lo <= g['fav_by'] <= hi and -thi <= g['favm'] <= -tlo]
        if len(gs) < 60: continue
        P(f"   {lo:>4}-{hi:<5}   {tlo:>2}-{thi:<3}      {len(gs):5d}   {pct(np.mean([g['favfinal'] > 0 for g in gs]))}    {pct(cover([g['favfinal'] for g in gs], [g['fav_by']] * len(gs)))}                 {pct(cover([g['fav2'] for g in gs], [g['s2_fav'] for g in gs]))}            {pct(cover([-g['fav2'] for g in gs], [-g['s2_fav'] for g in gs]))}")
gs = [g for g in G if g['home_fav'] and g['favm'] < 0]
P(f"   all home favorites trailing at the half: n {len(gs)}, win {pct(np.mean([g['favfinal'] > 0 for g in gs]))}, cover pregame {pct(cover([g['favfinal'] for g in gs], [g['fav_by']] * len(gs)))}, cover 2H {pct(cover([g['fav2'] for g in gs], [g['s2_fav'] for g in gs]))}")
gs = [g for g in G if (not g['home_fav']) and g['fav_by'] > 0 and g['favm'] < 0]
P(f"   away favorites trailing at the half:     n {len(gs)}, win {pct(np.mean([g['favfinal'] > 0 for g in gs]))}, cover pregame {pct(cover([g['favfinal'] for g in gs], [g['fav_by']] * len(gs)))}, cover 2H {pct(cover([g['fav2'] for g in gs], [g['s2_fav'] for g in gs]))}")
P('   Read: the pregame cover rate is the pregame bettor\'s hindsight, not a bet (that ticket is placed). The live bet is the 2H spread or')
P('   Kalshi\'s full-game spread ladder at the half, and there the trailing home favorite covers 47 to 50 percent: priced.')

P()
P('E. THE 2H SPREAD MARKET ITSELF: WHO COVERS')
twofav = [g for g in G if g['s2'] > 0]
two_cov = cover([(g['hm2'] if g['s2fav'] == 'home' else -g['hm2']) for g in twofav], [g['s2'] for g in twofav])
P(f"   the 2H favorite covers {pct(two_cov)} (n {len(twofav)}); 2H dogs {pct(1 - two_cov)}. -110 needs 52.4.")
for name, pred in [('2H fav is the pregame fav', lambda g: (g['s2fav'] == 'home') == g['home_fav']), ('2H fav is the pregame dog', lambda g: (g['s2fav'] == 'home') != g['home_fav']),
                   ('2H fav lays 1 or less', lambda g: g['s2'] <= 1), ('2H fav lays 2-4', lambda g: 2 <= g['s2'] <= 4), ('2H fav lays 5-7', lambda g: 5 <= g['s2'] <= 7), ('2H fav lays 8+', lambda g: g['s2'] >= 8),
                   ('2H fav is the home team', lambda g: g['s2fav'] == 'home'), ('2H fav is the away team', lambda g: g['s2fav'] == 'away'),
                   ('2H fav trailing at the half', lambda g: (g['hm1'] if g['s2fav'] == 'home' else -g['hm1']) < 0), ('2H fav leading by 15+', lambda g: (g['hm1'] if g['s2fav'] == 'home' else -g['hm1']) >= 15)]:
    gs = [g for g in twofav if pred(g)]
    if len(gs) < 100: continue
    cv = cover([(g['hm2'] if g['s2fav'] == 'home' else -g['hm2']) for g in gs], [g['s2'] for g in gs])
    P(f"   {name:30s} n {len(gs):5d}  2H fav covers {pct(cv)}  dog {pct(1 - cv)}")
P('   by season (2H dog cover rate):')
P('   ' + '  '.join(f"{s-1}-{str(s)[2:]} {100*(1 - cover([(g['hm2'] if g['s2fav'] == 'home' else -g['hm2']) for g in twofav if g['season'] == s], [g['s2'] for g in twofav if g['season'] == s])):.1f}" for s in sorted({g['season'] for g in twofav})))

P()
P('F. TOTALS AND SPREADS TOGETHER')
h2t = np.array([g['h2'] for g in G], float); am2 = np.abs(np.array([g['hm2'] for g in G], float)); f2 = np.array([g['fav2'] for g in G], float)
P(f"   corr(2H points, |2H margin|) {np.corrcoef(h2t, am2)[0,1]:+.3f}; corr(2H points, fav 2H margin) {np.corrcoef(h2t, f2)[0,1]:+.3f}")
for name, pred in [('fav covers the 2H spread', lambda g: g['fav2'] > g['s2_fav']), ('fav fails the 2H spread', lambda g: g['fav2'] < g['s2_fav']),
                   ('2H margin within 5', lambda g: abs(g['hm2']) <= 5), ('2H margin 15+', lambda g: abs(g['hm2']) >= 15)]:
    gs = [g for g in G if pred(g)]
    P(f"   {name:28s} n {len(gs):5d}  2H over the 2H line {pct(cover([g['h2'] for g in gs], [g['L'] for g in gs]))}  (2H pts {np.mean([g['h2'] for g in gs]):.1f}, line {np.mean([g['L'] for g in gs]):.1f})")
P('   Read: no link. A close second half and a 15-point one score the same (the foul game and garbage time cancel), and the fav')
P('   covering says nothing about the total. An over/cover pair is two bets, not a correlated one.')

P()
P('G. QUARTERS: WHERE THE SECOND-HALF POINTS COME FROM, BY HALFTIME MARGIN (full table, 24,437 games)')
A = []
for r in csv.DictReader(open(os.path.join(ROOT, 'data', 'nba_games.csv'))):
    A.append(dict(hm=abs(int(r['h1h']) - int(r['h1a'])), q3=int(r['q3a']) + int(r['q3h']), q4=int(r['q4a']) + int(r['q4h']), ot=int(r['ota']) + int(r['oth']), fm=abs(int(r['fh']) - int(r['fa'])), season=int(r['season'])))
A = [a for a in A if a['season'] >= 2017]
for lo, hi in [(0, 3), (4, 9), (10, 14), (15, 19), (20, 99)]:
    gs = [a for a in A if lo <= a['hm'] <= hi]
    P(f"   half margin {lo:>2}-{hi:<3}: n {len(gs):5d}  Q3 {np.mean([a['q3'] for a in gs]):5.1f}  Q4 {np.mean([a['q4'] for a in gs]):5.1f}  OT {np.mean([a['ot'] for a in gs]):4.1f}  final margin within 5: {pct(np.mean([a['fm'] <= 5 for a in gs]))}")
P('   Q4 scores the same in a blowout as in a close game: the foul-game points and the garbage-time points cancel. That is why the')
P('   second half is flat and why neither side of the total has a halftime lean.')

P()
P('H. PREGAME: WHERE A CLOSING TOTAL OR SPREAD MISSES (full table, regular season, 2012-13 on; by season for consistency)')
B = []
for r in csv.DictReader(open(os.path.join(ROOT, 'data', 'nba_games.csv'))):
    if int(r['playoffs']) or int(r['season']) < 2013: continue
    hs = float(r['home_spread']); ft = int(r['fa']) + int(r['fh']); hm = int(r['fh']) - int(r['fa'])
    B.append(dict(season=int(r['season']), month=int(r['date'][5:7]), day=r['date'], total=float(r['total']), ft=ft, hs=hs, hm=hm, home_fav=hs < 0, fav_by=abs(hs)))
def pregame(name, pred):
    gs = [b for b in B if pred(b)]
    if len(gs) < 200: return
    over = cover([b['ft'] for b in gs], [b['total'] for b in gs]); hcov = cover([b['hm'] for b in gs], [-b['hs'] for b in gs])
    seasons = sorted({b['season'] for b in gs})
    by = [cover([b['ft'] for b in gs if b['season'] == s], [b['total'] for b in gs if b['season'] == s]) for s in seasons]
    P(f"   {name:40s} n {len(gs):5d}  over {pct(over)} (seasons over 50: {sum(1 for x in by if x > .5)} of {len(by)})  home covers {pct(hcov)}  final minus total {np.mean([b['ft'] - b['total'] for b in gs]):+.2f}")
for m, name in [(10, 'October'), (11, 'November'), (12, 'December'), (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April')]:
    pregame(name, lambda b, m=m: b['month'] == m)
pregame('first 10 days of the season', lambda b: b['month'] == 10 and int(b['day'][8:10]) <= 31 and True)
pregame('home dog', lambda b: not b['home_fav'] and b['fav_by'] > 0)
pregame('home fav by 10+', lambda b: b['home_fav'] and b['fav_by'] >= 10)
pregame('total 235+', lambda b: b['total'] >= 235)
pregame('total under 205', lambda b: b['total'] < 205)
P('   Read: April is the one calendar lean (the league runs loose the last two weeks); everything else is the vig. No Sharp for the NBA')
P('   means the pregame leg of any middle has no edge of its own unless Kalshi\'s pregame line sits off the sharp close, which the')
P('   watcher now records every night (pre_total from ESPN against Kalshi\'s 50-50 line) and can be tested in two weeks.')

P()
P('I. OUT OF SAMPLE: THE 2H MARGIN MODEL VS THE MARKET 2H SPREAD (fit 2008-2015, test 2016-2020)')
tr = [g for g in G if g['season'] <= 2015]; te = [g for g in G if g['season'] >= 2016]
X = lambda gs: np.array([[1.0, g['fav_by'], g['favm']] for g in gs])
cc, *_ = np.linalg.lstsq(X(tr), np.array([g['fav2'] for g in tr], float), rcond=None)
pred = X(te) @ cc; y = np.array([g['fav2'] for g in te], float); L = np.array([g['s2_fav'] for g in te])
P(f"   coef {np.round(cc, 3).tolist()}  MAE model {np.mean(np.abs(y - pred)):.2f}  market {np.mean(np.abs(y - L)):.2f}  model minus market: mean {np.mean(pred - L):+.2f} sd {np.std(pred - L):.2f}")
for k in (1, 2, 3):
    sel = np.abs(pred - L) >= k
    hits = [(y[i] > L[i]) == (pred[i] > L[i]) for i in range(len(y)) if sel[i] and y[i] != L[i]]
    P(f"   model side when it disagrees with the 2H line by {k}+: n {len(hits):4d} hit {100*np.mean(hits):.1f}%")
naive = np.array([g['fav_by'] / 2 for g in te])
P(f"   the naive 2H line (half the spread, no shrink): MAE {np.mean(np.abs(y - naive)):.2f}; naive minus market sd {np.std(naive - L):.2f}; market side vs naive when 3+ apart: {100*np.mean([(y[i] > naive[i]) == (L[i] > naive[i]) for i in range(len(y)) if abs(L[i] - naive[i]) >= 3 and y[i] != naive[i]]):.1f}% (n {sum(1 for i in range(len(y)) if abs(L[i] - naive[i]) >= 3)})")
P()
P('J. THE TEAM UP 15+ AT THE HALF THAT IS STILL THE 2H FAVORITE, by season (2H dog cover rate)')
two = [g for g in G if g['s2'] > 0 and (g['hm1'] if g['s2fav'] == 'home' else -g['hm1']) >= 15]
P('   ' + '  '.join(f"{s-1}-{str(s)[2:]} n{len([g for g in two if g['season'] == s])} {100*(1 - cover([(g['hm2'] if g['s2fav'] == 'home' else -g['hm2']) for g in two if g['season'] == s], [g['s2'] for g in two if g['season'] == s])):.0f}" for s in sorted({g['season'] for g in two})))
