"""The push rewrite of Oct 22, 2026, pinned on the two pushes that prompted it (Patriots at Bears, East Carolina
at Memphis), no network.
1. Order: the score and fair against the book, then the plays, then what you hold, then the resting middle. The
   spot label is out of the push; the book's number is the full-game total, not a second-half line to add up.
2. One position per total: a line a leg with one verdict and one number, the finals together in dollars with
   the chance of each, the window named when the legs are a middle.
3. The no-lose hedge covers the net downside of the whole position: with an under held next to the over, 667
   shares of Under 51.5 (the old FREE line, sized to the over alone) would have lost $88 on the likeliest final;
   the hedge now covers only the $93 the position loses below 51, and every final is zero or better after it.
4. The $15 middle cap counts a middle you already hold: at ECU, the 42.5/45.5 pair already risks $20, so the push
   says nothing new to post instead of offering the same middle again. A lone leg spends none of it."""
import sys, os, copy
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine

BANK, RISK, COST = 3590.0, 89.75, 269.25


def ladder(m, lines, bumps=None):
    rows = engine.price_lines(m, lines)
    q = {}
    for r in rows:
        po, pu = int(round(100 * r['p_over'])), int(round(100 * r['p_under']))
        q[r['line']] = dict(y=min(97, po + 2), n=min(97, pu + 2), yb=max(1, po - 2), nb=max(1, pu - 2), ticker=f"T-{int(r['line'] + 0.5)}")
    for k, v in (bumps or {}).items():
        q[k].update(v)
    return rows, q


