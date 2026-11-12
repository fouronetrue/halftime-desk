"""scripts/readout.py, the readouts the export job prints into data/desk:
1. The shadow summary: resting orders, would-fills at the break vs in play (a break is the break of the stage that
   posted the order: a half order touched at the end of the third was filled in play), tight vs wide pair, timing
   buckets, middles with both legs or one leg filled, P&L split the same way, takes; the file holds counts and
   dollars only, never a ticker, strike, price or id.
2. The honest scorecard: the results table's row wins over the CSV's, a CSV-only game is kept; the lead play per
   window by week (Tuesday start) and sport, the NBA misreads called out, the end-of-third window counted as its
   own window, finals against the market, the shadow shots and the came-and-went lines graded from the sheet."""
import sys, os, json, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scripts import readout as ro

CID = 'c0ffee00-0000-4000-8000-%012d'


def order(i, game, stage, side, strike, price, count, reason, pair, kind='rest', status='planned', phase=None, secs=None, pnl=None, mode='shadow', sport='nba', date='2026-10-22'):
    return dict(client_order_id=CID % i, created_at=f'{date}T23:40:00+00:00', game_id=game, sport=sport, game='BOS @ DET', date_et=date,
                event_ticker='KXNBATOTAL-26OCT22BOSDET', market_ticker=f'KXNBATOTAL-26OCT22BOSDET-{strike:g}', strike=strike, side=side, action='buy',
                kind=kind, stage=stage, price_c=price, count=count, cost=round(count * price / 100, 2), expire_at=f'{date}T23:59:00+00:00', reason=reason,
                pair=pair, mode=mode, status=status, touch_phase=phase, touch_s=secs, pnl=pnl)


ORDERS = [
    # g1, the half: the tight pair fills both legs (one at the break, one in play after the score moved)
    order(1, 'g1', 'half', 'yes', 210.5, 46, 50, 'rest_mid', '210.5/216.5', status='touched', phase='half', secs=40, pnl=27.0),
    order(2, 'g1', 'half', 'no', 216.5, 50, 50, 'rest_mid', '210.5/216.5', status='touched', phase='live', secs=1900, pnl=-25.0),
    # the wide pair: one leg touched at the end of the third, which for a half order is in play
    order(3, 'g1', 'half', 'yes', 206.5, 40, 30, 'rest_mid wide', '206.5/220.5', status='expired'),
    order(4, 'g1', 'half', 'no', 220.5, 44, 30, 'rest_mid wide', '206.5/220.5', status='touched', phase='q3end', secs=1700, pnl=-13.2),
    # the push's lead middle as takes: one ask was still there, the other was not
    order(5, 'g1', 'half', 'yes', 212.5, 55, 40, 'play_mid', '212.5/214.5', kind='take', status='touched', phase='half', secs=5, pnl=10.0),
    order(6, 'g1', 'half', 'no', 214.5, 60, 40, 'play_mid', '212.5/214.5', kind='take', status='expired'),
    # g2, the end of the third: one leg touched at q3end, which is that stage's break
    order(7, 'g2', 'q3', 'yes', 224.5, 48, 20, 'rest_mid', '224.5/228.5', status='touched', phase='q3end', secs=200, pnl=10.4),
    order(8, 'g2', 'q3', 'no', 228.5, 49, 20, 'rest_mid', '224.5/228.5', status='expired'),
    # g3, an NFL ladder order, another night
    order(9, 'g3', 'half', 'yes', 44.5, 50, 10, 'ladder', None, sport='nfl', date='2026-10-25', status='expired'),
    # a live-mode fill on g1 sits in its own row
    order(10, 'g1', 'half', 'yes', 208.5, 42, 5, 'rest_mid', '208.5/218.5', mode='live', status='filled', pnl=2.9),
]

