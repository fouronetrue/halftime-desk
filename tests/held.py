"""held.py against the fixtures, with Supabase and ntfy faked:
1. a held over whose other side is too dear: no push,
2. the under drops to where the pair clears the breakeven: one push, sized to the loss cap, text names both legs,
3. the same prices again: no repeat; 3c better: pushes again,
4. a game at the half is left to the engine; a held under pairs with a lower over."""
import sys, os, json
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
print('held: ok')
