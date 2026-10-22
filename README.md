# Halftime Desk

Watches NFL, college football and NBA games, and at the half prices every Kalshi full-game total strike with a
second-half points model fit on 2,290 NFL, 6,506 FBS and 12,849 NBA games. When a single leg or a middle (Yes on
a lower total plus No on a higher one) clears the edge, it sends a push notification with the play, the price,
how many shares or pairs, and the resting limits for every strike near fair.

## What it does each run
1. Reads ESPN's scoreboards (NFL, FBS, NBA). For games not yet kicked off it stores the pregame spread and total
   (ESPN's odds block, then ESPN's odds endpoint, then Kalshi's 50-50 strikes). That stored line is the only
   line a game is ever priced off. Once a game has kicked off nothing read from a feed is accepted as its
   pregame line (by then the feeds show the live line); a watcher that lost its record of the line takes it
   from the games table in Supabase, where the other watcher saved it before kickoff, or skips the game.
2. For games at the half, or in the first minutes of the third quarter while the score is still the halftime
   score, it pulls the Kalshi total event for that game, prices each strike (fair over and under, max price to
   take, max resting limit), scores every single leg and every Yes-low/No-high pair against the asks, and sizes
   anything that clears the edge. The moment the live score moves off the halftime score, pricing stops: no
   row is logged or written and nothing is pushed, so the newest suggestions row is always one priced at the
   score it shows, and the app marks it stale when the games row's live score no longer matches it.
3. Pushes exactly twice per game: once the first time the game is seen at the half (within about a minute of
   the end of Q2), once the first time it is seen after the Q3 kick with the score unchanged. The title is
   `PLAY: Away 21, Home 45 (half, CFB)` when something clears, `UPDATE: ...` when nothing does.
   - PLAY body: `Buy UNDER 102.5 for $90 at 55c (-122)` lines (best first, the rest are backups, not a stack),
     then `MIDDLE:` with both legs as `Buy OVER 93.5 at 60c (227 shares for $136)` and the win/lose line.
   - UPDATE body: `POSSIBLE MIDDLE (post as limit orders):` with the most you should pay on each side for the
     pair to still carry the edge, shares and dollars, and what happens if both fill. If they don't fill, you
     didn't want it.
   - `REVERSE MIDDLE:` when the ladder prices the numbers between two strikes too dear: NO on the lower strike
     plus YES on the higher one, one leg pays on any final outside that hole, both lose inside it. The edge a
     pair is 1 minus the pair cost minus P(hole), the mirror of the middle's rule, and it is the two legs'
     single edges added together: a reverse that clears is two cheap wings, sized as one bet (quarter Kelly
     on the pair, the hole as the risk, under the single caps). It follows the singles and the middle
     (instead of, not on top) and leads the push only when it is all that cleared. Expect it rarely; the
     stale wings that feed middles run the other way.
   - `YOU HOLD Over 44.5, 100 sh at 48c. Fair now 61c.` when you own a side of this total (from the Kalshi
     sync): the bid against fair with a SELL or HOLD verdict and both numbers; `PAIR IT:` the other side
     beyond your strike when it clears as a single (your shares, the three finals in dollars); `LAY OFF:` the
     other side short of your strike when it clears (a reverse on the leg you own); `FREE:` the completion
     your leg pays for outright, with that leg's own edge, which can be negative. On a read with something to
     do the block goes first and the push is high priority whatever `read_push` says.
   The priority of an UPDATE comes from `read_push` per sport; a PLAY is always high priority.
4. Logs every priced halftime to `log/halftime_log.csv`, and when the game goes final grades what the first push
   said against the final total in `log/results.csv` (first single, middle, reverse middle, and the what-if resting middle),
   plus the model's fair line against the market's. What is graded is what was pushed: every push carries its
   sheet (the plays at their prices and sizes) on its row in the `alerts` table, and the game's record is the
   first PLAY push (the half, or Q3 when the half was a read), else the first push's resting what-if. The play
   is what the push led with: the first single (the rest are backups, one or the other, never a stack), the
   middle when the push led with one, or the reverse middle when it was all that cleared. Both watchers grade that same push, so a watcher that saw the game
   late never overwrites the record with an empty sheet. `scripts/regrade.py` (the `regrade` input on the
   portfolio sync workflow) rebuilds every settled game from its pushes. The push is a snapshot; between the
   pushes the ladder keeps moving and a line can clear the edge for a while and go away again (that is what the
   Today screen shows and the push did not). At the final the watcher also grades every line that cleared in any
   priced row of the half, pushed or not, at the best price it showed (`results.flickers`; the Record screen
   calls them "came and went"), so whether those are worth chasing is answered by the count, not by memory.
   Today tags each live BET line with how long it has held. `python watch.py --scorecard` prints the season to date;
   every run prints it too. Both files and `state.json` are committed back to the repo by
   `scripts/save_run.py`, which appends the run's CSV rows to whatever is on main and takes `state.json`
   whole, so a run can never commit a merge conflict into the log.
5. If any game is approaching the half (Q2 under 5:00) or at the half, the run keeps polling every
   `poll_seconds` for up to `max_poll_minutes`, so a 5-minute cron still covers the whole halftime window.
6. With Supabase keys set, everything above also lands in Supabase as it happens: `games`, `quote_snapshots`
   (every strike's bid and ask next to the model's number, every poll), `suggestions` (with the live score it
   was priced at, the ranked singles, middles and reverse middles, and what you held with the verdicts;
   `supabase/005_reverse.sql` adds the last two columns), `alerts` (the exact push text) and `results`. The CSVs stay the source of truth; a
   failed write prints one line and the watch goes on. A column the schema does not have yet (a file in
   `supabase/` not run) is dropped from the write and reported once, so the mirror keeps flowing.
7. With a Kalshi API key set, the run ends by pulling your balance, positions and fills (read-only) into
   `portfolio_snapshots`, `positions` and `bets`. A separate `portfolio sync` workflow does the same every two
   hours between game windows. Fills in a market the watcher priced at the half, filled after the half, are
   tagged `halftime`; everything else is `personal` until you retag it. The sync never overwrites a tag. The
   balance goes to Supabase only; no dollar figure is printed to the Actions log.

## Setup (10 minutes)
1. Create a GitHub repo (public is free for Actions minutes; private gets 2,000 minutes a month, enough if you
   trim the cron windows). Upload these files, or let Claude push them once GitHub is connected in claude.ai.
2. Install the ntfy app on your phone (free) and subscribe to a topic with a name nobody would guess, for example
   `halftime-desk-7k2m9q`. In the repo: Settings > Secrets and variables > Actions > New repository secret:
   name `NTFY_TOPIC`, value the topic name. (Pushover works too: `PUSHOVER_TOKEN` and `PUSHOVER_USER`.)
3. Actions tab > enable workflows. `halftime watch` runs on its own schedule; use Run workflow to test it now.
4. Edit `config.json` when the bankroll changes:

| key | meaning | default |
|---|---|---|
| bankroll | Kalshi balance used for sizing | 3590 |
| risk_pct | most to lose on one game, % of bankroll | 2.5 |
| cost_pct | most to spend on one game, % | 7.5 |
| margin_c | edge needed before a play is called, cents | 3 |
| trust_pct | weight on the model vs the market price in the fair number | 50 |
| order | taker (fee) or maker (resting, no fee) when pricing the asks | taker |
| read_push | per sport, the ntfy priority of an UPDATE: default (normal), min (silent, shows in the app list only), off | nfl default, cfb default |
| min_price_c, max_price_c | ignore legs priced outside this band (model tails are not trusted) | 15, 85 |
| day_cost_pct | most to suggest across all plays in one day, % of bankroll | 20 |
| poll_seconds, max_poll_minutes | in-run polling during a halftime | 60, 22 |

## Supabase (optional, 10 minutes)
1. Create a free project at supabase.com. In the SQL Editor paste `supabase/schema.sql` and run it, then
   `002_week2.sql` through `006_flickers.sql` in order (all safe to run again). Every table has row level
   security on; the app reads as a signed-in user and only the secret key can write.
2. Settings > API Keys: copy the project URL and the **secret** key (`sb_secret_...`). Add two repository secrets:
   `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. The publishable key is for the app later, not for the worker.

## Kalshi portfolio sync (optional, 10 minutes)
1. kalshi.com > profile > API Keys > Create New API Key. Ed25519 (the default) or RSA both work. Save the
   private key file; Kalshi shows it once.
2. Add two repository secrets: `KALSHI_API_KEY_ID` (the key id) and `KALSHI_PRIVATE_KEY` (paste the whole PEM
   file, BEGIN and END lines included).
3. Actions > portfolio sync > Run workflow with backfill checked, once, to pull your fill history.

Kalshi API keys have no permission scopes: a key that can read your fills could also trade. The read-only
guarantee lives in the code instead. `portfolio.py` signs GET requests only, nothing in the repo names an order
endpoint, and `tests/readonly.py` fails the build if either changes. Nothing here places, cancels or changes an
order.

With the key in place the worker also watches what you hold (`held.py`). For every open full-game total, once a
minute from three hours before kickoff, it prices the other side on nearby strikes from the live Kalshi book. When
owning both would clear the middle breakeven (pair cost with fees under 0.97 + 3.5c per winning number NFL, 2.4c
CFB, with at least 1c of room and both prices inside 15 to 85c) it pushes MIDDLE OPEN: the leg to buy, the share
count (held to a $15 miss), both outcomes, and what selling at the bid would make instead. It pushes once, and
again only when the pair gets 2c better. Games at the half are the engine's; live games are skipped.

## NBA
Same loop, same ladder, same rules (3-cent margin, 15 to 85c band, quarter Kelly and the caps, two pushes a
game), one difference in where the center of the ladder comes from. 24,437 games of history (2007-08 through
2025-26, `data/nba_games.csv`) say the NBA second half runs at the pregame pace whatever the half looks like:
expected second-half points are 5.3 + 0.474 x the pregame total, and the halftime margin, who is favored, home
or away and first-half pace all carry a coefficient of zero. No spot leans over or under against the market's
own second-half line (home favorite trailing, small favorite leading, blowouts: every cell 47 to 53 percent).
The model's center is 2.4 points from the sharp line in the median game and never beats it; its shape is
calibrated to a cent at every strike. So for the NBA the watcher centers the ladder on the market (Kalshi's
implied full-game line at the half minus the first-half points) and keeps the model for the shape, with
`center_model_pct` (25) on the model's own number. Football keeps its own center as before. Kalshi's NBA
ladder has 31 strikes every 2 points, so an NBA middle is two numbers wide at least; a number is worth 2.9c a
pair in the breakeven rule. Overtime is in the fit (a full-game total settles on it). The Q3 push slot is the
first 30 seconds of the third quarter, because a basket comes in seconds and the score-moved rule then stops
pricing. The study and the decisions are in `claude/nba-halftime.md`; `python scripts/fit_nba.py
data/nba_games.csv` reprints it (`--write` refits the block in `model.json`). Run `supabase/004_nba.sql` once
so the games table accepts the sport.

The NBA's second push is the end of the third quarter, not the start (a basket comes in seconds, so the
early-Q3 look never happens there). In the break before the fourth, and its first 30 seconds while the score is
still the end-of-third score, the watcher prices the same ladder with the end-of-third model (`engine.LateModel`,
the `nba_q3` block: regulation fourth-quarter points plus an overtime mixture by the margin after three, 9 percent
in a close game and 0.3 percent at 18+), centered on the ladder the same way, and pushes once as slot q3 ("end of
3rd, NBA"). Resting middles there say "cancel what has not filled by the first timeout of the 4th". The final
grades it on the game's results row in the q3_ columns (`supabase/007_q3.sql`); `log/results.csv` upgrades its
own header the first time. `python scripts/fit_nba_q3.py` reprints the fit and its calibration.

## Manual use
```
python cli.py --sport nfl --away BUF --home LAR --spread -3.5 --total 55.5 --half 13-7 --quotes "45.5y59,48.5y47,51.5n66"
python cli.py --sport nba --away BOS --home DET --spread -1.5 --total 221.5 --half 58-61 --center 230.5 --quotes "236.5y21,238.5n73"
```
Quotes are Kalshi asks in cents. Same engine, same PLAY/UPDATE text as the push, then the full ladder. For the
NBA, `--center` is the market's full-game line at the half (Kalshi's 50-50 line, or a sharp 2H line plus the
halftime score); without it the model prices on its own center.

## Honest limits
- The model knows the lines, the score and the clock. It does not know injuries, weather or pace. That is why the
  market price gets half the weight once it is known, and why a 3-cent edge is required.
- Kalshi's second-half line already discounts blowouts. The edge the desk reports is the gap between the model
  and the price you can actually get, nothing more.
- GitHub's cron can run a few minutes late. In-run polling covers most of it; the log shows what was missed.
  The windows run until about 4 AM Eastern after each game night so West Coast finals get graded.
- A game the watcher never saw before kickoff has no pregame line on record and is skipped at the half, on
  purpose: a line read after kickoff is the live line, and pricing off it cost real money on Oct 17.
- Nothing here places orders. You tap buy. Auto-execution is a different risk discussion.

## Files
`engine.py` model and pricing (pure). `feeds.py` ESPN and Kalshi readers and game matching. `watch.py` the loop,
state and alerts. `data/nba_games.csv` and `scripts/fit_nba.py` the NBA history and its fit. `data/cfb_games.csv`, `scripts/build_cfb_games.py` and `scripts/fit_cfb.py` the FBS history (10,491 games, 2006-2022, halftime scores from play by play), how it is built, and the second-half fit with the blowout study. `worker.py` the always-on loop. `notify.py` push. `store.py` Supabase writer. `portfolio.py`
read-only Kalshi sync. `held.py` open-position watch. `cli.py` manual desk. `model.json` fitted coefficients and
residual quantiles. `supabase/` the tables, in order. `scripts/save_run.py` commits a run's state and log rows
without ever committing a conflict. `tests/` parity check against the ledger artifact, the read-only proof, the
mirror check, the worker and held-position checks, the Oct 17 fixes (`fixes.py`), the NBA path (`nba.py`, on
`fixtures_nba/`), reverse middles and held positions at the half (`reverse.py`), the CFB model block and game table (`cfb_model.py`), and an offline run on fixtures.