rows = ro.shadow_rows(ORDERS, '2026-10-22')
assert [(r['sport'], r['mode']) for r in rows] == [('nba', 'live'), ('nba', 'shadow')], rows
s = rows[1]
assert s['games'] == 2 and s['rest_orders'] == 6 and s['rest_cost'] == 23.0 + 25.0 + 12.0 + 13.2 + 9.6 + 9.8, s
assert s['rest_touched'] == 4 and s['touched_break'] == 2 and s['touched_play'] == 2, s   # g1 yes at the half, g2 at its break; g1 no in play, the wide leg at q3end
assert s['tight_orders'] == 4 and s['tight_touched'] == 3 and s['wide_orders'] == 2 and s['wide_touched'] == 1 and s['other_orders'] == 0
assert (s['touch_under_60s'], s['touch_1_5m'], s['touch_5_15m'], s['touch_later']) == (1, 1, 0, 2) and s['touch_median_s'] == 1700, s
assert s['middles'] == 3 and s['middles_both'] == 1 and s['middles_one'] == 2, s
assert s['graded'] == 4 and s['pnl'] == round(27 - 25 - 13.2 + 10.4, 2) and s['pnl_both'] == 2.0 and s['pnl_lone'] == round(-13.2 + 10.4, 2), s
assert s['pnl_break'] == round(27 + 10.4, 2) and s['pnl_play'] == round(-25 - 13.2, 2) and s['middles_both_break'] == 0 and s['pnl_both_break'] == 0, s
assert s['pnl_cost'] == round(23 + 25 + 13.2 + 9.6, 2), s
assert s['takes'] == 2 and s['takes_available'] == 1 and s['takes_pnl'] == 10.0, s
live = rows[0]
assert live['rest_orders'] == 1 and live['rest_touched'] == 1 and live['middles_one'] == 1 and live['pnl'] == 2.9, live
text = ro.shadow_csv(rows)
assert text.splitlines()[0] == ','.join(ro.SHADOW_COLS)
for word in ('KXNBA', '210.5', '216.5', 'c0ffee', 'BOS @ DET', 'client'):
    assert word not in text, word
nfl = ro.shadow_rows(ORDERS, '2026-10-25')
assert len(nfl) == 1 and nfl[0]['sport'] == 'nfl' and nfl[0]['other_orders'] == 1 and nfl[0]['rest_touched'] == 0 and nfl[0]['middles'] == 0
assert len(ro.shadow_rows(ORDERS)) == 3
print('readout: shadow summary counts fills by the stage that posted the order, pairs and timing, no order details')

# 2. the scorecard
def res(sport, game, date, cost, pnl, rest=None, final=None, mkt=None, model_err=None, mkt_err=None, sheet=None, q3=None, flick=None, src='db', fair=None, q3_gap=1.0):
    r = dict(sport=sport, game=game, final_total=final, mkt=mkt, total=(mkt - 2) if mkt is not None else None, fair=fair if fair is not None else (mkt + 1) if mkt is not None else None,
             model_err=model_err, mkt_err=mkt_err, plays_cost=cost, plays_pnl=pnl, rest_mid_pnl=rest, sheet=sheet, flickers=flick)
    if src == 'db':
        r.update(date_et=date, game_id=game.replace(' ', ''))
    else:
        r.update(settled_utc=f'{date}T03:00:00+00:00', date=date)
    if q3:
        r.update(q3_score='50-55', q3_plays_cost=q3[0], q3_plays_pnl=q3[1], q3_rest_mid_pnl=q3[2], q3_fair=230.5 - q3_gap, q3_mkt=230.5)
    return r


