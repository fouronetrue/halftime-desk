# Halftime Desk scorecard

Written by the nightly export on 2026-11-12 (UTC) from the Supabase results table (802 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 957 windows on 802 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 10 to Nov 11 | CBB SHADOW | 4 | 4 | $106 | $+41 |
| all | all | 26 | 9 | $1,546 | $+220 |
| all, without the misreads | all | 20 | 6 | $881 | $-150 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 155 windows graded, 3 with a play, $-13 on $354.

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 340 | 142 | 72 | 9.3 | 9.3 | +1.4 on 340 (+2.1 SE), over 54% (past 2 SE, watch) | +0.1 on 340 (+0.1 SE), over 49% |
| CFB | 231 | 88 | 47 | 8.9 | 8.7 | +1.3 on 231 (+1.8 SE), over 47% | +1.1 on 231 (+1.0 SE), over 48% |
| NBA | 169 | 70 | 37 | 11.0 | 10.8 | -0.9 on 169 (-0.9 SE), over 40% | -2.0 on 169 (-1.5 SE), over 45% |
| NFL | 56 | 20 | 9 | 7.6 | 7.7 | +0.2 on 56 (+0.1 SE), over 48% | -0.4 on 56 (-0.2 SE), over 54% |

## Drift (this season against the model)

- CBB: finals vs the model +0.3 on 340 games (+0.5 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +1.2 on 175 games (+1.4 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -0.8 on 166 games (-0.7 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -0.5 on 43 games (-0.4 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 331 | 61 | $+852 |
| CBB SHADOW | half | 7 | 3 | $+69 |
| CFB | half | 172 | 22 | $+923 |
| NBA | half | 165 | 21 | $+1,114 |
| NBA | end of 3rd | 151 | 23 | $+410 |
| NFL | half | 43 | 7 | $+229 |

## Mismatch lane (college 28+), shadow shots

- no graded shots yet (the first Saturday of SHOT lines is Oct 31)

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CBB | shadow | 5 | 161 | 316 | 246 | 100 | 85 of 161 | 4 | 76 | $+16 | $+20 | $-4 | $+307 | $-291 |
| CFB | shadow | 3 | 22 | 46 | 37 | 22 | 15 of 23 | 1 | 7 | $-121 | $-11 | $-110 | $-19 | $-102 |
| NBA | shadow | 19 | 138 | 861 | 640 | 202 | 167 of 524 | 5 | 306 | $-326 | $+481 | $-808 | $+795 | $-1,122 |
| NFL | shadow | 2 | 14 | 28 | 22 | 16 | 8 of 14 | 2 | 6 | $-0 | $-12 | $+11 | $+36 | $-36 |
