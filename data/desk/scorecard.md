# Halftime Desk scorecard

Written by the nightly export on 2026-11-01 (UTC) from the Supabase results table (283 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 357 windows on 283 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

## Lead play per game window

The play the push led with: the first single, or the middle when it led. The end-of-third window (NBA) is its own window.

| week | sport | plays | won | risked | P&L |
|---|---|---|---|---|---|
| Oct 16 to Oct 19 | CFB | 9 | 4 | $593 | $+78 |
| Oct 16 to Oct 19 | NFL | 2 | 2 | $139 | $+467 |
| Oct 20 to Oct 26 | CFB | 3 | 1 | $209 | $-98 |
| Oct 20 to Oct 26 | NBA | 4 | 1 | $486 | $-145 |
| Oct 27 to Oct 31 | CFB | 4 | 1 | $60 | $-23 |
| all | all | 22 | 9 | $1,486 | $+280 |
| all, without the misreads | all | 16 | 6 | $821 | $-90 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 74 windows graded, 3 with a play, $-13 on $354.

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CFB | 167 | 65 | 34 | 8.5 | 8.4 | +1.0 on 167 (+1.2 SE), over 47% | +0.6 on 167 (+0.5 SE), over 48% |
| NBA | 88 | 41 | 11 | 12.0 | 11.6 | -1.5 on 88 (-1.0 SE), over 41% | -3.4 on 88 (-1.7 SE), over 45% |
| NFL | 28 | 12 | 5 | 7.3 | 7.6 | -0.8 on 28 (-0.5 SE), over 43% | -0.7 on 28 (-0.3 SE), over 57% |

## Drift (this season against the model)

- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +0.9 on 109 games (+0.8 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -0.6 on 85 games (-0.4 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -3.1 on 15 games (-1.6 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CFB | half | 107 | 17 | $+872 |
| NBA | half | 84 | 9 | $+870 |
| NBA | end of 3rd | 70 | 11 | $+286 |
| NFL | half | 15 | 3 | $+171 |

## Mismatch lane (college 28+), shadow shots

- no graded shots yet (the first Saturday of SHOT lines is Oct 31)

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NBA | shadow | 9 | 70 | 442 | 333 | 114 | 90 of 272 | 4 | 153 | $-302 | $+468 | $-769 | $+599 | $-901 |