shot = dict(mu_model=25.0, h1a=10, h1h=20, shot=dict(picks=[dict(kind='under', line=63.5, price_c=83, contracts=106, cost=88.0)]))
db = [res('cfb', 'MEM @ TULN', '2026-10-24', 79.4, -79.4, rest=-6.4, final=48, mkt=61.0, model_err=12.5, mkt_err=13.0, sheet=shot,
          flick=[dict(kind='single', pushed=False, win=True, pnl=40.0), dict(kind='mid', pushed=True, win=False, pnl=-9.0)]),
      res('nba', 'MIA @ CHA', '2026-10-24', 132.0, -132.0, rest=12.0, final=222, mkt=231.0, fair=172.5, model_err=50.5, mkt_err=9.0),     # a misread play, 58.5 off the market
      res('nba', 'GS @ PHX', '2026-10-24', 0.0, 0.0, rest=-5.0, final=236, mkt=224.0, model_err=71.5, mkt_err=12.0, q3=(132.0, -132.0, -4.0), q3_gap=61.0),   # a misread at the end of the 3rd
      res('nba', 'DEN @ OKC', '2026-10-26', 0.0, 0.0, rest=30.0, final=210, mkt=228.0, model_err=20.0, mkt_err=18.0, q3=(100.0, 150.0, 20.0)),
      res('nfl', 'PIT VS NO', '2026-10-25', 64.9, 77.1, rest=-7.5, final=26, mkt=44.0, model_err=18.5, mkt_err=18.0)]
csvr = [res('cfb', 'MEM @ TULN', '2026-10-24', 0.0, 0.0, src='csv'),                                     # the table's row wins
        res('cfb', 'WSU @ ORST', '2026-10-17', 79.37, -79.37, rest=-6.4, final=78, mkt=63.5, model_err=16.5, mkt_err=14.5, src='csv'),
        res('nfl', 'ARI @ LAR', '2026-10-18', 64.93, 77.07, final=40, mkt=44.5, model_err=4.5, mkt_err=4.5, src='csv'),
        dict(settled_utc='settled_utc', sport='sport', game='game', date='date')]                       # a header line among the rows
rows = ro.dedupe(db, csvr)
assert len(rows) == 7 and sum(1 for r in rows if r['src'] == 'csv') == 2
assert next(r for r in rows if r['game'] == 'MEM @ TULN')['plays_cost'] == 79.4, 'the results table row wins'
wins = ro.windows(rows)
assert len(wins) == 9 and sum(1 for w in wins if w['stage'] == 'q3') == 2
assert ro.week_start('2026-10-17') == dt.date(2026, 10, 13) and ro.week_start('2026-10-20') == dt.date(2026, 10, 20) and ro.week_start('2026-10-26') == dt.date(2026, 10, 20)
tbl = ro.play_table(wins)
assert '| Oct 17 to Oct 18 | CFB | 1 | 0 | $79 | $-79 |' in tbl and '| Oct 17 to Oct 18 | NFL | 1 | 1 | $65 | $+77 |' in tbl, tbl   # the week's graded slates, plays or not
assert '| Oct 24 to Oct 26 | NBA | 3 | 1 | $364 | $-114 |' in tbl, tbl                     # the half play and the two end-of-third plays
assert '| all | all | 7 | 3 | $653 | $-119 |' in tbl, tbl
assert '| all, without the misreads | all | 5 | 3 | $389 | $+145 |' in tbl, tbl         # the Oct 26 end-of-third play sat a point off the market and stays
assert any(line.startswith('Misreads: 2 plays ($-264)') and 'NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132.' in line for line in tbl), tbl
text = ro.scorecard_md(db, csvr, ORDERS, now=dt.datetime(2026, 10, 27, 12, tzinfo=dt.timezone.utc))
assert 'from the Supabase results table (5 games' in text and 'plus the 2 games only log/results.csv has' in text and '9 windows on 7 games' in text, text
assert 'End of 3rd (NBA): 2 windows graded, 2 with a play, $+18 on $232.' in text, text
assert '| NBA | 3 | 0 | 0 | 47.3 | 13.0 | -5.0 on 3 (-0.6 SE), over 33% | -3.0 on 3 (-0.3 SE), over 33% |' in text, text   # finals vs the market: -9, +12, -18; the pregame total sits 2 under it
assert '| CFB | 2 | 1 | 0 | 14.5 | 13.8 | +0.8 on 2 (+0.1 SE), over 50% | +2.8 on 2 (+0.2 SE), over 50% |' in text, text   # -13 and +14.5
assert '- CFB: finals vs the model -7.0 on 1 game' in text and '- CFB: finals vs the fair line +13.5 on 1 game' in text, text   # the sheet row scores against mu_model, the CSV row against fair
assert '| NBA | half | 3 | 2 | $+37 |' in text and '| NBA | end of 3rd | 2 | 1 | $+16 |' in text, text
assert '| Oct 24 | 1 | 1 | $88 | $+18 |' in text, text                                    # the shot: under 63.5 won on a 48
assert '| CFB | 1 | 1 | $+40 |' in text, text                                             # one line came and went
assert '| NBA | shadow | 1 | 2 | 6 | 4 | 2 | 1 of 3 | 0 | 2 | $-1 | $+37 | $-38 | $+2 | $-3 |' in text, text
for word in ('KXNBA', 'c0ffee', '210.5'):
    assert word not in text, word
