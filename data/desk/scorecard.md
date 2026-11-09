# Halftime Desk scorecard

Written by the nightly export on 2026-11-09 (UTC) from the Supabase results table (636 games, graded by the worker and the GitHub backup) plus the 0 games only log/results.csv has (graded before the mirror existed). One row a game window; 767 windows on 636 games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.

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
| Nov 3 to Nov 8 | CBB SHADOW | 5 | 4 | $90 | $+71 |
| Nov 3 to Nov 8 | CFB | 3 | 0 | $50 | $-50 |
| all | all | 26 | 9 | $1,546 | $+220 |
| all, without the misreads | all | 20 | 6 | $881 | $-150 |

Misreads: 6 plays ($+370) from windows whose fair line sat 10+ points from the market, the quarter-break bug's signature (a quarter's score priced as a break; fixed Oct 25, claude/breaks-oct25.md): CFB WMU @ CMU Oct 17 $+106, NFL ARI @ LAR Oct 18 $+408, NBA DEN @ OKC Oct 22 (end of 3rd) $+251, NBA GS @ PHX Oct 24 (end of 3rd) $-132, NBA MIA @ CHA Oct 24 $-132, NBA LAC @ OKC Oct 25 (end of 3rd) $-132.

End of 3rd (NBA): 131 windows graded, 3 with a play, $-13 on $354.

## Model against the market

Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.

| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |
|---|---|---|---|---|---|---|---|
| CBB | 205 | 89 | 44 | 8.9 | 9.0 | +1.8 on 205 (+2.2 SE), over 56% (past 2 SE, watch) | +0.5 on 205 (+0.5 SE), over 53% |
| CFB | 225 | 84 | 47 | 8.9 | 8.8 | +1.4 on 225 (+1.9 SE), over 47% | +1.2 on 225 (+1.1 SE), over 48% |
| NBA | 146 | 63 | 30 | 11.9 | 11.6 | -1.1 on 146 (-0.9 SE), over 39% | -2.6 on 146 (-1.7 SE), over 43% |
| NFL | 55 | 20 | 8 | 7.6 | 7.7 | +0.3 on 55 (+0.2 SE), over 49% | -0.1 on 55 (-0.1 SE), over 55% |

## Drift (this season against the model)

- CBB: finals vs the model +0.7 on 205 games (+0.9 SE)
- CFB: finals vs the fair line +0.4 on 58 games (+0.2 SE)
- CFB: finals vs the model +1.4 on 169 games (+1.6 SE)
- NBA: finals vs the fair line -0.5 on 3 games (-0.0 SE)
- NBA: finals vs the model -0.9 on 143 games (-0.7 SE)
- NFL: finals vs the fair line +3.6 on 13 games (+1.4 SE)
- NFL: finals vs the model -0.3 on 42 games (-0.2 SE)

## Resting middles, what-if (assumes both legs filled)

| sport | window | games | hits | P&L |
|---|---|---|---|---|
| CBB | half | 200 | 40 | $+590 |
| CBB SHADOW | half | 5 | 3 | $+71 |
| CFB | half | 166 | 22 | $+932 |
| NBA | half | 142 | 13 | $+912 |
| NBA | end of 3rd | 127 | 20 | $+389 |
| NFL | half | 42 | 7 | $+231 |

## Mismatch lane (college 28+), shadow shots

- no graded shots yet (the first Saturday of SHOT lines is Oct 31)

## Came and went (cleared between pushes, not played)

- nothing came and went yet

## Auto orders (shadow fill model: the ask touched the resting bid)

Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg. P&L at the break is what the night would have made with every resting order pulled when the break ended.

| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | both at the break | one leg | P&L all | P&L at the break | P&L in play | P&L (both) | P&L (lone) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CBB | shadow | 2 | 41 | 79 | 65 | 29 | 24 of 41 | 2 | 17 | $+141 | $+24 | $+117 | $+136 | $+5 |
| CFB | shadow | 1 | 16 | 34 | 27 | 16 | 11 of 17 | 1 | 5 | $-86 | $-37 | $-48 | $-13 | $-73 |
| NBA | shadow | 16 | 117 | 744 | 554 | 179 | 146 of 454 | 5 | 262 | $-423 | $+517 | $-940 | $+691 | $-1,114 |
| NFL | shadow | 1 | 13 | 26 | 21 | 15 | 8 of 13 | 2 | 5 | $+15 | $+3 | $+11 | $+36 | $-21 |
