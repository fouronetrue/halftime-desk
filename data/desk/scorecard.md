# Halftime Desk scorecard

Written by the nightly export on 2026-10-27 (UTC) from the Supabase results table (190 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 228 windows on 190 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

## Lead play per game window

The play the push led with: the first single, or the middle when it led. The end-of-third window (NBA) is its own window.

| week | sport | plays | won | risked | P&L |
|---|---|---|---|---|---|
| Oct 16 to Oct 19 | CFB | 9 | 4 | $593 | $+78 |
| Oct 16 to Oct 19 | NFL | 2 | 2 | $139 | $+467 |
| Oct 20 to Oct 26 | CFB | 3 | 1 | $209 | $-98 |
| Oct 20 to Oct 26 | NBA | 4 | 1 | $486 | $-145 |
| all | all | 18 | 8 | $1,427 | $+302 |
| all, without the misreads | all | 12 | 5 | $762 | $-68 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 38 windows graded, 3 with a play, $-13 on $354.

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CFB | 111 | 43 | 21 | 8.8 | 8.7 | +1.8 on 111 (+1.8 SE), over 50% | +1.2 on 111 (+0.7 SE), over 50% |
| NBA | 52 | 27 | 5 | 12.0 | 11.2 | -1.3 on 52 (-0.7 SE), over 42% | -3.1 on 52 (-1.3 SE), over 42% |
| NFL | 27 | 11 | 5 | 7.3 | 7.6 | -0.6 on 27 (-0.3 SE), over 44% | -0.6 on 27 (-0.3 SE), over 59% |

## Drift (this season against the model)

- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +2.8 on 53 games (+2.0 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model +0.5 on 49 games (+0.2 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -2.8 on 14 games (-1.3 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CFB | half | 52 | 8 | $+697 |
| NBA | half | 48 | 7 | $+857 |
| NBA | end of 3rd | 34 | 6 | $+236 |
| NFL | half | 14 | 3 | $+172 |

## Mismatch lane (college 28+), shadow shots

- no graded shots yet (the first Saturday of SHOT lines is Oct 31)

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NBA | shadow | 4 | 36 | 222 | 168 | 56 | 46 of 138 | 0 | 76 | $-114 | $+466 | $-580 | $+579 | $-693 |
