# Halftime Desk

Watches NFL, college football and NBA games, and at the half prices every Kalshi full-game total strike with a
second-half points model fit on 2,290 NFL, 13,124 FBS and 12,849 NBA games. When a single leg or a middle (Yes on
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
   `PLAY: Away 21, Home 45 (half, CFB)` when something clears, `UPDATE: ...` when nothing does. The body reads
   in the same order every time (Oct 22):
   - `Fair 44.5. Book 46.5.` The book's number is the full-game total (the half score plus the sharp
     second-half line, when one was read), so nothing has to be added up on the phone.
   - What to do: `Buy UNDER 102.5 for $90 at 55c (-122)` lines (best first, the rest are backups, not a stack),
     then `MIDDLE:` with both legs as shares and dollars and one finals line (`43 to 45 pays +$124 (10%). Any
     other final -$5.`), then a reverse middle when one clears.
   - What you hold, as one position: `YOU HOLD Over 50.5, 279 sh at 52c. Worth 83c. Hold.` a leg (or `Bid 68c:
     SELL for +$18.`), then `Together it's a 51 to 57 middle: 50 or less -$93 (17%), 51 to 57 +$186 (25%), 58
     or more +$46 (58%).`, then `NO-LOSE HEDGE:` when one leg leaves every final at zero or better. The hedge
     is sized to the net downside of everything you hold on the total, never to one leg.
   - `REST A MIDDLE:` with the limit prices to post, shares and dollars, and the finals line. If they don't
     fill, you didn't want it. A middle you already hold on the total counts against the $15 loss cap first:
     when it has spent the cap the push says `Nothing new to post` instead of offering the same middle again.
   The priority of an UPDATE comes from `read_push` per sport; a PLAY is always high priority, and so is an
   UPDATE with a SELL verdict or a hedge.
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
| mid_loss_cap | most a middle may lose on a miss, dollars; a middle you already hold on the total spends it first | 15 |
| poll_seconds, max_poll_minutes | in-run polling during a halftime | 60, 22 |
| sharp_model_pct | per sport, the weight the model keeps when the sharp second-half line is in hand at the half (needs ODDS_API_KEY) | nfl 50, cfb 80, nba 0 |

## The Odds API (optional, 5 minutes): the sharp pregame line
Without it the pregame total and spread come from ESPN's consensus, then ESPN's odds endpoint, then Kalshi's
50-50 strike. With a key the worker reads The Odds API instead: Pinnacle's close when Pinnacle has both
numbers, else the median across DraftKings, FanDuel, BetMGM, BetOnline, LowVig, Bovada and BetRivers. ESPN's
number and every book's are kept beside it in the games row (`pre_books`, `supabase/008_pre_books.sql`), so
the ESPN-vs-sharp gap and closing line value are on record. One call covers every upcoming game of a sport
and costs 2 of the 500 free credits a month: the worker calls once when a kickoff is within three hours and
once more inside the last 25 minutes (the closing read), at most 12 calls a day per sport, only the closing
read under 40 credits left and nothing under 10. The GitHub backup never carries the key, so the quota is
spent once; it inherits the worker's lines through the games table.
1. the-odds-api.com > Get API key (free plan). The key arrives by email.
2. Railway > the halftime-desk project > the worker service > Variables > New Variable: name `ODDS_API_KEY`,
   value the key. Railway redeploys the worker on its own; the log then shows lines like
   `odds api nfl: 14 games (14 with Pinnacle), closing read, 468 credits left this month`.
3. Supabase SQL Editor: run `supabase/008_pre_books.sql` and `supabase/009_sharp.sql` once.

