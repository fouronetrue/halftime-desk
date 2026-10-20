"""Reverse middles and held positions at the half, no network.
1. engine.suggest scores the reverse middle (NO on a lower strike plus YES on a higher one): its EV is the two
   legs' single edges added together, a normal ladder clears none, a ladder whose wings are cheap clears one,
   and it is sized as one bet under the single caps (quarter Kelly on the pair, the hole loss as the risk).
2. order_sheet names it in a PLAY after the singles and the middle ("instead of, not on top"), leads with it
   when it is all that clears, and the sheet's lead is 'rev' only then; grade_sheet pays one leg outside the
   hole and loses the pair inside it.
3. held_options prices a total you own off the same ladder: SELL when the bid net of fee pays the margin over
   fair, HOLD otherwise; PAIR IT when the other side beyond your strike clears as a single; LAY OFF when the
   other side short of it does; FREE when your leg pays for the completion outright.
4. The fixtures run with a holding on the halftime game: the push carries the YOU HOLD block after its text,
   the sheet and the suggestions row keep it; a read with a SELL verdict leads with the block at high priority."""
import sys, os, json, copy, tempfile, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine, watch, notify, store

m = engine.HalfModel('nfl', 55.5, -3.5, 7, 13)
LINES = [41.5, 42.5, 43.5, 44.5, 45.5, 46.5, 47.5, 48.5, 49.5, 50.5, 51.5, 52.5]
rows = engine.price_lines(m, LINES)
BANK, RISK, COST = 3590.0, 89.75, 269.25
SIZING = dict(bankroll=BANK, max_risk=RISK, max_cost=COST, margin=0.03, mid_loss=15)
fair_q = {r['line']: dict(y=int(round(100 * r['p_over'])) + 2, n=int(round(100 * r['p_under'])) + 2,
                          yb=int(round(100 * r['p_over'])) - 2, nb=int(round(100 * r['p_under'])) - 2) for r in rows}