assert chr(8212) not in text and chr(8212) not in open(os.path.join(ROOT, 'scripts', 'readout.py'), encoding='utf-8').read()
print('readout: scorecard dedupes to the table, counts both windows, flags the misreads, grades shots and flickers from the sheet')

# 3. the go-live sections (Nov 12): the tiers, the spot cells at Kalshi's line, the rules, the fills as a return
assert ro.GO_LIVE == '2026-11-12' and ro.RULES['plays_n'] == 50 and ro.RULES['lane_n'] == 30 and ro.RULES['cell_n'] == 150 and ro.RULES['rest_n'] == 300
SPOTS = {'nfl': {'home_fav_trailing': {'lean': 1.5, 'mode': 'live', 'stake': 0.25}}, 'cfb': {'fav_leading_1_7': {'lean': 1.1, 'mode': 'shadow'}},
         'cbb': {'mismatch_hanging': {'lean': -1.0, 'mode': 'shadow'}}}
def half(sport, game, date, away, home, total, spread, mkt, final, cost=0.0, pnl=0.0, lane=None, fair=None, src='db', plays=None):
    sh = dict(h1a=away, h1h=home, mu_model=20.0, lead='single' if cost else 'rest',
              singles=[dict(dict(kind='over', line=mkt, price_c=45, contracts=50, cost=cost), **({'lane': lane} if lane else {}))] if cost else [])
    r = dict(sport=sport, game=game, final_total=final, mkt=mkt, total=total, home_spread=spread, fair=mkt if fair is None else fair, half=f'{away}-{home}',
             model_err=1.0, mkt_err=1.0, plays_cost=cost, plays_pnl=pnl, plays=plays)
    if src == 'db':
        r.update(date_et=date, game_id=game.replace(' ', ''), sheet=sh)
    else:
        r.update(settled_utc=f'{date}T03:00:00+00:00', date=date)
    return r
db2 = [half('nfl', 'GB @ NE', '2026-11-08', 24, 14, 44.5, -3.0, 63.0, 72),                                          # the cell, before go-live, no play: over the line
       half('nfl', 'BUF @ LAR', '2026-11-15', 13, 7, 55.5, -3.5, 46.5, 51, cost=23.0, pnl=32.0, lane='home_fav_trailing'),   # the lane's play, won
       half('nfl', 'DAL @ PHI', '2026-11-15', 17, 10, 47.5, -4.5, 48.5, 40, cost=22.0, pnl=-22.0, lane='home_fav_trailing'), # the lane's play, lost
       half('nfl', 'NYG @ WSH', '2026-11-15', 10, 13, 44.5, -3.0, 45.5, 50, cost=40.0, pnl=45.0),                    # a play on price (the favorite leads: no cell)
       half('nfl', 'SEA @ SF', '2026-11-15', 3, 3, 46.5, -2.5, 48.5, 34, cost=60.0, pnl=-60.0, fair=30.5),            # a misread: in no tier
       half('cfb', 'PITT @ UVA', '2026-11-14', 10, 14, 50.5, -6.5, 49.0, 49),                                        # the college cell, a push on the line
       half('cfb', 'WVU @ ISU', '2026-11-14', 14, 10, 50.5, 3.0, 51.5, 60),                                           # the road favorite up 4: over, on the lane side
       half('cbb', 'WOF @ TENN', '2026-11-13', 30, 41, 150.5, -17.5, 152.5, 144),                                     # a 17.5 favorite up 11: under, on the lane side
       half('cbb', 'LEM @ CREI', '2026-11-13', 33, 30, 148.5, -20.5, 140.5, 151)]                                      # the favorite behind: over, against the lane
