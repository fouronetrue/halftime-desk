# Halftime Desk scorecard

Written by the nightly export on 2026-11-11 (UTC) from the Supabase results table (742 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 887 windows on 742 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 10 to Nov 10 | CBB SHADOW | 3 | 3 | $87 | $+27 |
| all | all | 26 | 9 | $1,546 | $+220 |
| all, without the misreads | all | 20 | 6 | $881 | $-150 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 145 windows graded, 3 with a play, $-13 on $354.

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 293 | 120 | 62 | 9.3 | 9.3 | +1.6 on 293 (+2.4 SE), over 55% (past 2 SE, watch) | +0.3 on 293 (+0.3 SE), over 50% |
| CFB | 228 | 87 | 47 | 8.8 | 8.7 | +1.4 on 228 (+2.0 SE), over 47% | +1.3 on 228 (+1.3 SE), over 49% |
| NBA | 160 | 68 | 35 | 11.2 | 11.0 | -0.9 on 160 (-0.9 SE), over 39% | -2.3 on 160 (-1.6 SE), over 43% |
| NFL | 56 | 20 | 9 | 7.6 | 7.7 | +0.2 on 56 (+0.1 SE), over 48% | -0.4 on 56 (-0.2 SE), over 54% |

## Drift (this season against the model)

- CBB: finals vs the model +0.5 on 293 games (+0.8 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +1.4 on 172 games (+1.7 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -0.7 on 157 games (-0.6 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -0.5 on 43 games (-0.4 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 285 | 52 | $+704 |
| CBB SHADOW | half | 6 | 3 | $+71 |
| CFB | half | 169 | 22 | $+927 |
| NBA | half | 156 | 18 | $+1,034 |
| NBA | end of 3rd | 141 | 23 | $+434 |
| NFL | half | 43 | 7 | $+229 |

## Mismatch lane (college 28+), shadow shots

- no graded shots yet (the first Saturday of SHOT lines is Oct 31)

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CBB | shadow | 4 | 124 | 243 | 187 | 78 | 63 of 124 | 3 | 61 | $+7 | $-22 | $+30 | $+225 | $-218 |
| CFB | shadow | 2 | 19 | 40 | 33 | 19 | 14 of 20 | 1 | 5 | $-90 | $+3 | $-94 | $-18 | $-73 |
| NBA | shadow | 18 | 130 | 818 | 611 | 192 | 162 of 498 | 5 | 287 | $-345 | $+498 | $-843 | $+750 | $-1,095 |
| NFL | shadow | 2 | 14 | 28 | 22 | 16 | 8 of 14 | 2 | 6 | $-0 | $-12 | $+11 | $+36 | $-36 |
