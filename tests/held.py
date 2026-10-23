"""held.py against the fixtures, with Supabase and ntfy faked:
1. a held over whose other side is too dear: no push,
2. the under drops to where the pair clears the breakeven: one push, sized to the loss cap, text names both legs,
3. the same prices again: no repeat; 3c better: pushes again,
4. a game at the half is left to the engine; a held under pairs with a lower over,
5. the free tier: hold KC Under 50.5 at 51c. Over 46.5 at 53c is open (a miss costs); at 45c the under pays for the
   over outright (no final loses) and the push says FREE MIDDLE with the protect size; 47c is free only resting."""
import sys, os, json, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, store, held

FIX = os.path.join(ROOT, 'tests', 'fixtures')
EV = 'KXNFLTOTAL-26OCT15BUFLAR'
cfg = watch.load_json(watch.CONFIG_PATH, {})
pushes = []
tables = {}
store.enabled = lambda: True
store.read = lambda table, params: [r for r in tables.get(table, []) if all(
    str(r.get(k)) == v[3:] if v.startswith('eq.') else (str(r.get(k)) != v[4:] if v.startswith('neq.') else True)
    for k, v in params.items() if k != 'select')]
push = lambda title, body, priority='default', tags='football': pushes.append((title, body))


def desk_with(no_ask_485, yes_ask_425=None):
    d = watch.Desk(cfg, {}, FIX)
    events = json.load(open(os.path.join(FIX, 'kalshi_KXNFLTOTAL.json')))['events']
    for m in next(e for e in events if e['event_ticker'] == EV)['markets']:
        if m['floor_strike'] == 48.5:
            m['no_ask_dollars'] = f'{no_ask_485:.4f}'
        if yes_ask_425 is not None and m['floor_strike'] == 42.5:
            m['yes_ask_dollars'] = f'{yes_ask_425:.4f}'
    d._events[('nfl', 'total')] = events
    return d


# 1. hold Over 45.5 (YES, 200 at 48c); No 48.5 asks 64c: pair 115c against a 107.5c breakeven, nothing to say
tables['positions'] = [dict(ticker=f'{EV}-46', event_ticker=EV, position=200, total_traded=96.0, settlement_status='unsettled')]
tables['bets'] = [dict(ticker=f'{EV}-46', outcome_side='yes', count=120, cost=57.6), dict(ticker=f'{EV}-46', outcome_side='yes', count=80, cost=38.4)]
h = held.holdings()
assert len(h) == 1 and h[0]['paid_c'] == 48.0 and h[0]['shares'] == 200 and h[0]['side'] == 'yes', h
d = desk_with(0.64)
assert held.check(d, push) == [] and not pushes
print('held: too dear, no push')

# 2. the under drops to 52c: 48 + 1.7 + 52 + 1.7 = 103.5c, under 107.5c. 200 shares, a miss costs 3.5c a pair = $7
d = desk_with(0.52)
sent = held.check(d, push)
assert len(sent) == 1 and len(pushes) == 1
title, body = pushes[0]
assert title.startswith('MIDDLE OPEN') and 'BUF' in title, title
assert 'Buy No on UNDER 48.5 at 52c, 200 shares' in body and 'Final 46 to 48' in body, body
assert 'loses $7' in body and 'SELL now at 48c' in body, body
assert d.state['held'][f'{EV}-46']['slack_c'] == 4.0, d.state['held']
print('held: middle open pushed once, sized to all 200 shares, both legs named')

# 3. same prices: silent. 49c (3c better a pair): pushes again. 48c (1c more): silent
assert held.check(d, push) == [] and len(pushes) == 1
d2 = desk_with(0.49); d2.state = d.state
assert len(held.check(d2, push)) == 1 and len(pushes) == 2
d3 = desk_with(0.48); d3.state = d.state
assert held.check(d3, push) == [] and len(pushes) == 2
print('held: repeats only on a 2c improvement')