csv2 = [half('nfl', 'MIA @ NYJ', '2026-11-16', 21, 7, 39.5, -3.5, 49.0, 54, cost=20.0, pnl=24.0, src='csv',
             plays='spot home_fav_trailing +1.5 live; lane over 49.5@45 W +24; alt lane over 46.5@55 W +15')]          # a CSV-only row: the lane is read from the plays text
rows2 = ro.dedupe(db2, csv2)
w2 = ro.windows(rows2)
assert {w['game'] for w in w2 if w['lane'] == 'home_fav_trailing'} == {'BUF @ LAR', 'DAL @ PHI', 'MIA @ NYJ'} and all(w['lane'] in (None, 'home_fav_trailing') for w in w2), [(w['game'], w['lane']) for w in w2]
assert ro.lead_lane(dict(plays='over 45.5@50 W +20')) is None and ro.lead_lane(dict(plays='spot hot_first_half +1.0 shadow; under 76.5@54 L -19')) is None
tl = ro.tier_lines(w2)
assert '| plays on price | before Nov 12 | 0 | 0 | $0 | $+0 |  |' in tl and '| plays on price | Nov 12 on | 1 | 1 | $40 | $+45 | +112.5% |' in tl, tl
assert '| spot lane: home_fav_trailing | Nov 12 on | 3 | 2 | $65 | $+34 | +52.3% |' in tl, tl                  # the misread is in neither tier
cl = ro.cell_lines(rows2, SPOTS)
assert '| NFL | home favorite trailing | live | over | 4 | 3 of 4 (75%) | +2.5 |' in cl, cl                    # +9, +4.5, -8.5 and +5 past the line; the misread half and the half with the favorite ahead name no cell
assert '| CFB | favorite leading by 1-7 | shadow | over | 2 | 1 of 1 (100%) | +4.2 |' in cl, cl                # the push is a half, not a decision
assert '| CBB | 15+ point favorite not up by 15 | shadow | under | 2 | 1 of 2 (50%) | -1.0 |' in cl, cl        # under side: +8.5 and -10.5
orders2 = [order(1, 'BOSDET', 'half', 'yes', 210.5, 45, 100, 'rest_mid', 'p1', status='touched', phase='half', secs=30, pnl=10.0, date='2026-11-13'),
           order(2, 'BOSDET', 'half', 'no', 214.5, 50, 100, 'rest_mid', 'p1', status='touched', phase='q3', secs=1200, pnl=-25.0, date='2026-11-13'),
           order(3, 'OKCSA', 'half', 'yes', 220.5, 40, 50, 'rest_mid', 'p2', status='touched', phase='early3', secs=200, pnl=-4.0, date='2026-11-13'),
           order(4, 'NYKMIA', 'half', 'yes', 218.5, 40, 50, 'rest_mid', 'p3', status='touched', phase='half', secs=20, pnl=30.0, date='2026-11-10')]   # before go-live: in the table, not in the rule
srow = ro.shadow_rows(orders2, '2026-11-13')[0]
assert (srow['touched_break'], srow['touched_play'], srow['cost_break'], srow['cost_play'], srow['pnl_break'], srow['pnl_play']) == (2, 1, 65.0, 50.0, 6.0, -25.0), srow
# the table's rows carry the final each was graded on, so the summary regrades every fill with the fee it pays: the
# maker fee on a resting fill (which the pnl column left out on every row graded before Nov 12), the taker fee on a take
graded = [dict(order(1, 'G', 'half', 'yes', 210.5, 45, 100, 'rest_mid', 'p1', status='touched', phase='half', secs=30, pnl=55.0, date='2026-11-09'), final_total=214.0),
          dict(order(2, 'G', 'half', 'no', 214.5, 50, 100, 'rest_mid', 'p1', status='touched', phase='live', secs=900, pnl=50.0, date='2026-11-09'), final_total=214.0),
          dict(order(3, 'G', 'half', 'yes', 212.5, 55, 40, 'single', None, kind='take', status='touched', phase='half', secs=5, pnl=17.3, date='2026-11-09'), final_total=214.0)]
