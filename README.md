# Halftime Desk

Watches NFL and college football games, and at the half prices every Kalshi full-game total strike with a
second-half points model fit on 2,290 NFL and 6,506 FBS games. When a single leg or a middle (Yes on a lower
total plus No on a higher one) clears the edge, it sends a push notification with the play, the price, how many
shares or pairs, and the resting limits for every strike near fair.

## What it does each run
1. Reads ESPN's scoreboards (NFL, FBS). For games not yet kicked off it stores the pregame spread and total
   (ESPN's odds block, or Kalshi's 50-50 strikes as the fallback).
2. For games at the half, or in the first minutes of the third quarter, it pulls the Kalshi total event for that
   game, prices each strike (fair over and under, max price to take, max resting limit), scores every single leg
   and every Yes-low/No-high pair against the asks, and sizes anything that clears the edge.
3. Pushes exactly twice per game: once the first time the game is seen at the half (within about a minute of
   the end of Q2), once the first time it is seen after the Q3 kick with the score unchanged. The title is
   `PLAY: Away 21, Home 45 (half, CFB)` when something clears, `UPDATE: ...` when nothing does.
   - PLAY body: `Buy UNDER 102.5 for $90 at 55c (-122)` lines (best first, the rest are backups, not a stack),
     then `MIDDLE:` with both legs as `Buy OVER 93.5 at 60c (227 shares for $136)` and the win/lose line.
   - UPDATE body: `POSSIBLE MIDDLE (post as limit orders):` with the most you should pay on each side for the
     pair to still carry the edge, shares and dollars, and what happens if both fill. If they don't fill, you
     didn't want it.
   The priority of an UPDATE comes from `read_push` per sport; a PLAY is always high priority.
4. Logs every priced halftime to `log/halftime_log.csv`, and when the game goes final grades what the first push
   said against the final total in `log/results.csv` (first single, middle, and the what-if resting middle),
   plus the model's fair line against the market's. `python watch.py --scorecard` prints the season to date;
   every run prints it too. Both files and `state.json` are committed back to the repo.
5. If any game is approaching the half (Q2 under 5:00) or at the half, the run keeps polling every
   `poll_seconds` for up to `max_poll_minutes`, so a 5-minute cron still covers the whole halftime window.
6. With Supabase keys set, everything above also lands in Supabase as it happens: `games`, `quote_snapshots`
   (every strike's bid and ask next to the model's number, every poll), `suggestions`, `alerts` (the exact push
   text) and `results`. The CSVs stay the source of truth; a failed write prints one line and the watch goes on.
7. With a Kalshi API key set, the run ends by pulling your balance, positions and fills (read-only) into
   `portfolio_snapshots`, `positions` and `bets`. A separate `portfolio sync` workflow does the same every two
   hours between game windows. Fills in a market the watcher priced at the half, filled after the half, are
   tagged `halftime`; everything else is `personal` until you retag it. The sync never overwrites a tag.

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
1. Create a free project at supabase.com. In the SQL Editor paste `supabase/schema.sql` and run it (safe to run
   again). Every table has row level security on with no policies, so only the secret key can read or write.
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

## Manual use
```
python cli.py --sport nfl --away BUF --home LAR --spread -3.5 --total 55.5 --half 13-7 --quotes "45.5y59,48.5y47,51.5n66"
```
Quotes are Kalshi asks in cents. Same engine, same PLAY/UPDATE text as the push, then the full ladder.

## Honest limits
- The model knows the lines, the score and the clock. It does not know injuries, weather or pace. That is why the
  market price gets half the weight once it is known, and why a 3-cent edge is required.
- Kalshi's second-half line already discounts blowouts. The edge the desk reports is the gap between the model
  and the price you can actually get, nothing more.
- GitHub's cron can run a few minutes late. In-run polling covers most of it; the log shows what was missed.
- Nothing here places orders. You tap buy. Auto-execution is a different risk discussion.

## Files
`engine.py` model and pricing (pure). `feeds.py` ESPN and Kalshi readers and game matching. `watch.py` the loop,
state and alerts. `notify.py` push. `store.py` Supabase writer. `portfolio.py` read-only Kalshi sync.
`cli.py` manual desk. `model.json` fitted coefficients and residual quantiles. `supabase/schema.sql` the tables.
`tests/` parity check against the ledger artifact, the read-only proof, the mirror check, and an offline run on fixtures.
