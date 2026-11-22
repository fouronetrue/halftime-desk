# Halftime Desk scorecard

Written by the nightly export on 2026-11-22 (UTC) from the Supabase results table (1441 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 1667 windows on 1441 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

## Lead play per game window

The play the push led with: the first single, or the middle when it led. The end-of-third window (NBA) is its own window.

| week | sport | plays | won | risked | P&L |
|---|---|---|---|---|---|
| Oct 16 to Oct 19 | CFB | 9 | 4 | $593 | $+78 |
| Oct 16 to Oct 19 | NFL | 2 | 2 | $139 | $+467 |
| Oct 20 to Oct 26 | CFB | 3 | 1 | $209 | $-98 |
| Oct 20 to Oct 26 | NBA | 4 | 1 | $486 | $-145 |
| Oct 27 to Nov 2 | CFB | 4 | 1 | $60 | $-23 |
| Oct 27 to Nov 2 | NFL | 1 | 0 | $10 | $-10 |
| Nov 3 to Nov 9 | CBB SHADOW | 5 | 4 | $90 | $+71 |
| Nov 3 to Nov 9 | CFB | 3 | 0 | $50 | $-50 |
| Nov 10 to Nov 16 | CBB | 1 | 1 | $10 | $+6 |
| Nov 10 to Nov 16 | CBB SHADOW | 4 | 4 | $106 | $+41 |
| Nov 10 to Nov 16 | CFB | 2 | 1 | $16 | $+2 |
| Nov 10 to Nov 16 | NFL | 3 | 2 | $11 | $+2 |
| Nov 17 to Nov 21 | CBB | 2 | 1 | $14 | $-1 |
| Nov 17 to Nov 21 | CFB | 2 | 2 | $16 | $+14 |
| all | all | 36 | 16 | $1,614 | $+242 |
| all, without the misreads | all | 30 | 13 | $949 | $-128 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 226 windows graded, 3 with a play, $-13 on $354.

## The tiers (live Nov 12)

What each live play was made on: the price (the desk number against the ask) or a spot lane. Misreads and shadow plays are left out. Plays on price run at half stake and the live lane at a quarter of full size until the rules below say otherwise.

| tier | when | plays | won | risked | P&L | return |
|---|---|---|---|---|---|---|
| plays on price | before Nov 12 | 20 | 6 | $881 | $-150 | -17.0% |
| plays on price | Nov 12 on | 7 | 5 | $57 | $+20 | +35.0% |
| spot lane: home_fav_trailing | before Nov 12 | 0 | 0 | $0 | $+0 |  |
| spot lane: home_fav_trailing | Nov 12 on | 3 | 2 | $11 | $+2 | +19.4% |

## Spot cells at the Kalshi line

Every graded half that sat in a configured cell, live or shadow, counted on the side the cell leans: the final against the Kalshi 50-50 line at the break. A cell earns a lane here, at the market number, not against the model.

| sport | cell | mode | lane side | halves | on the lane side of the line | finals past the line, lane side |
|---|---|---|---|---|---|---|
| CBB | 15+ point favorite not up by 15 | shadow | under | 148 | 78 of 146 (53%) | +1.3 |
| CFB | favorite leading by 1-7 | shadow | over | 96 | 44 of 92 (48%) | +0.7 |
| CFB | first half 10+ over the pace | shadow | over | 54 | 25 of 53 (47%) | +0.5 |
| NFL | home favorite trailing | live | over | 11 | 7 of 11 (64%) | +2.3 |

## The go-live rules, and where each stands

Set on Nov 12, before the plays they judge (the Playbook has them in full).

- Plays on price: 7 of 50 graded since Nov 12, 5 won, $+20 on $57. Half stake stays (43 more to the review).
- Spot lane home_fav_trailing: 3 of 30 graded plays since Nov 12, 2 won, $+2 on $11. The lane stays at its stake (27 more to the review).
- Shadow cell CBB 15+ point favorite not up by 15 (under): 78 of 146 on its side of Kalshi's line (53%). Stays in shadow (4 more to the first review).
- Shadow cell CFB favorite leading by 1-7 (over): 44 of 92 on its side of Kalshi's line (48%). Stays in shadow (58 more to the first review).
- Shadow cell CFB first half 10+ over the pace (over): 25 of 53 on its side of Kalshi's line (47%). Stays in shadow (97 more to the first review).
- Resting orders, filled at the break (shadow fill model): 182 of 300 since Nov 12, $-324 on $2,180 (-14.9%). The resting block stays on the push (118 more to the review).

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 758 | 292 | 166 | 9.2 | 9.2 | +0.9 on 758 (+2.1 SE), over 52% (past 2 SE, watch) | +0.3 on 758 (+0.6 SE), over 50% |
| CFB | 359 | 134 | 79 | 8.5 | 8.4 | +0.6 on 359 (+1.1 SE), over 46% | +0.3 on 359 (+0.3 SE), over 47% |
| NBA | 239 | 100 | 49 | 11.1 | 10.9 | -0.1 on 239 (-0.1 SE), over 44% | -1.1 on 239 (-0.9 SE), over 47% |
| NFL | 71 | 25 | 11 | 7.4 | 7.4 | +1.0 on 71 (+0.9 SE), over 54% | +0.1 on 71 (+0.1 SE), over 55% |

## Drift (this season against the model)

- CBB: finals vs the model -0.1 on 760 games (-0.3 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +0.2 on 303 games (+0.4 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -0.0 on 236 games (-0.0 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model +0.5 on 58 games (+0.4 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 749 | 131 | $+1,735 |
| CBB SHADOW | half | 7 | 3 | $+69 |
| CFB | half | 300 | 42 | $+1,326 |
| NBA | half | 235 | 29 | $+1,255 |
| NBA | end of 3rd | 221 | 36 | $+610 |
| NFL | half | 57 | 10 | $+284 |

## Mismatch lane (college 28+), shadow shots

| slate | shots | won | risked | P&L |
|---|---|---|---|---|
| Nov 14 | 1 | 1 | $21 | $+4 |
| Nov 21 | 1 | 1 | $21 | $+4 |
| all | 2 | 2 | $43 | $+7 |

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CBB | shadow | 16 | 433 | 857 | 626 | 194 | 196 of 433 | 6 | 234 | $-509 | $-199 | $-310 | $+554 | $-1,063 |
| CFB | shadow | 9 | 78 | 158 | 121 | 67 | 43 of 79 | 8 | 35 | $-262 | $-139 | $-123 | $+29 | $-291 |
| NBA | shadow | 27 | 174 | 1062 | 790 | 234 | 201 of 650 | 5 | 388 | $-557 | $+497 | $-1,054 | $+800 | $-1,356 |
| NFL | shadow | 5 | 24 | 48 | 35 | 27 | 11 of 24 | 3 | 13 | $-13 | $-49 | $+35 | $+49 | $-62 |

The same fills as a return on the money behind them (the dollars above ride on the size the shadow ran that week):

| sport | filled at the break | risked | P&L | return | filled in play | risked | P&L | return |
|---|---|---|---|---|---|---|---|---|
| CBB | 194 | $2,334 | $-199 | -8.5% | 432 | $5,156 | $-310 | -6.0% |
| CFB | 67 | $1,012 | $-139 | -13.8% | 54 | $781 | $-123 | -15.7% |
| NBA | 234 | $3,665 | $+497 | +13.6% | 556 | $8,791 | $-1,054 | -12.0% |
| NFL | 27 | $363 | $-49 | -13.3% | 8 | $103 | $+35 | +34.3% |
| ALL | 522 | $7,374 | $+111 | +1.5% | 1050 | $14,831 | $-1,452 | -9.8% |