# 4. loss cap: 600 shares at 48c, under at 55c: 48 + 1.7 + 55 + 1.7 = 106.5c, 1c of room. A miss costs 6.5c a pair,
#    so $15 buys 231 pairs and the other 369 stay a single. At 56c (0.0c of room) nothing is pushed
tables['positions'][0]['position'] = 600
tables['bets'] = [dict(ticker=f'{EV}-46', outcome_side='yes', count=600, cost=288.0)]
d4 = desk_with(0.56)
assert held.check(d4, push) == [], 'a pair with no room under the breakeven was pushed'
d4 = desk_with(0.55)
sent = held.check(d4, push)
m = held.best_middle(held.holdings()[0], 45.5, {48.5: dict(n=55, y=45, yb=44, nb=54, ticker='t')})
assert m['pairs'] == int(15 / (m['c'] - 1) + 1e-9) and 200 < m['pairs'] < 600, m
assert len(sent) == 1 and f"{m['pairs']} shares" in sent[0][1] and f"other {600 - m['pairs']} shares stay a single" in sent[0][1], sent[0][1]
print('held: sized to the $15 loss cap, remainder named')

# 5. a game at the half is skipped; a held under (NO on 48.5 at 60c) pairs with Yes on 42.5 when it is cheap
d5 = desk_with(0.52)
d5.state['games'] = {'x': dict(kalshi_total_event=EV, phase='half')}
assert held.check(d5, push) == []
tables['positions'] = [dict(ticker=f'{EV}-49', event_ticker=EV, position=-100, total_traded=60.0, settlement_status='unsettled')]
tables['bets'] = [dict(ticker=f'{EV}-49', outcome_side='no', count=100, cost=60.0)]
d6 = desk_with(0.52, yes_ask_425=0.40)     # 60 + 1.7 + 40 + 1.7 = 103.4c against 0.97 + 6 * 3.5 = 118c
sent = held.check(d6, push)
assert len(sent) == 1 and 'You hold Under 48.5' in sent[0][1] and 'Buy Yes on OVER 42.5 at 40c, 100 shares' in sent[0][1] and 'Final 43 to 48' in sent[0][1], sent[0][1]
print('held: half skipped, held under pairs with a lower over')

# 6. free tier, Nick's own example: hold Under 50.5 (NO on 50.5, 100 at 51c), watch Over 46.5
tables['positions'] = [dict(ticker=f'{EV}-51', event_ticker=EV, position=-100, total_traded=51.0, settlement_status='unsettled')]
tables['bets'] = [dict(ticker=f'{EV}-51', outcome_side='no', count=100, cost=51.0, fee=1.75)]
h = held.holdings()[0]
assert h['fee'] == 1.75 and h['paid_c'] == 51.0
assert held.free_c(h) == 45 and held.free_c(h, 'rest') == 47, (held.free_c(h), held.free_c(h, 'rest'))
n = held.protect_size(h, 45)
o = held.outcomes(h, 45, n)
assert 0 <= o['held_alone'] < 1 and o['other_alone'] >= 0 and o['both'] > 90, (n, o)
quotes = {46.5: dict(y=53, n=50, yb=51, nb=48, ticker='k')}
m = held.best_middle(h, 50.5, quotes)
assert m['tier'] == 'open' and m['pairs'] == 100, m
body = held.text(h, 50.5, m, None, 'LAC @ KC')[1]
assert 'At 45c or less taken (47c resting)' in body, body
quotes[46.5]['y'] = 45
m = held.best_middle(h, 50.5, quotes)
assert m['tier'] == 'free' and m['pairs'] == n and m['held_alone'] == o['held_alone'] and m['other_alone'] == o['other_alone'], m
title, body = held.text(h, 50.5, m, None, 'LAC @ KC')
assert title.startswith('FREE MIDDLE') and f'OVER 46.5 at 45c, {n} shares' in body and 'no final loses' in body and 'Under wins alone = even' in body, body
# the push: open at 53c, then the upgrade to free at 45c goes out even though the room improved by less than 2c... it improved by 8c here, so check the tier upgrade path on its own
pushes.clear()
tables['positions'] = [dict(ticker=f'{EV}-49', event_ticker=EV, position=-100, total_traded=51.0, settlement_status='unsettled')]
tables['bets'] = [dict(ticker=f'{EV}-49', outcome_side='no', count=100, cost=51.0, fee=1.75)]
d7 = desk_with(0.52, yes_ask_425=0.56)      # hold Under 48.5 at 51c; Over 42.5 at 56c: 6 numbers, breakeven 118c, open
assert len(held.check(d7, push)) == 1 and pushes[-1][0].startswith('MIDDLE OPEN')
d8 = desk_with(0.52, yes_ask_425=0.55); d8.state = d7.state
assert held.check(d8, push) == [], 'a 1c improvement inside the open tier repeated the push'
d9 = desk_with(0.52, yes_ask_425=0.45); d9.state = d7.state
sent = held.check(d9, push)
assert len(sent) == 1 and sent[0][0].startswith('FREE MIDDLE') and d9.state['held'][f'{EV}-49']['tier'] == 'free', sent
print('held: free tier sized so the held leg pays for the other, pushed on the upgrade')

