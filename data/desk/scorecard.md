# Halftime Desk scorecard

Written by the nightly export on 2026-11-05 (UTC) from the Supabase results table (364 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 471 windows on 364 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 3 to Nov 4 | CBB SHADOW | 1 | 1 | $19 | $+9 |
| all | all | 23 | 9 | $1,496 | $+270 |
| all, without the misreads | all | 17 | 6 | $831 | $-100 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 107 windows graded, 3 with a play, $-13 on $354.

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 30 | 10 | 7 | 7.8 | 8.0 | -1.4 on 30 (-0.8 SE), over 47% | -1.6 on 30 (-0.5 SE), over 47% |
| CFB | 172 | 66 | 36 | 8.5 | 8.5 | +1.2 on 172 (+1.4 SE), over 48% | +0.6 on 172 (+0.5 SE), over 48% |
| NBA | 121 | 55 | 25 | 11.9 | 11.7 | -1.4 on 121 (-1.1 SE), over 39% | -3.0 on 121 (-1.8 SE), over 45% |
| NFL | 41 | 15 | 5 | 7.8 | 7.9 | +0.2 on 41 (+0.1 SE), over 49% | -0.1 on 41 (-0.1 SE), over 56% |

## Drift (this season against the model)

- CBB: finals vs the model -2.7 on 30 games (-1.5 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +1.1 on 114 games (+1.1 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -0.9 on 118 games (-0.6 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -0.8 on 28 games (-0.4 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 29 | 8 | $+140 |
| CBB SHADOW | half | 1 | 1 | $+23 |
| CFB | half | 112 | 18 | $+893 |
| NBA | half | 117 | 11 | $+886 |
| NBA | end of 3rd | 103 | 15 | $+316 |
| NFL | half | 28 | 5 | $+201 |

## Mismatch lane (college 28+), shadow shots

- no graded shots yet (the first Saturday of SHOT lines is Oct 31)

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NBA | shadow | 12 | 98 | 618 | 455 | 156 | 115 of 378 | 4 | 225 | $-458 | $+495 | $-953 | $+616 | $-1,073 |
