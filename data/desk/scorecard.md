# Halftime Desk scorecard

Written by the nightly export on 2026-11-21 (UTC) from the Supabase results table (1330 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 1550 windows on 1330 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 17 to Nov 20 | CBB | 2 | 1 | $14 | $-1 |
| all | all | 34 | 14 | $1,598 | $+228 |
| all, without the misreads | all | 28 | 11 | $932 | $-141 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 220 windows graded, 3 with a play, $-13 on $354.

## The tiers (live Nov 12)

What each live play was made on: the price (the desk number against the ask) or a spot lane. Misreads and shadow plays are left out. Plays on price run at half stake and the live lane at a quarter of full size until the rules below say otherwise.

| tier | when | plays | won | risked | P&L | return |
|---|---|---|---|---|---|---|
| plays on price | before Nov 12 | 20 | 6 | $881 | $-150 | -17.0% |
| plays on price | Nov 12 on | 5 | 3 | $41 | $+6 | +14.8% |
| spot lane: home_fav_trailing | before Nov 12 | 0 | 0 | $0 | $+0 |  |
| spot lane: home_fav_trailing | Nov 12 on | 3 | 2 | $11 | $+2 | +19.4% |

## Spot cells at the Kalshi line

Every graded half that sat in a configured cell, live or shadow, counted on the side the cell leans: the final against the Kalshi 50-50 line at the break. A cell earns a lane here, at the market number, not against the model.

| sport | cell | mode | lane side | halves | on the lane side of the line | finals past the line, lane side |
|---|---|---|---|---|---|---|
| CBB | 15+ point favorite not up by 15 | shadow | under | 144 | 75 of 142 (53%) | +1.4 |
| CFB | favorite leading by 1-7 | shadow | over | 81 | 37 of 79 (47%) | +0.6 |
| CFB | first half 10+ over the pace | shadow | over | 46 | 22 of 45 (49%) | +0.6 |
| NFL | home favorite trailing | live | over | 11 | 7 of 11 (64%) | +2.3 |

## The go-live rules, and where each stands

Set on Nov 12, before the plays they judge (the Playbook has them in full).

- Plays on price: 5 of 50 graded since Nov 12, 3 won, $+6 on $41. Half stake stays (45 more to the review).
- Spot lane home_fav_trailing: 3 of 30 graded plays since Nov 12, 2 won, $+2 on $11. The lane stays at its stake (27 more to the review).
- Shadow cell CBB 15+ point favorite not up by 15 (under): 75 of 142 on its side of Kalshi's line (53%). Stays in shadow (8 more to the first review).
- Shadow cell CFB favorite leading by 1-7 (over): 37 of 79 on its side of Kalshi's line (47%). Stays in shadow (71 more to the first review).
- Shadow cell CFB first half 10+ over the pace (over): 22 of 45 on its side of Kalshi's line (49%). Stays in shadow (105 more to the first review).
- Resting orders, filled at the break (shadow fill model): 153 of 300 since Nov 12, $-230 on $1,783 (-12.9%). The resting block stays on the push (147 more to the review).

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 712 | 274 | 155 | 9.2 | 9.2 | +1.0 on 712 (+2.1 SE), over 52% (past 2 SE, watch) | +0.3 on 712 (+0.5 SE), over 49% |
| CFB | 302 | 114 | 68 | 8.8 | 8.7 | +0.4 on 302 (+0.7 SE), over 45% | +0.3 on 302 (+0.3 SE), over 46% |
| NBA | 233 | 98 | 47 | 11.0 | 10.9 | +0.1 on 233 (+0.1 SE), over 44% | -0.7 on 233 (-0.6 SE), over 48% |
| NFL | 71 | 25 | 11 | 7.4 | 7.4 | +1.0 on 71 (+0.9 SE), over 54% | +0.1 on 71 (+0.1 SE), over 55% |

## Drift (this season against the model)

- CBB: finals vs the model -0.0 on 714 games (-0.1 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +0.1 on 246 games (+0.1 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model +0.1 on 230 games (+0.1 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model +0.5 on 58 games (+0.4 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 703 | 128 | $+1,772 |
| CBB SHADOW | half | 7 | 3 | $+69 |
| CFB | half | 243 | 29 | $+1,017 |
| NBA | half | 229 | 28 | $+1,233 |
| NBA | end of 3rd | 215 | 34 | $+568 |
| NFL | half | 57 | 10 | $+284 |

## Mismatch lane (college 28+), shadow shots

| slate | shots | won | risked | P&L |
|---|---|---|---|---|
| Nov 14 | 1 | 1 | $21 | $+4 |
| all | 1 | 1 | $21 | $+4 |

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CBB | shadow | 15 | 411 | 814 | 592 | 185 | 184 of 411 | 6 | 224 | $-453 | $-134 | $-319 | $+576 | $-1,029 |
| CFB | shadow | 8 | 57 | 116 | 88 | 48 | 31 of 58 | 5 | 26 | $-245 | $-104 | $-141 | $-32 | $-213 |
| NBA | shadow | 26 | 173 | 1056 | 788 | 233 | 201 of 646 | 5 | 386 | $-550 | $+492 | $-1,042 | $+800 | $-1,350 |
| NFL | shadow | 5 | 24 | 48 | 35 | 27 | 11 of 24 | 3 | 13 | $-13 | $-49 | $+35 | $+49 | $-62 |

The same fills as a return on the money behind them (the dollars above ride on the size the shadow ran that week):

| sport | filled at the break | risked | P&L | return | filled in play | risked | P&L | return |
|---|---|---|---|---|---|---|---|---|
| CBB | 185 | $2,236 | $-134 | -6.0% | 407 | $4,880 | $-319 | -6.5% |
| CFB | 48 | $719 | $-104 | -14.5% | 40 | $571 | $-141 | -24.7% |
| NBA | 233 | $3,659 | $+492 | +13.4% | 555 | $8,779 | $-1,042 | -11.9% |
| NFL | 27 | $363 | $-49 | -13.3% | 8 | $103 | $+35 | +34.3% |
| ALL | 493 | $6,978 | $+205 | +2.9% | 1010 | $14,333 | $-1,467 | -10.2% |
