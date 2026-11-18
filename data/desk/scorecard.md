# Halftime Desk scorecard

Written by the nightly export on 2026-11-18 (UTC) from the Supabase results table (1158 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 1353 windows on 1158 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| all | all | 32 | 13 | $1,584 | $+229 |
| all, without the misreads | all | 26 | 10 | $919 | $-141 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 195 windows graded, 3 with a play, $-13 on $354.

## The tiers (live Nov 12)

What each live play was made on: the price (the desk number against the ask) or a spot lane. Misreads and shadow plays are left out. Plays on price run at half stake and the live lane at a quarter of full size until the rules below say otherwise.

| tier | when | plays | won | risked | P&L | return |
|---|---|---|---|---|---|---|
| plays on price | before Nov 12 | 20 | 6 | $881 | $-150 | -17.0% |
| plays on price | Nov 12 on | 3 | 2 | $27 | $+7 | +26.1% |
| spot lane: home_fav_trailing | before Nov 12 | 0 | 0 | $0 | $+0 |  |
| spot lane: home_fav_trailing | Nov 12 on | 3 | 2 | $11 | $+2 | +19.4% |

## Spot cells at the Kalshi line

Every graded half that sat in a configured cell, live or shadow, counted on the side the cell leans: the final against the Kalshi 50-50 line at the break. A cell earns a lane here, at the market number, not against the model.

| sport | cell | mode | lane side | halves | on the lane side of the line | finals past the line, lane side |
|---|---|---|---|---|---|---|
| CBB | 15+ point favorite not up by 15 | shadow | under | 121 | 60 of 119 (50%) | +0.8 |
| CFB | favorite leading by 1-7 | shadow | over | 79 | 35 of 77 (45%) | +0.4 |
| CFB | first half 10+ over the pace | shadow | over | 45 | 22 of 44 (50%) | +0.6 |
| NFL | home favorite trailing | live | over | 11 | 7 of 11 (64%) | +2.3 |

## The go-live rules, and where each stands

Set on Nov 12, before the plays they judge (the Playbook has them in full).

- Plays on price: 3 of 50 graded since Nov 12, 2 won, $+7 on $27. Half stake stays (47 more to the review).
- Spot lane home_fav_trailing: 3 of 30 graded plays since Nov 12, 2 won, $+2 on $11. The lane stays at its stake (27 more to the review).
- Shadow cell CBB 15+ point favorite not up by 15 (under): 60 of 119 on its side of Kalshi's line (50%). Stays in shadow (31 more to the first review).
- Shadow cell CFB favorite leading by 1-7 (over): 35 of 77 on its side of Kalshi's line (45%). Stays in shadow (73 more to the first review).
- Shadow cell CFB first half 10+ over the pace (over): 22 of 44 on its side of Kalshi's line (50%). Stays in shadow (106 more to the first review).
- Resting orders, filled at the break (shadow fill model): 109 of 300 since Nov 12, $-232 on $1,239 (-18.7%). The resting block stays on the push (191 more to the review).

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 576 | 231 | 125 | 9.0 | 9.1 | +0.6 on 576 (+1.3 SE), over 52% | -0.6 on 576 (-0.9 SE), over 47% |
| CFB | 293 | 111 | 64 | 8.8 | 8.7 | +0.4 on 293 (+0.6 SE), over 44% | +0.2 on 293 (+0.2 SE), over 45% |
| NBA | 208 | 84 | 45 | 11.1 | 10.9 | +0.5 on 208 (+0.5 SE), over 45% | -0.7 on 208 (-0.5 SE), over 47% |
| NFL | 70 | 25 | 10 | 7.4 | 7.4 | +1.2 on 70 (+1.0 SE), over 54% | +0.4 on 70 (+0.2 SE), over 56% |

## Drift (this season against the model)

- CBB: finals vs the model -0.4 on 578 games (-0.8 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model -0.0 on 237 games (-0.0 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model +0.6 on 205 games (+0.6 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model +0.7 on 57 games (+0.6 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 567 | 107 | $+1,544 |
| CBB SHADOW | half | 7 | 3 | $+69 |
| CFB | half | 234 | 27 | $+981 |
| NBA | half | 204 | 25 | $+1,178 |
| NBA | end of 3rd | 191 | 31 | $+542 |
| NFL | half | 56 | 10 | $+286 |

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
| CBB | shadow | 12 | 334 | 661 | 490 | 154 | 157 of 334 | 5 | 176 | $-240 | $-127 | $-113 | $+561 | $-802 |
| CFB | shadow | 6 | 55 | 112 | 86 | 46 | 31 of 56 | 5 | 24 | $-246 | $-105 | $-141 | $-32 | $-214 |
| NBA | shadow | 24 | 161 | 993 | 738 | 223 | 187 of 606 | 5 | 364 | $-523 | $+467 | $-990 | $+794 | $-1,317 |
| NFL | shadow | 4 | 23 | 46 | 33 | 26 | 10 of 23 | 3 | 13 | $-11 | $-32 | $+21 | $+51 | $-62 |

The same fills as a return on the money behind them (the dollars above ride on the size the shadow ran that week):

| sport | filled at the break | risked | P&L | return | filled in play | risked | P&L | return |
|---|---|---|---|---|---|---|---|---|
| CBB | 154 | $1,812 | $-127 | -7.0% | 336 | $4,065 | $-113 | -2.8% |
| CFB | 46 | $689 | $-105 | -15.3% | 40 | $571 | $-141 | -24.7% |
| NBA | 223 | $3,586 | $+467 | +13.0% | 515 | $8,514 | $-990 | -11.6% |
| NFL | 26 | $347 | $-32 | -9.2% | 7 | $88 | $+21 | +23.6% |
| ALL | 449 | $6,434 | $+202 | +3.1% | 898 | $13,237 | $-1,223 | -9.2% |