# 1. the Patriots: 14-20 at the half, fair 59.5 with the book at 59.5 (sharp 2H 25.5), a position of Over 50.5
#    (279 sh at 52c) and Under 57.5 (140 sh at 63c)
m = engine.HalfModel('nfl', 47.5, -2.5, 20, 14, center=25.5, center_w=0.5)
rows, q = ladder(m, [x + 0.5 for x in range(44, 66)], {51.5: dict(n=19)})
sizing = dict(bankroll=BANK, max_risk=RISK, max_cost=COST, margin=0.03, mid_loss=15, mid_loss_cap=15, held_miss=0)
sug = engine.suggest(rows, q, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
legs = [dict(ticker='T-51', side='yes', strike=50.5, shares=279, paid_c=52.0, fee=2.0),
        dict(ticker='T-58', side='no', strike=57.5, shares=140, paid_c=63.0, fee=1.4)]
pos = engine.held_position(rows, q, legs)
regs = pos['regions']
assert [(g['lo'], g['hi']) for g in regs] == [(None, 50.0), (51.0, 57.0), (58.0, None)], regs
assert regs[0]['pnl'] == -96.68 and regs[1]['pnl'] == 182.32 and regs[2]['pnl'] == 42.32, regs   # fees in
assert abs(sum(g['p'] for g in regs) - 1) < 1e-6 and regs[2]['p'] > regs[1]['p'] > regs[0]['p'], 'the finals carry the ladder\'s own odds and sum to one'
assert pos['window'] == (51.0, 57.0) and pos['miss_loss'] == 96.68 and not pos['no_lose']
hd = pos['hedge']
assert hd and hd['kind'] == 'under' and hd['strike'] == 51.5 and hd['ask_c'] == 19, hd
assert 115 <= hd['shares'] <= 125 and hd['cost'] < 30, 'the hedge covers the $97 below 51, not the over\'s whole win'
after = {(g['lo'], g['hi']): g['pnl'] for g in hd['regions']}
assert min(after.values()) >= 0 and after[(None, 50.0)] < 3 and after[(51.0, 51.0)] > 250 and after[(58.0, None)] > 10, after
# the old sizing, the over's win as the budget, is what Nick caught: 667 shares put the only loss on 58 or more
old = engine.pnl_regions(legs + [dict(side='no', strike=51.5, shares=667, paid_c=19, fee=engine.order_fee(667, 0.19))])
assert old[-1]['pnl'] < -80, old
lines = engine.held_block(pos)
assert lines[0] == 'YOU HOLD Over 50.5, 279 sh at 52c. Worth 80c. Hold.' and lines[1] == 'YOU HOLD Under 57.5, 140 sh at 63c. Worth 46c. Hold.', lines
assert lines[2].startswith("Together it's a 51 to 57 middle: 50 or less -$97 (") and '51 to 57 +$182 (' in lines[2] and '58 or more +$42 (' in lines[2], lines[2]
assert lines[3].startswith(f"NO-LOSE HEDGE: buy Under 51.5 at 19c, {hd['shares']} sh (${hd['cost']:.0f}). Then 50 or less $0, 51 +$") and '58 or more +$' in lines[3], lines[3]
inp = dict(away='NE', home='CHI', away_name='Patriots', home_name='Bears', h1a=14, h1h=20, sharp=25.5)
kind, head, body = engine.order_sheet(m, inp, rows, sug, sizing, held=lines)
assert kind == 'UPDATE' and head == 'UPDATE: Patriots 14, Bears 20'
L = body.split('\n')
assert L[0] == 'Fair 58.5. Book 59.5.' and L[1] == '' and L[2].startswith('YOU HOLD Over 50.5'), L[:3]
assert 'lean' not in body and 'Sharp' not in body and 'FREE' not in body and 'POSSIBLE' not in body, body
assert body.index('NO-LOSE HEDGE') < body.index('REST A MIDDLE:'), 'the position comes before the resting middle'
rest = body[body.index('REST A MIDDLE:'):].split('\n')
assert rest[1].startswith('Over ') and ' sh ($' in rest[1] and rest[2].startswith('Under ') and ' pays +$' in rest[3] and 'Any other final -$' in rest[3] and rest[3].endswith('One leg alone is a fair single.'), rest
print('patriots: one position, the window and the finals in dollars, the hedge sized to the downside, the fixed order')

# the same read with nothing held: the push is the header and the resting middle
kind, head, body0 = engine.order_sheet(m, dict(inp, sharp=None), rows, sug, sizing)
assert body0.split('\n')[0] == 'Fair 58.5.' and 'Book' not in body0 and 'YOU HOLD' not in body0 and body0.split('\n')[2] == 'REST A MIDDLE:', body0

# 2. East Carolina 16, Memphis 3: the 42.5/45.5 middle already held (117 sh at 62c, 121 sh at 50c) risks $20 on a
#    miss, past the $15 cap, so nothing new is posted and the cleared middle (if any) is not a play
m2 = engine.HalfModel('cfb', 46.5, -7.5, 3, 16, center=27.5, center_w=0.8)
rows2, q2 = ladder(m2, [x + 0.5 for x in range(36, 56)])
legs2 = [dict(ticker='T-43', side='yes', strike=42.5, shares=117, paid_c=62.0, fee=1.9), dict(ticker='T-46', side='no', strike=45.5, shares=121, paid_c=50.0, fee=2.1)]
miss = engine.held_miss_loss(legs2)
assert abs(miss - 20.04) < 0.01, miss
room = max(0.0, 15 - miss)
sug2 = engine.suggest(rows2, q2, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), room)
assert not any(x['ok'] for x in sug2['mids']), 'no middle fits inside a spent cap'
sizing2 = dict(sizing, mid_loss=room, held_miss=miss)
pos2 = engine.held_position(rows2, q2, legs2)
lines2 = engine.held_block(pos2)
assert lines2[2].startswith("Together it's a 43 to 45 middle: 42 or less -$16 (") and '43 to 45 +$101 (' in lines2[2] and '46 or more -$20 (' in lines2[2], lines2
assert pos2['hedge'] is None, 'a middle that loses on both sides has no one-leg no-lose hedge'
kind, head, body2 = engine.order_sheet(m2, dict(away='ECU', home='MEM', away_name='East Carolina', home_name='Memphis', h1a=16, h1h=3, sharp=27.5), rows2, sug2, sizing2, held=lines2)
assert kind == 'UPDATE' and body2.split('\n')[0].startswith('Fair ') and body2.split('\n')[0].endswith('. Book 46.5.'), body2
assert body2.rstrip().endswith('Nothing new to post: what you hold already risks $20 on a miss, the $15 middle cap.') and 'REST A MIDDLE' not in body2, body2
# with the cap not yet spent the resting middle posts as usual
sizing3 = dict(sizing, mid_loss=15, held_miss=0)
sug3 = engine.suggest(rows2, q2, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
kind, head, body3 = engine.order_sheet(m2, dict(away='ECU', home='MEM', h1a=16, h1h=3), rows2, sug3, sizing3)
assert 'REST A MIDDLE:' in body3 and 'Nothing new to post' not in body3, body3
# a lone leg spends none of the cap
assert engine.held_miss_loss(legs2[:1]) == 0 and engine.held_miss_loss([legs2[1]]) == 0
assert engine.held_miss_loss([dict(legs2[0], strike=45.5), dict(legs2[1], strike=42.5)]) == 0, 'a reverse is not a middle'
print('ecu: a held middle spends the cap, the push says so instead of posting the same middle again')

# 3. a PLAY keeps its shape: singles, the middle, then the position, with the miss as a signed dollar line
cheap = copy.deepcopy(q)
cheap[57.5].update(n=30, nb=26)   # an under beyond the held over, cheap at the ask
sug4 = engine.suggest(rows, cheap, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
assert any(x['ok'] for x in sug4['singles'])
pos4 = engine.held_position(rows, cheap, legs[:1])
kind, head, body4 = engine.order_sheet(m, inp, rows, sug4, sizing, held=engine.held_block(pos4))
assert kind == 'PLAY' and body4.split('\n')[2].startswith('Buy UNDER 57.5 for $') and body4.index('Buy UNDER') < body4.index('YOU HOLD'), body4
assert 'PAIR IT' not in body4 and 'LAY OFF' not in body4, 'a cleared leg is a play; it is not repeated as a pairing'
if any(x['ok'] for x in sug4['mids']):
    mid = body4[body4.index('MIDDLE'):].split('\n')
    assert mid[1].startswith('Over ') and mid[3].count('pays +$') == 1 and ('Any other final -$' in mid[3] or 'free roll' in mid[3]), mid
assert engine.miss_text(-5.4) == '-$5' and engine.miss_text(2.0) == '+$2 (free roll)' and engine.miss_text(0.2) == '$0 (free roll)'
print('play: singles first, the middle, then the position; the miss is a signed dollar line')
print('push: ok')
