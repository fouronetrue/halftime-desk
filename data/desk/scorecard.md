# Halftime Desk scorecard

Written by the nightly export on 2026-11-15 (UTC) from the Supabase results table (1014 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 1187 windows on 1014 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 10 to Nov 14 | CBB | 1 | 1 | $10 | $+6 |
| Nov 10 to Nov 14 | CBB SHADOW | 4 | 4 | $106 | $+41 |
| Nov 10 to Nov 14 | CFB | 2 | 1 | $16 | $+2 |
| Nov 10 to Nov 14 | NFL | 1 | 1 | $3 | $+3 |
| all | all | 30 | 12 | $1,575 | $+231 |
| all, without the misreads | all | 24 | 9 | $910 | $-139 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 173 windows graded, 3 with a play, $-13 on $354.

## The tiers (live Nov 12)

What each live play was made on: the price (the desk number against the ask) or a spot lane. Misreads and shadow plays are left out. Plays on price run at half stake and the live lane at a quarter of full size until the rules below say otherwise.

| tier | when | plays | won | risked | P&L | return |
|---|---|---|---|---|---|---|
| plays on price | before Nov 12 | 20 | 6 | $881 | $-150 | -17.0% |
| plays on price | Nov 12 on | 3 | 2 | $27 | $+7 | +26.1% |
| spot lane: home_fav_trailing | before Nov 12 | 0 | 0 | $0 | $+0 |  |
| spot lane: home_fav_trailing | Nov 12 on | 1 | 1 | $3 | $+3 | +113.5% |

## Spot cells at the Kalshi line

Every graded half that sat in a configured cell, live or shadow, counted on the side the cell leans: the final against the Kalshi 50-50 line at the break. A cell earns a lane here, at the market number, not against the model.

| sport | cell | mode | lane side | halves | on the lane side of the line | finals past the line, lane side |
|---|---|---|---|---|---|---|
| CBB | 15+ point favorite not up by 15 | shadow | under | 100 | 52 of 98 (53%) | +1.1 |
| CFB | favorite leading by 1-7 | shadow | over | 79 | 35 of 77 (45%) | +0.4 |
| CFB | first half 10+ over the pace | shadow | over | 44 | 21 of 43 (49%) | +0.5 |
| NFL | home favorite trailing | live | over | 8 | 5 of 8 (62%) | +2.7 |

## The go-live rules, and where each stands

Set on Nov 12, before the plays they judge (the Playbook has them in full).

- Plays on price: 3 of 50 graded since Nov 12, 2 won, $+7 on $27. Half stake stays (47 more to the review).
- Spot lane home_fav_trailing: 1 of 30 graded plays since Nov 12, 1 won, $+3 on $3. The lane stays at its stake (29 more to the review).
- Shadow cell CBB 15+ point favorite not up by 15 (under): 52 of 98 on its side of Kalshi's line (53%). Stays in shadow (52 more to the first review).
- Shadow cell CFB favorite leading by 1-7 (over): 35 of 77 on its side of Kalshi's line (45%). Stays in shadow (73 more to the first review).
- Shadow cell CFB first half 10+ over the pace (over): 21 of 43 on its side of Kalshi's line (49%). Stays in shadow (107 more to the first review).
- Resting orders, filled at the break (shadow fill model): 61 of 300 since Nov 12, $-181 on $742 (-24.3%). The resting block stays on the push (239 more to the review).

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 471 | 191 | 99 | 9.0 | 9.1 | +0.5 on 471 (+0.9 SE), over 50% | -0.9 on 471 (-1.3 SE), over 46% |
| CFB | 290 | 109 | 63 | 8.8 | 8.7 | +0.4 on 290 (+0.6 SE), over 44% | +0.1 on 290 (+0.1 SE), over 45% |
| NBA | 187 | 77 | 39 | 11.0 | 10.7 | -0.2 on 187 (-0.2 SE), over 43% | -1.2 on 187 (-0.9 SE), over 46% |
| NFL | 57 | 21 | 9 | 7.6 | 7.7 | +0.3 on 57 (+0.2 SE), over 49% | -0.3 on 57 (-0.2 SE), over 54% |

## Drift (this season against the model)

- CBB: finals vs the model -0.5 on 472 games (-1.0 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +0.0 on 234 games (+0.0 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -0.0 on 184 games (-0.0 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -0.4 on 44 games (-0.2 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 462 | 89 | $+1,301 |
| CBB SHADOW | half | 7 | 3 | $+69 |
| CFB | half | 231 | 27 | $+987 |
| NBA | half | 183 | 23 | $+1,149 |
| NBA | end of 3rd | 169 | 27 | $+484 |
| NFL | half | 44 | 7 | $+224 |

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
| CBB | shadow | 8 | 257 | 510 | 384 | 130 | 128 of 257 | 4 | 128 | $-94 | $-87 | $-7 | $+488 | $-582 |
| CFB | shadow | 5 | 53 | 108 | 82 | 45 | 29 of 54 | 5 | 24 | $-244 | $-121 | $-123 | $-30 | $-214 |
| NBA | shadow | 21 | 148 | 923 | 685 | 210 | 178 of 562 | 5 | 329 | $-401 | $+475 | $-876 | $+792 | $-1,193 |
| NFL | shadow | 2 | 14 | 28 | 22 | 16 | 8 of 14 | 2 | 6 | $-3 | $-14 | $+11 | $+34 | $-37 |

The same fills as a return on the money behind them (the dollars above ride on the size the shadow ran that week):

| sport | filled at the break | risked | P&L | return | filled in play | risked | P&L | return |
|---|---|---|---|---|---|---|---|---|
| CBB | 130 | $1,521 | $-87 | -5.7% | 254 | $3,054 | $-7 | -0.2% |
| CFB | 45 | $674 | $-121 | -17.9% | 37 | $523 | $-123 | -23.6% |
| NBA | 210 | $3,518 | $+475 | +13.5% | 475 | $8,265 | $-876 | -10.6% |
| NFL | 16 | $224 | $-14 | -6.1% | 6 | $77 | $+11 | +14.0% |
| ALL | 401 | $5,936 | $+254 | +4.3% | 772 | $11,919 | $-995 | -8.3% |
