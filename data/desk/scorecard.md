# Halftime Desk scorecard

Written by the nightly export on 2026-11-13 (UTC) from the Supabase results table (832 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 991 windows on 832 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 10 to Nov 12 | CBB SHADOW | 4 | 4 | $106 | $+41 |
| Nov 10 to Nov 12 | NFL | 1 | 1 | $3 | $+3 |
| all | all | 27 | 10 | $1,548 | $+224 |
| all, without the misreads | all | 21 | 7 | $883 | $-146 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 159 windows graded, 3 with a play, $-13 on $354.

## The tiers (live Nov 12)

What each live play was made on: the price (the desk number against the ask) or a spot lane. Misreads and shadow plays are left out. Plays on price run at half stake and the live lane at a quarter of full size until the rules below say otherwise.

| tier | when | plays | won | risked | P&L | return |
|---|---|---|---|---|---|---|
| plays on price | before Nov 12 | 20 | 6 | $881 | $-150 | -17.0% |
| plays on price | Nov 12 on | 0 | 0 | $0 | $+0 |  |
| spot lane: home_fav_trailing | before Nov 12 | 0 | 0 | $0 | $+0 |  |
| spot lane: home_fav_trailing | Nov 12 on | 1 | 1 | $3 | $+3 | +113.5% |

## Spot cells at the Kalshi line

Every graded half that sat in a configured cell, live or shadow, counted on the side the cell leans: the final against the Kalshi 50-50 line at the break. A cell earns a lane here, at the market number, not against the model.

| sport | cell | mode | lane side | halves | on the lane side of the line | finals past the line, lane side |
|---|---|---|---|---|---|---|
| CBB | 15+ point favorite not up by 15 | shadow | under | 79 | 42 of 79 (53%) | +1.1 |
| CFB | favorite leading by 1-7 | shadow | over | 64 | 29 of 62 (47%) | +1.1 |
| CFB | first half 10+ over the pace | shadow | over | 35 | 16 of 34 (47%) | +1.2 |
| NFL | home favorite trailing | live | over | 8 | 5 of 8 (62%) | +2.7 |

## The go-live rules, and where each stands

Set on Nov 12, before the plays they judge (the Playbook has them in full).

- Plays on price: 0 of 50 graded since Nov 12, 0 won, $+0 on $0. Half stake stays (50 more to the review).
- Spot lane home_fav_trailing: 1 of 30 graded plays since Nov 12, 1 won, $+3 on $3. The lane stays at its stake (29 more to the review).
- Shadow cell CBB 15+ point favorite not up by 15 (under): 42 of 79 on its side of Kalshi's line (53%). Stays in shadow (71 more to the first review).
- Shadow cell CFB favorite leading by 1-7 (over): 29 of 62 on its side of Kalshi's line (47%). Stays in shadow (88 more to the first review).
- Shadow cell CFB first half 10+ over the pace (over): 16 of 34 on its side of Kalshi's line (47%). Stays in shadow (116 more to the first review).
- Resting orders, filled at the break (shadow fill model): 10 of 300 since Nov 12, $+3 on $86 (+3.3%). The resting block stays on the push (290 more to the review).

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 364 | 152 | 74 | 9.3 | 9.4 | +1.1 on 364 (+1.8 SE), over 53% | -0.0 on 364 (-0.0 SE), over 49% |
| CFB | 232 | 88 | 47 | 8.9 | 8.8 | +1.4 on 232 (+1.9 SE), over 47% | +1.3 on 232 (+1.2 SE), over 49% |
| NBA | 173 | 72 | 38 | 11.2 | 11.0 | -0.7 on 173 (-0.7 SE), over 40% | -1.6 on 173 (-1.2 SE), over 46% |
| NFL | 57 | 21 | 9 | 7.6 | 7.7 | +0.3 on 57 (+0.2 SE), over 49% | -0.3 on 57 (-0.2 SE), over 54% |

## Drift (this season against the model)

- CBB: finals vs the model +0.1 on 364 games (+0.2 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +1.3 on 176 games (+1.5 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -0.6 on 170 games (-0.5 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -0.4 on 44 games (-0.2 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 355 | 61 | $+790 |
| CBB SHADOW | half | 7 | 3 | $+69 |
| CFB | half | 173 | 22 | $+922 |
| NBA | half | 169 | 22 | $+1,138 |
| NBA | end of 3rd | 155 | 24 | $+430 |
| NFL | half | 44 | 7 | $+224 |

## Mismatch lane (college 28+), shadow shots

- no graded shots yet (a shot needs a 28+ point college spread and a side at 80c or more that the narrowed ladder still calls cheap)

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CBB | shadow | 6 | 181 | 356 | 274 | 107 | 94 of 181 | 4 | 86 | $-92 | $-5 | $-87 | $+276 | $-368 |
| CFB | shadow | 3 | 22 | 46 | 37 | 22 | 15 of 23 | 1 | 7 | $-125 | $-14 | $-112 | $-23 | $-103 |
| NBA | shadow | 20 | 140 | 875 | 648 | 205 | 168 of 532 | 5 | 312 | $-430 | $+470 | $-900 | $+733 | $-1,163 |
| NFL | shadow | 2 | 14 | 28 | 22 | 16 | 8 of 14 | 2 | 6 | $-3 | $-14 | $+11 | $+34 | $-37 |

The same fills as a return on the money behind them (the dollars above ride on the size the shadow ran that week):

| sport | filled at the break | risked | P&L | return | filled in play | risked | P&L | return |
|---|---|---|---|---|---|---|---|---|
| CBB | 107 | $1,241 | $-5 | -0.4% | 167 | $1,977 | $-87 | -4.4% |
| CFB | 22 | $328 | $-14 | -4.1% | 15 | $209 | $-112 | -53.5% |
| NBA | 205 | $3,489 | $+470 | +13.5% | 443 | $8,027 | $-900 | -11.2% |
| NFL | 16 | $224 | $-14 | -6.1% | 6 | $77 | $+11 | +14.0% |
| ALL | 350 | $5,281 | $+438 | +8.3% | 631 | $10,289 | $-1,088 | -10.6% |