# 6. the app's calculator (app/lib/desk.js sizeHeld) prices a held leg the way held.py does: same protect size,
# same three finals, same free price, with the fee paid on the held leg counted. Runs when node is on the box.
import shutil, subprocess
if shutil.which('node'):
    cases = [(49, 153, 2.68, 45, 'take'), (49, 153, 2.68, 52, 'take'), (51, 100, 1.75, 44, 'rest'), (62, 40, 0.66, 36, 'take')]
    script = ("import { sizeHeld } from '%s/app/lib/desk.js';\n" % ROOT.replace('\\', '/')
              + 'const out = [];\n'
              + 'for (const [pa, n, fee, pb, fill] of %s) {\n' % json.dumps(cases)
              + "  const r = sizeHeld({ held: { side: 'over', paid: pa, fill: 'take', shares: n }, other: { price: pb, fill }, numbers: 2, sport: 'nfl', budget: 10 });\n"
              + '  out.push([r.protect.n, r.protect.heldAlone, r.protect.both, r.protect.otherAlone, r.even.heldAlone, r.freeC, r.free]);\n'
              + '}\nconsole.log(JSON.stringify(out));\n')
    tmp = os.path.join(tempfile.mkdtemp(), 'held_check.mjs')
    open(tmp, 'w').write(script)
    got = json.loads(subprocess.run(['node', '--no-warnings', tmp], capture_output=True, text=True, check=True).stdout.strip())
    for (pa, n, fee, pb, fill), g in zip(cases, got):
        hh = dict(shares=n, paid_c=pa, fee=fee, side='yes')
        want_n = held.protect_size(hh, pb, fill)
        want = held.outcomes(hh, pb, want_n, fill)
        assert g[0] == want_n, (pa, n, pb, fill, g[0], want_n)
        assert abs(g[1] - want['held_alone']) < 0.011 and abs(g[2] - want['both']) < 0.011 and abs(g[3] - want['other_alone']) < 0.011, (g, want)
        assert abs(g[4] - held.outcomes(hh, pb, n, fill)['held_alone']) < 0.011, (g[4], held.outcomes(hh, pb, n, fill))
        assert g[5] == held.free_c(hh, fill), (pb, fill, g[5], held.free_c(hh, fill))
        assert g[6] == (want_n >= 1 and want['other_alone'] >= 0), (g[6], want)
    print('held: the app calculator matches held.py on protect size, finals and the free price')
else:
    print('held: node not found, app calculator parity skipped')
print('held: ok')