With the key the desk also reads the sharp second-half total at the half (Pinnacle's 2H line, else the median
of the books), one credit a game, read once and once more after four minutes, and centers the ladder between
the model and that line: `sharp_model_pct` in config.json is the weight the model keeps (nfl 50, cfb 80, nba
0). A market line is a median, and the engine turns it into the mean that puts the block's own median on the
line before blending (every block's residual median sits below its mean; taking the line as the mean had
shifted a market-centered ladder down by half a point to a point, 2 to 3 cents of under-saying the over at
every strike). On 944 NFL halftimes 2023-2026 the model and DraftKings' 2H line were a dead heat (7.54 vs 7.53 points
of miss) and within a point of each other in 99 percent of games, so the blend halves the model's own misses
without giving up its view; the 5-point gaps the live desk had seen were Kalshi's thin ladder sitting off the
sharp line, which is the edge, not the model being off. On 873 college halftimes 2024-2025 the model beat the
book's 2H line out of sample (closer in 472 games to 401, 8.28 vs 8.40 points of miss, best blend 0.9 on
the model), so college keeps 80. On 3,579 NBA halftimes 2023-24 to 2025-26 the book's line beat the model at every
weight (closer in 2,028 games to 1,551, best blend 0.0, the model's leans wrong-signed), so the NBA keeps 0 and
the model only shapes the ladder, which it does to within a cent of actual at the rungs. `claude/trust-study.md`
has the tables. The push says `Sharp 2H 24.5.` when a line was in
hand; the sheet and the suggestions row carry the center, where it came from and the sharp line, so the
model-versus-market study keeps running on every half (`python scripts/trust_study.py nfl`). The GitHub backup
carries the key too, so both watchers price the same way.

On a paid plan the history is there too: the market's second-half total at halftime for every game since May
2023, five-minute snapshots, 10 credits a game. `data/half_times_nfl.csv` (scripts/build_half_times.py, off
the nflverse play-by-play clock) says when each break started; Actions > odds history > Run workflow pulls
`data/odds_h2_nfl.csv` with the key as a repository secret (`ODDS_API_KEY` there too), resumable, inside the
credits you allow. That table is what the model-versus-market trust study runs on (Build Plan week 5).

## Supabase (optional, 10 minutes)
1. Create a free project at supabase.com. In the SQL Editor paste `supabase/schema.sql` and run it, then
   `002_week2.sql` through `009_sharp.sql` in order (all safe to run again). Every table has row level
   security on; the app reads as a signed-in user and only the secret key can write.
2. Settings > API Keys: copy the project URL and the **secret** key (`sb_secret_...`). Add two repository secrets:
   `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. The publishable key is for the app later, not for the worker.

### Nightly export to the repo
`.github/workflows/export.yml` runs `scripts/export_desk.py` every morning at 10:40 UTC (after the slate closes
at 05:00 ET) and commits the desk's own rows as `data/desk/TABLE/DATE.csv.gz`: games, suggestions, alerts,
results, quote_snapshots and venue_quotes, one file per table per slate. It re-checks the last three slates, so
a missed night heals itself; games, suggestions, alerts and results are rewritten when a day's rows changed (a
final or a grade landing late), the quote files are written once. Two tables are thinned so the repo grows about
10 MB a month instead of 70: quote_snapshots keeps every row at a break and, pregame, one poll an hour per game
plus the close; suggestions keeps every row's numbers but the singles, mids and revs JSON only on the first and
last row of a game's break and on the row a push came from. Run it by hand from the Actions tab with a date or
`force`. The repo is public, so it never exports bets, positions, portfolio_snapshots, desk_state (the
bankroll), control or orders, drops bankroll, max_risk, max_cost and held from suggestions, and strips the held
block out of every JSON column; `tests/export.py` holds it to that. Once the files are in, old quote rows can be
pruned from Supabase before the free tier fills (around March at the current rate).

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

## Football models
The `nfl` block (2,290 games, SBR archive) was checked on Oct 22 against 5,496 nflverse games 2006-2026
(`data/nfl_games.csv`, 7,058 games 2000-2026 with roof, temp and wind, built by `scripts/build_nfl_games.py`):
it prices within a cent of actual at the rungs the desk uses, blowouts included, and a running-clock term fits
at zero, so it stays as it is. The one lean is big spreads (10.5+), 2.3 cents hot on 535 games, under the
margin; a spread-size term is the candidate if the live scorecard ever shows those overs bleeding.
`python scripts/fit_nfl.py data/nfl_games.csv` reprints the check.

The `cfb` block is fit on 13,124 FBS games, 2006-2025 (`data/cfb_games.csv`: halftime scores off the cfbfastR
play by play, finals checked against the schedules, Pinnacle closing lines). It carries one term the NFL block
does not: the running clock, minus 0.20 second-half points for every point of halftime margin past 14. A team
up four scores sits on the ball, and the six-term shape priced that second half as if both sides kept
throwing: at the rungs the desk prices it said OVER 56 percent in 36+ point blowouts where overs hit 43, a
phantom 10-cent OVER edge on exactly the games that kneel. With the term the same bucket reads 44.6 vs 43.1,
and every other slice (by total, spread, season, trailing favorite) sits within 0.3 points of zero out of
sample. The oft-repeated "60+ first-half points means a 20-point second half" is not in the data (115 games,
29.6 actual, 30.9 model). `python scripts/fit_cfb.py data/cfb_games.csv` reprints the study (`--write` refits
the block); `scripts/build_cfb_games.py` rebuilds the table. The study is in `claude/cfb-blowout-refit.md`.

## Bankroll from the live balance
Every cap is a percentage of `bankroll`. The worker sets it from Kalshi instead of a number typed into
`config.json`: the first time it runs with no stored bankroll, and every Tuesday after that (the unit-reset day),
the bankroll becomes the newest portfolio snapshot's cash plus positions at market, rounded to the dollar, when
that snapshot is under 36 hours old and the number is at least $500. It is stored in `desk_state` (id `bankroll`)
so the worker and the GitHub backup size alike; `config.json` is the seed and the fallback. `"bankroll_auto": false`
in `config.json` turns it off.

## The push carries the market
Every push's tap target is the Kalshi event page (`kalshi.com/markets/<series>/event/<event ticker>`), and the
notification carries an Open market button; Pushover gets the same as its supplementary URL. One tap from the
alert to the market. The Today card at a break and the Desk have the same button.

## Auto orders (trade.py), shadow first
`trade.py` is the one module that may send an order, and `tests/readonly.py` fails the build if any other file
names an order endpoint. It runs in the worker only, and only with an `auto` block in `config.json`:

| key | meaning | default |
|---|---|---|
| mode | shadow (record what it would send, send nothing) or live | shadow |
| sports | which sports it plans for | nba |
| rest_mode | pair: the push's resting middle legs (tight and wide for the NBA); ladder: YES on every strike at or below fair and NO on every strike at or above it, within rest_near_pts | pair |
| rest_until | how long a resting order lives: break (the end of the half) or q4 (the start of the fourth, the push's own cancel rule) | q4 |
| pair_miss_pct, pair_miss_max | per game: if every resting order filled, the worst final loses at most this % of bankroll (or this many dollars when set), less what you already hold on the total | 0.5, none |
| night_loss_pct, night_loss_max | once the night's graded auto orders have lost this much, nothing new is posted | 5, none |
| rest_capital_pct | open resting orders at once, % of bankroll | 40 |
| singles | also send the push's lead (the cleared middle, else the first single) as immediate-or-cancel orders at the ask (phase 3); shadow records them regardless | false |
| max_orders_per_game, max_orders_per_night | hard stops | 12, 200 |

At the first look at a break the worker plans the orders at the resting limits the push names, sizes them under
the cap (the caps count every leg at once, plus a middle you already hold), and in shadow mode writes them to the
`orders` table (`supabase/011_orders.sql`). It then keeps reading that game's ladder through the third quarter: a
resting bid is marked touched when the ask reaches it, with the phase (the break or in play) and the seconds since
the first look, and at the final every touched order is graded. `python trade.py --readout` prints the readout
(orders, fills at the break vs in play, both legs of a middle filled, P&L); the scorecard carries the same line.

Live mode sends only when, at the moment of sending, all of these hold: `auto.mode` is live, the environment has
`TRADE_ENABLED=1`, the trade key is present (`KALSHI_TRADE_KEY_ID` and `KALSHI_TRADE_PRIVATE_KEY`, a second
Kalshi key kept in the Railway worker's variables only, never in GitHub secrets, so the Actions backup can never
trade), and the `control` row (id `trade`) does not say kill. Every order is a buy limit order at the engine's
price and count, post-only when resting, with a `client_order_id` built from the game, window, strike, side and
price (a restart cannot post it twice) and an `expiration_ts` at the window's end (a dead worker leaves nothing
resting). The kill switch cancels what is resting and stops every send until it is turned off. `tests/trade_guard.py`
pins all of it, and the fixtures run plans in shadow with the network forbidden.

## Polymarket price log
At every break the worker also reads Polymarket's total lines for the same game (the public Gamma API, no key;
events are slugged `nba-bos-det-2026-10-20`, with full-game and first-half totals) every 15 seconds and writes each
line's Over bid and ask in cents beside Kalshi's quote at that strike at the same moment (`venue_quotes`,
`supabase/012_venues.sql`). Nothing prices off it. It answers the cross-venue question before any order crosses a
venue: does one ladder lag the other at the half, on which strikes, by how much. NBA and NFL for now (no slug
scheme for college yet).

## Manual use
```
python cli.py --sport nfl --away BUF --home LAR --spread -3.5 --total 55.5 --half 13-7 --quotes "45.5y59,48.5y47,51.5n66"
python cli.py --sport nba --away BOS --home DET --spread -1.5 --total 221.5 --half 58-61 --center 230.5 --quotes "236.5y21,238.5n73"
```
Quotes are Kalshi asks in cents. Same engine, same PLAY/UPDATE text as the push, then the full ladder. For the
NBA, `--center` is the market's full-game line at the half (Kalshi's 50-50 line, or a sharp 2H line plus the
halftime score); without it the model prices on its own center.

## What deploys the worker (Railway)
Railway builds the worker from the `worker` branch, not from `main`. `worker release` (`.github/workflows/release.yml`)
moves `worker` to a commit on `main` only when it changes what the worker runs (the root `.py` modules,
`config.json`, `model.json`, `requirements.txt`, `.python-version`, `railway.json`) and only after the full test
suite passes on it, fast-forward only. The backup's `state.json` and log saves, the nightly `data/desk` export, the
app and the docs never touch `worker`, so they never rebuild or restart the worker. Before Oct 24 Railway followed
`main`: its watch patterns skipped most state saves but not all, so the worker restarted mid-slate for a save, and
Railway's own builder failures arrived as emails about commits with no code in them. `tests/release.py` keeps
the path list matched to what `worker.py` imports. After moving the branch the run waits for Railway's status on
the commit and fails (GitHub emails you) if none shows up in 4 minutes, which means Railway is not listening to
`worker` (its service settings have been reported to drift back to `main`). To ship by hand: Actions > worker
release > Run workflow.
A Railway variable change still redeploys the worker on its own, from the newest commit on `worker`.

## Honest limits
- The model knows the lines, the score and the clock. It does not know injuries, weather or pace. That is why the
  market price gets half the weight once it is known, and why a 3-cent edge is required.
- Kalshi's second-half line already discounts blowouts. The edge the desk reports is the gap between the model
  and the price you can actually get, nothing more.
- GitHub's cron can run a few minutes late. In-run polling covers most of it; the log shows what was missed.
  The windows run until about 4 AM Eastern after each game night so West Coast finals get graded.
- A game the watcher never saw before kickoff has no pregame line on record and is skipped at the half, on
  purpose: a line read after kickoff is the live line, and pricing off it cost real money on Oct 17.
- Nothing places an order until `auto.mode` is live and every switch in the Auto orders section is on. Until then
  you tap buy.

## Files
`engine.py` model and pricing (pure). `feeds.py` ESPN and Kalshi readers and game matching. `watch.py` the loop,
state and alerts. `data/nba_games.csv` and `scripts/fit_nba.py` the NBA history and its fit. `data/cfb_games.csv`, `scripts/build_cfb_games.py` and `scripts/fit_cfb.py` the FBS history (13,127 games, 2006-2025, halftime scores from play by play), how it is built, and the second-half fit with the blowout study; `data/nfl_games.csv`, `scripts/build_nfl_games.py` and `scripts/fit_nfl.py` the same for the NFL (7,058 games, 2000-2026). `worker.py` the always-on loop. `notify.py` push. `store.py` Supabase writer. `portfolio.py`
read-only Kalshi sync. `held.py` open-position watch. `trade.py` the order executor (shadow by default). `cli.py` manual desk. `model.json` fitted coefficients and
residual quantiles. `data/nfl_features.csv.gz` and `data/cfb_features.csv.gz` (`scripts/build_nfl_features.py`,
`scripts/build_cfb_features.py`) per-game play-by-play features by half (yards, plays, turnovers, missed kicks,
return TDs, red zone, fourth downs, late and garbage-time points, kickoff time, weather) and
`scripts/study_tails.py` the tail study that reads them (claude/tail-study-oct24.md). `supabase/` the tables, in order. `scripts/save_run.py` commits a run's state and log rows
without ever committing a conflict. `scripts/export_desk.py` the nightly Supabase export to `data/desk/`. `tests/` parity check against the ledger artifact, the read-only proof, the
mirror check, the worker and held-position checks, the Oct 17 fixes (`fixes.py`), the NBA path (`nba.py`, on
`fixtures_nba/`), reverse middles and held positions at the half (`reverse.py`), the football model blocks and game tables (`football.py`), what moves the worker branch (`release.py`), and an offline run on fixtures.