assert [ro.net_pnl(o) for o in graded] == [54.56, 49.56, 17.3], [ro.net_pnl(o) for o in graded]
g = ro.shadow_rows(graded, '2026-11-09')[0]
assert (g['pnl'], g['pnl_break'], g['pnl_play'], g['pnl_both'], g['takes_pnl']) == (104.12, 54.56, 49.56, 104.12, 17.3), g
assert ro.net_pnl(dict(graded[0], pnl=None)) is None and ro.net_pnl(dict(graded[0], final_total=None)) == 55.0, 'ungraded stays ungraded; no final on the row, the column stands'
fl = ro.fill_lines(orders2)
assert '| NBA | 3 | $85 | $+36 | +42.4% | 1 | $50 | $-25 | -50.0% |' in fl and fl[-1].startswith('| ALL | 3 | $85 |'), fl
rl = ro.rule_lines(w2, rows2, orders2, SPOTS)
assert rl[0] == '- Plays on price: 1 of 50 graded since Nov 12, 1 won, $+45 on $40. Half stake stays (49 more to the review).', rl[0]
assert rl[1] == '- Spot lane home_fav_trailing: 3 of 30 graded plays since Nov 12, 2 won, $+34 on $65. The lane stays at its stake (27 more to the review).', rl[1]
assert "- Shadow cell CBB 15+ point favorite not up by 15 (under): 1 of 2 on its side of Kalshi's line (50%). Stays in shadow (148 more to the first review)." in rl, rl
assert "- Shadow cell CFB favorite leading by 1-7 (over): 1 of 1 on its side of Kalshi's line (100%). Stays in shadow (149 more to the first review)." in rl, rl
assert rl[-1] == '- Resting orders, filled at the break (shadow fill model): 2 of 300 since Nov 12, $+6 on $65 (+9.2%). The resting block stays on the push (298 more to the review).', rl[-1]
# the reviews fire at their marks
many = [dict(sport='nfl', game=f'g{i}', date='2026-11-20', stage='half', cost=10.0, pnl=(12.0 if i % 5 else -10.0), rest=None, mid=None, src='db', gap=1.0, shadow=False, lane=None) for i in range(50)]
assert 'REVIEW: in profit at the mark, full stake is earned' in ro.rule_lines(many, [], [], {})[0]
lost = [dict(w, pnl=(9.0 if i % 3 == 0 else -10.0)) for i, w in enumerate(many)]
assert 'REVIEW: down more than a tenth of the money risked, plays on price become reads (config stake_scale 0)' in ro.rule_lines(lost, [], [], {})[0]
lane30 = [dict(w, lane='home_fav_trailing', pnl=(12.0 if i % 3 else -10.0)) for i, w in enumerate(many[:30])]
assert 'REVIEW: the lane has earned double its stake' in ro.rule_lines(lane30, [], [], SPOTS)[1]
cold = [dict(w, lane='home_fav_trailing', pnl=(12.0 if i % 3 == 0 else -10.0)) for i, w in enumerate(many[:30])]
assert 'REVIEW: under 48 percent, the lane goes back to shadow' in ro.rule_lines(cold, [], [], SPOTS)[1]
text2 = ro.scorecard_md(db2, csv2, orders2, now=dt.datetime(2026, 11, 17, 12, tzinfo=dt.timezone.utc), spots=SPOTS)
for head in ('## The tiers (live Nov 12)', '## Spot cells at the Kalshi line', '## The go-live rules, and where each stands', 'The same fills as a return on the money behind them'):
    assert head in text2, head
assert text2.index('## Lead play per game window') < text2.index('## The tiers') < text2.index('## Spot cells') < text2.index('## The go-live rules') < text2.index('## Model against the market')
assert chr(8212) not in text2
print('readout: the tiers, the cells at the Kalshi line, the rules and the fills as a return, each at its mark')
