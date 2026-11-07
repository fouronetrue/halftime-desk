# Halftime Desk scorecard

Written by the nightly export on 2026-11-07 (UTC) from the Supabase results table (483 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 601 windows on 483 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 3 to Nov 6 | CBB SHADOW | 4 | 4 | $77 | $+84 |
| all | all | 23 | 9 | $1,496 | $+270 |
| all, without the misreads | all | 17 | 6 | $831 | $-100 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 118 windows graded, 3 with a play, $-13 on $354.

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 130 | 55 | 27 | 9.2 | 9.3 | +0.6 on 130 (+0.5 SE), over 51% | -0.5 on 130 (-0.4 SE), over 50% |
| CFB | 179 | 67 | 38 | 8.5 | 8.4 | +1.3 on 179 (+1.6 SE), over 48% | +0.9 on 179 (+0.7 SE), over 48% |
| NBA | 132 | 59 | 27 | 11.9 | 11.6 | -1.5 on 132 (-1.2 SE), over 38% | -2.8 on 132 (-1.8 SE), over 44% |
| NFL | 42 | 15 | 5 | 7.7 | 7.8 | +0.3 on 42 (+0.2 SE), over 50% | -0.0 on 42 (-0.0 SE), over 57% |

## Drift (this season against the model)

- CBB: finals vs the model -0.5 on 130 games (-0.4 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +1.3 on 121 games (+1.3 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -1.0 on 129 games (-0.7 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -0.6 on 29 games (-0.3 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 126 | 21 | $+248 |
| CBB SHADOW | half | 4 | 3 | $+73 |
| CFB | half | 119 | 19 | $+910 |
| NBA | half | 128 | 12 | $+900 |
| NBA | end of 3rd | 114 | 17 | $+343 |
| NFL | half | 29 | 5 | $+199 |

## Mismatch lane (college 28+), shadow shots

- no graded shots yet (the first Saturday of SHOT lines is Oct 31)

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NBA | shadow | 14 | 109 | 691 | 510 | 168 | 132 of 422 | 4 | 246 | $-437 | $+504 | $-941 | $+673 | $-1,110 |