# 1. scoring
s = engine.suggest(rows, fair_q, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
assert s['revs'] and not any(r['ok'] for r in s['revs']), 'a ladder at fair should clear no reverse middle'
for r in s['revs']:
    edges = {(l['kind'], l['line']): l['edge'] for l in s['legs']}
    assert abs(r['ev'] - (edges[('under', r['a']['line'])] + edges[('over', r['b']['line'])])) < 1e-9, 'EV must equal the two single edges added'
    assert r['a']['line'] < r['b']['line'] and r['lo'] == r['a']['line'] + 0.5 and r['hi'] == r['b']['line'] - 0.5
wings = copy.deepcopy(fair_q)
wings[45.5] = dict(y=75, n=28, yb=71, nb=24)   # the under at 45.5 is cheap
wings[49.5] = dict(y=35, n=68, yb=31, nb=64)   # the over at 49.5 is cheap
s2 = engine.suggest(rows, wings, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
ok = [r for r in s2['revs'] if r['ok']]
assert len(ok) == 1 and ok[0]['a']['line'] == 45.5 and ok[0]['b']['line'] == 49.5, [(r['a']['line'], r['b']['line']) for r in ok]
r = ok[0]
assert r['ev'] >= 0.03 and r['pairs'] >= 1 and abs(r['cost'] - r['pairs'] * r['c']) < 0.05, r
assert r['cost'] <= RISK + 1e-9 and r['cost'] <= COST + 1e-9, 'the hole loss is the risk and sits under the single caps'
assert r['win'] == round(r['pairs'] - r['cost'], 2) and r['lose'] == round(-r['cost'], 2)
f = 0.25 * r['ev'] / (1 - r['c'])
assert r['pairs'] == min(int(min(f * BANK, RISK) / r['c'] + 1e-9), int(COST / r['c'] + 1e-9)), 'quarter Kelly on the pair'
print(f"scoring: EV is the sum of the single edges; cheap wings clear at +{100 * r['ev']:.1f}c, {r['pairs']} pairs, hole loss ${r['cost']:.0f}")

# 2. the push and the grade
inp = dict(away='BUF', home='LAR', h1a=13, h1h=7)
kind, head, body = engine.order_sheet(m, inp, rows, s2, SIZING)
assert kind == 'PLAY' and 'REVERSE MIDDLE (instead of the above, not on top):' in body, body
assert body.index('Buy UNDER 45.5 for') < body.index('REVERSE MIDDLE'), 'the single leads, the reverse follows'
assert f"Buy UNDER 45.5 at 28c ({r['pairs']} shares for ${r['pairs'] * 0.28:.0f})" in body and f"Buy OVER 49.5 at 35c ({r['pairs']} shares" in body, body
assert 'Final 45 or less, or 50 or more, pays one leg' in body and 'final 46 to 49 loses both' in body, body
kind, head, body = engine.order_sheet(m, inp, rows, s2, dict(SIZING, near_pts=6.5), focus='middles')
assert kind == 'PLAY' and 'REVERSE MIDDLE' in body and body.index('REVERSE MIDDLE') < body.index('RESTING MIDDLE'), body
only = copy.deepcopy(fair_q)
only[45.5] = dict(y=75, n=32, yb=71, nb=28)
only[49.5] = dict(y=35, n=68, yb=31, nb=64)
s3 = engine.suggest(rows, only, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
s3['mids'] = [dict(x, ok=False) for x in s3['mids']]   # the crossed fake quotes also open a middle; take it away so only the reverse stands
assert not any(x['ok'] for x in s3['singles']) and engine.chosen_rev(s3), 'the reverse should be all that clears'
kind, head, body = engine.order_sheet(m, inp, rows, s3, SIZING)
assert kind == 'PLAY' and body.split('\n')[2] == 'REVERSE MIDDLE:', body
kind, head, body = engine.order_sheet(m, inp, rows, s, SIZING)
assert kind == 'UPDATE' and 'REVERSE' not in body, 'an UPDATE says nothing about reverse middles'
rv = engine.chosen_rev(s3)
sh = dict(lead='rev', singles=[], mid=None, rest_mid=None, total=55.5, spread=-3.5, h1a=13, h1h=7, fair=47.5, mkt=47.5,
          rev=dict(a_line=45.5, a_price=32, b_line=49.5, b_price=35, pairs=rv['pairs'], cost=rv['cost']))
g = watch.grade_sheet(sh, 44)
assert g['lead'] == 'rev' and g['win'] is True and g['pnl'] == round(rv['pairs'] - rv['cost'], 2) and g['cost'] == round(rv['cost'], 2) and g['rev_hole'] is False, g
g = watch.grade_sheet(sh, 47)
assert g['win'] is False and g['pnl'] == round(-rv['cost'], 2) and g['rev_hole'] is True and g['detail'] == f"rev 45.5/49.5 HOLE {-rv['cost']:+.0f}", g
g = watch.grade_sheet(dict(sh, lead='single', singles=[dict(kind='under', line=45.5, price_c=32, contracts=100, cost=33.0)]), 44)
assert g['lead'] == 'single' and g['pnl'] == 67.0 and g['rev_pnl'] == round(rv['pairs'] - rv['cost'], 2) and g['n_plays'] == 2, 'a single leads; the reverse is graded on the side'
print('push: the reverse follows the single and the middle, leads when alone; grade: one leg outside the hole, the pair inside it')

# 3. held options
h = dict(side='yes', strike=44.5, shares=100, paid_c=48, fee=1.75)
s = engine.suggest(rows, fair_q, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
o = engine.held_options(rows, fair_q, h)
assert o['sell']['verdict'] == 'HOLD' and o['sell']['bid_c'] == 58 and o['pair'] is None and o['layoff'] is None, o
assert abs(o['hold_ev'] - (100 * rows[3]['used_over'] - 49.75)) < 0.01 and abs(o['sell']['pnl'] - (58 - 49.75 - engine.order_fee(100, 0.58))) < 0.01, o
assert o['free'] and o['free']['strike'] == 45.5 and o['free']['mine_alone'] >= 0 and o['free']['other_alone'] >= 0 and o['free']['edge_c'] < 0, o['free']
moved = copy.deepcopy(fair_q)
moved[44.5] = dict(fair_q[44.5], yb=68)     # the bid runs past fair
moved[47.5] = dict(fair_q[47.5], n=44)      # a cheap under beyond: the completion
moved[42.5] = dict(fair_q[42.5], n=25)      # a cheap under short of it: the lay-off
engine.suggest(rows, moved, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
o = engine.held_options(rows, moved, h)
assert o['sell']['verdict'] == 'SELL' and o['sell']['pnl'] > o['sell']['hold'], o['sell']
assert o['pair'] and o['pair']['strike'] == 47.5 and o['pair']['shares'] == 100 and o['pair']['lo'] == 45 and o['pair']['hi'] == 47 and o['pair']['edge_c'] >= 3, o['pair']
assert o['pair']['both'] > o['pair']['mine_alone'] and o['pair']['both'] > o['pair']['other_alone']
assert o['layoff'] and o['layoff']['strike'] == 42.5 and o['layoff']['lo'] == 43 and o['layoff']['hi'] == 44 and o['layoff']['neither'] < 0 < o['layoff']['mine_alone'], o['layoff']
lines = engine.held_lines(h, o)
assert lines[0] == 'YOU HOLD Over 44.5, 100 sh at 48c. Fair now 60c.' and lines[1].startswith('Bid 68c: SELL.'), lines
assert any(l.startswith('PAIR IT: Buy UNDER 47.5 at 44c, 100 sh') for l in lines) and any(l.startswith('LAY OFF: Buy UNDER 42.5 at 25c, 100 sh') for l in lines), lines
assert 'Final 45 or more pays your over' in ''.join(lines) and '42 or less pays the under' in ''.join(lines) and '43 to 44 loses both' in ''.join(lines), lines
h2 = dict(side='no', strike=49.5, shares=80, paid_c=55, fee=1.4)
cheap_over = copy.deepcopy(fair_q)
cheap_over[46.5] = dict(fair_q[46.5], y=40)
engine.suggest(rows, cheap_over, 'taker', 0.03, 0.5, BANK, RISK, COST, (15, 85), 15)
o = engine.held_options(rows, cheap_over, h2)
assert o['pair'] and o['pair']['kind'] == 'over' and o['pair']['strike'] == 46.5 and o['pair']['lo'] == 47 and o['pair']['hi'] == 49, o['pair']
assert engine.held_options(rows, fair_q, dict(h, strike=60.5)) is None, 'a strike the ladder did not price is skipped'
print('held: HOLD at a bid under fair, SELL past it; PAIR IT beyond the strike, LAY OFF short of it, FREE when the leg pays for it')

# 4. the fixtures run with a holding
FIX = os.path.join(ROOT, 'tests', 'fixtures')
EV = 'KXNFLTOTAL-26OCT15BUFLAR'
pushes, written = [], []
notify.push = lambda title, body, priority='default', tags='football': (pushes.append((title, body, priority)) or ['test'])
store.enabled = lambda: True
store.write = lambda table, rows_, on_conflict=None, ignore_duplicates=False: (written.append((table, copy.deepcopy(rows_))) or True)
store.claim = lambda table, row, on_conflict: True
store.read = lambda table, params: []
scratch = tempfile.mkdtemp()
watch.LOG_PATH = os.path.join(scratch, 'halftime_log.csv'); watch.RESULTS_PATH = os.path.join(scratch, 'results.csv')
cfg = dict(watch.load_json(watch.CONFIG_PATH, {}), sports=['nfl'])
d = watch.Desk(cfg, {}, FIX)
d.holdings = {EV: [dict(ticker=f'{EV}-46', event_ticker=EV, sport='nfl', side='yes', shares=60, paid_c=44.0, fee=1.05)]}
d.run_pass()
assert len(pushes) == 1 and pushes[0][0].startswith('UPDATE:') and pushes[0][2] == 'default', pushes
body = pushes[0][1]
assert 'YOU HOLD Over 45.5, 60 sh at 44c.' in body and body.index('YOU HOLD') > body.index('POSSIBLE MIDDLE') and 'HOLD. Sell now' in body, 'with nothing to do the block follows the read and the priority stays'
sh = d.state['games']['401']['sheet']
assert sh.get('held') and sh['held'][0]['strike'] == 45.5 and sh['held'][0]['options']['sell'], sh.get('held')
sug_rows = [r for t, rs in written if t == 'suggestions' for r in rs]
assert sug_rows and sug_rows[-1]['held'][0]['ticker'] == f'{EV}-46' and 'revs' in sug_rows[-1], 'the suggestions row carries held and revs'
# a read whose held leg should be sold: the halftime ladder at fair, the bid at 45.5 run up past it
fix = json.load(open(os.path.join(FIX, 'kalshi_KXNFLTOTAL.json')))
hm = engine.HalfModel('nfl', 55.5, -3.5, 7, 13)
for mk in fix['events'][0]['markets']:
    k = mk['floor_strike']
    po = hm.p_over_2h(k - 20)
    yb, y = max(1, int(round(100 * po)) - 2), min(99, int(round(100 * po)) + 2)
    mk['yes_bid_dollars'], mk['yes_ask_dollars'], mk['no_bid_dollars'], mk['no_ask_dollars'] = f'{yb / 100:.4f}', f'{y / 100:.4f}', f'{(100 - y) / 100:.4f}', f'{(100 - yb) / 100:.4f}'
    if k == 45.5:
        mk['yes_bid_dollars'], mk['yes_ask_dollars'] = '0.6400', '0.6600'
flat = tempfile.mkdtemp()
for f in os.listdir(FIX):
    shutil.copy(os.path.join(FIX, f), flat)
json.dump(fix, open(os.path.join(flat, 'kalshi_KXNFLTOTAL.json'), 'w'))
pushes.clear()
d = watch.Desk(dict(cfg, read_push={'nfl': 'min'}), {}, flat)
d.holdings = {EV: [dict(ticker=f'{EV}-46', event_ticker=EV, sport='nfl', side='yes', shares=60, paid_c=44.0, fee=1.05)]}
d.run_pass()
assert len(pushes) == 1 and pushes[0][0].startswith('UPDATE:') and pushes[0][2] == 'high', pushes
body = pushes[0][1]
assert body.startswith('YOU HOLD Over 45.5') and 'Bid 64c: SELL.' in body, body
pushes.clear()
d = watch.Desk(dict(cfg, read_push={'nfl': 'min'}), {}, flat)
d.run_pass()
assert len(pushes) == 1 and pushes[0][2] == 'min' and 'YOU HOLD' not in pushes[0][1], 'with nothing held the read is the quiet read it was'
print('fixtures: a read carries YOU HOLD after its text; a read with a SELL verdict leads with it at high priority')
print('reverse: ok')
