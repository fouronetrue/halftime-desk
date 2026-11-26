# Halftime Desk scorecard

Written by the nightly export on 2026-11-26 (UTC) from the Supabase results table (1683 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 1938 windows on 1683 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 17 to Nov 23 | CBB | 3 | 1 | $19 | $-6 |
| Nov 17 to Nov 23 | CFB | 2 | 2 | $16 | $+14 |
| all | all | 37 | 16 | $1,619 | $+237 |
| all, without the misreads | all | 31 | 13 | $954 | $-133 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 255 windows graded, 3 with a play, $-13 on $354.

## The tiers (live Nov 12)

What each live play was made on: the price (the desk number against the ask) or a spot lane. Misreads and shadow plays are left out. Plays on price run at half stake and the live lane at a quarter of full size until the rules below say otherwise.

| tier | when | plays | won | risked | P&L | return |
|---|---|---|---|---|---|---|
| plays on price | before Nov 12 | 20 | 6 | $881 | $-150 | -17.0% |
| plays on price | Nov 12 on | 8 | 5 | $62 | $+15 | +23.3% |
| spot lane: home_fav_trailing | before Nov 12 | 0 | 0 | $0 | $+0 |  |
| spot lane: home_fav_trailing | Nov 12 on | 3 | 2 | $11 | $+2 | +19.4% |

## Spot cells at the Kalshi line

Every graded half that sat in a configured cell, live or shadow, counted on the side the cell leans: the final against the Kalshi 50-50 line at the break. A cell earns a lane here, at the market number, not against the model.

| sport | cell | mode | lane side | halves | on the lane side of the line | finals past the line, lane side |
|---|---|---|---|---|---|---|
| CBB | 15+ point favorite not up by 15 | shadow | under | 167 | 87 of 162 (54%) | +1.2 |
| CFB | favorite leading by 1-7 | shadow | over | 97 | 44 of 93 (47%) | +0.5 |
| CFB | first half 10+ over the pace | shadow | over | 54 | 25 of 53 (47%) | +0.5 |
| NFL | home favorite trailing | live | over | 13 | 8 of 13 (62%) | +1.7 |

## The go-live rules, and where each stands

Set on Nov 12, before the plays they judge (the Playbook has them in full).

- Plays on price: 8 of 50 graded since Nov 12, 5 won, $+15 on $62. Half stake stays (42 more to the review).
- Spot lane home_fav_trailing: 3 of 30 graded plays since Nov 12, 2 won, $+2 on $11. The lane stays at its stake (27 more to the review).
- Shadow cell CBB 15+ point favorite not up by 15 (under): 87 of 162 on its side of Kalshi's line (54%). Stays in shadow.
- Shadow cell CFB favorite leading by 1-7 (over): 44 of 93 on its side of Kalshi's line (47%). Stays in shadow (57 more to the first review).
- Shadow cell CFB first half 10+ over the pace (over): 25 of 53 on its side of Kalshi's line (47%). Stays in shadow (97 more to the first review).
- Resting orders, filled at the break (shadow fill model): 245 of 300 since Nov 12, $-364 on $2,877 (-12.7%). The resting block stays on the push (55 more to the review).

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 954 | 363 | 214 | 9.3 | 9.3 | +0.6 on 954 (+1.5 SE), over 51% | +0.3 on 954 (+0.6 SE), over 50% |
| CFB | 361 | 134 | 80 | 8.6 | 8.5 | +0.6 on 361 (+1.1 SE), over 46% | +0.2 on 361 (+0.3 SE), over 47% |
| NBA | 268 | 115 | 56 | 10.9 | 10.9 | +0.2 on 268 (+0.2 SE), over 45% | -0.9 on 268 (-0.8 SE), over 47% |
| NFL | 84 | 30 | 16 | 7.7 | 7.7 | +0.5 on 84 (+0.4 SE), over 50% | +0.6 on 84 (+0.4 SE), over 54% |

## Drift (this season against the model)

- CBB: finals vs the model -0.4 on 956 games (-0.9 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +0.2 on 305 games (+0.3 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model +0.2 on 265 games (+0.2 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -0.1 on 71 games (-0.1 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 945 | 168 | $+2,226 |
| CBB SHADOW | half | 7 | 3 | $+69 |
| CFB | half | 302 | 42 | $+1,321 |
| NBA | half | 264 | 33 | $+1,332 |
| NBA | end of 3rd | 250 | 38 | $+596 |
| NFL | half | 70 | 12 | $+317 |

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
| CBB | shadow | 20 | 571 | 1132 | 829 | 234 | 261 of 572 | 8 | 307 | $-657 | $-257 | $-400 | $+633 | $-1,290 |
| CFB | shadow | 10 | 80 | 162 | 123 | 69 | 43 of 81 | 8 | 37 | $-288 | $-165 | $-123 | $+29 | $-317 |
| NBA | shadow | 30 | 190 | 1148 | 854 | 242 | 217 of 704 | 5 | 420 | $-600 | $+513 | $-1,113 | $+808 | $-1,408 |
| NFL | shadow | 7 | 36 | 72 | 53 | 40 | 18 of 36 | 6 | 17 | $-30 | $-20 | $-10 | $+67 | $-97 |

The same fills as a return on the money behind them (the dollars above ride on the size the shadow ran that week):

| sport | filled at the break | risked | P&L | return | filled in play | risked | P&L | return |
|---|---|---|---|---|---|---|---|---|
| CBB | 234 | $2,777 | $-257 | -9.3% | 595 | $7,073 | $-400 | -5.7% |
| CFB | 69 | $1,038 | $-165 | -15.9% | 54 | $781 | $-123 | -15.7% |
| NBA | 242 | $3,707 | $+513 | +13.8% | 612 | $9,184 | $-1,113 | -12.1% |
| NFL | 40 | $549 | $-20 | -3.7% | 13 | $178 | $-10 | -5.8% |
| ALL | 585 | $8,071 | $+71 | +0.9% | 1274 | $17,216 | $-1,646 | -9.6% |
