-- Halftime Desk: Supabase schema (week 1).
-- Run once in the Supabase dashboard: SQL Editor > New query > paste > Run.
-- Safe to run again: every statement is "if not exists".
--
-- Who writes what:
--   watch.py      games, quote_snapshots, suggestions, alerts, results   (mirrors the CSVs and state.json)
--   portfolio.py  bets, positions, portfolio_snapshots                   (read-only pull from Kalshi)
-- The app (week 2) only reads. Row level security is on for every table with no policies yet, so the
-- publishable key sees nothing until week 2 adds read policies. The worker uses the secret key, which bypasses RLS.

-- One row per ESPN game the watcher has seen. Pregame lines, halftime score, final score.
create table if not exists games (
  id              text primary key,                    -- ESPN event id
  sport           text not null check (sport in ('nfl', 'cfb', 'nba')),
  name            text,
  short           text,                                -- "CSU @ TXST"
  date_et         date,
  start_utc       timestamptz,
  away_abbr       text,
  home_abbr       text,
  away_name       text,
  home_name       text,
  pre_total       numeric(5,1),
  pre_home_spread numeric(5,1),                        -- minus = home favored
  pre_source      text,                                -- espn, espn-odds, kalshi
  pre_at          timestamptz,
  kalshi_total_event text,                             -- KXNCAAFTOTAL-26OCT15CSUTXST
  phase           text,                                -- pre, approaching, half, early3, live, post
  status          text,
  half_away       int,
  half_home       int,
  half_at         timestamptz,                         -- first time the watcher priced this game at the half
  final_away      int,
  final_home      int,
  first_seen      timestamptz,
  last_seen       timestamptz,
  updated_at      timestamptz not null default now()
);

-- Every Kalshi quote the watcher saw, one row per strike per poll, with the model's view of that strike at
-- that moment. This is what makes a real backtest against Kalshi prices possible later.
create table if not exists quote_snapshots (
  id          bigint generated always as identity primary key,
  taken_at    timestamptz not null,
  game_id     text not null references games(id),
  event_ticker  text,
  market_ticker text,
  strike      numeric(5,1) not null,
  phase       text,
  yes_bid     int,                                     -- cents
  yes_ask     int,
  no_bid      int,
  no_ask      int,
  p_over      numeric(6,4),                            -- model probability the final clears the strike
  p_push      numeric(6,4),
  over_take   int,                                     -- most to pay as a taker, cents
  over_rest   int,                                     -- most to rest as a maker
  under_take  int,
  under_rest  int,
  unique (taken_at, game_id, strike)
);
create index if not exists quote_snapshots_game_time on quote_snapshots (game_id, taken_at);

-- One row per pricing pass at the half (mirrors log/halftime_log.csv), plus the full ranked singles and
-- middles the engine produced, sizes included.
create table if not exists suggestions (
  id            bigint generated always as identity primary key,
  taken_at      timestamptz not null,
  game_id       text not null references games(id),
  sport         text,
  game          text,
  date_et       date,
  event_ticker  text,
  phase         text,
  total         numeric(5,1),
  home_spread   numeric(5,1),
  half_away     int,
  half_home     int,
  mu            numeric(6,2),                          -- expected second-half points
  sd            numeric(6,2),
  fair_line     numeric(5,1),                          -- model's fair full-game total
  market_line   numeric(5,1),                          -- Kalshi's 50-50 total at that moment
  best_single   text,                                  -- "under 96.5 @20"
  best_single_edge_c numeric(6,1),
  best_mid      text,                                  -- "Y102.5@67+N108.5@52"
  best_mid_edge_c numeric(6,1),
  n_plays       int,                                   -- how many singles and middles cleared the margin
  singles       jsonb,                                 -- engine.suggest()['singles'], sorted by edge
  mids          jsonb,                                 -- engine.suggest()['mids'], sorted by ev
  bankroll      numeric(10,2),
  max_risk      numeric(10,2),
  max_cost      numeric(10,2),
  unique (taken_at, game_id)
);
create index if not exists suggestions_game_time on suggestions (game_id, taken_at);

-- Every push that went out. Two per game at most (half, q3). Body is the exact ntfy text.
create table if not exists alerts (
  id            bigint generated always as identity primary key,
  sent_at       timestamptz not null,
  game_id       text not null references games(id),
  sport         text,
  slot          text not null check (slot in ('half', 'q3')),
  kind          text not null check (kind in ('play', 'update')),
  priority      text,
  title         text,
  body          text,
  event_ticker  text,
  channels      text,                                  -- "ntfy 200"
  suggestion_at timestamptz,                           -- the suggestions row this push came from
  unique (game_id, slot)
);

-- Kalshi fills, one row per fill, pulled read-only from the portfolio API. A fill never changes, so rows are
-- insert-only. source is set once on insert by rule (halftime when the market is one the watcher priced and
-- the fill came after the half; otherwise personal) and is yours to retag; the sync never overwrites it.
create table if not exists bets (
  fill_id       text primary key,
  order_id      text,
  ticker        text not null,                         -- market ticker, KXNFLTOTAL-26OCT15BUFLAR-45
  event_ticker  text,                                  -- market ticker without the strike suffix
  outcome_side  text check (outcome_side in ('yes', 'no')),
  book_side     text,                                  -- bid or ask (Kalshi's book view of the same fill)
  count         numeric(12,2) not null,                -- contracts
  yes_price_c   numeric(7,2),                          -- cents; Kalshi fills can land on half cents
  no_price_c    numeric(7,2),
  price_c       numeric(7,2),                          -- price paid for outcome_side, cents
  cost          numeric(12,2),                         -- count * price_c / 100, before fees
  fee           numeric(10,4),
  is_taker      boolean,
  filled_at     timestamptz,
  source        text not null default 'personal' check (source in ('sharp', 'halftime', 'personal')),
  source_auto   boolean not null default true,         -- false once you retag it by hand
  game_id       text references games(id),
  ledger_id     text,                                  -- id of the matching record in the Sharp Bet Ledger
  note          text,
  synced_at     timestamptz not null default now()
);
create index if not exists bets_filled_at on bets (filled_at);
create index if not exists bets_event on bets (event_ticker);

-- Open and recently settled positions as Kalshi reports them, one row per market, replaced on every sync.
create table if not exists positions (
  ticker            text primary key,
  event_ticker      text,
  position          numeric(12,2),                     -- contracts: positive = YES, negative = NO
  total_traded      numeric(12,2),                     -- dollars
  exposure          numeric(12,2),
  realized_pnl      numeric(12,2),
  fees_paid         numeric(10,4),
  settlement_status text,
  last_updated      timestamptz,
  synced_at         timestamptz not null default now()
);

-- Balance and portfolio value each time the sync runs. The bankroll line on the Ledger screen.
create table if not exists portfolio_snapshots (
  taken_at        timestamptz primary key,
  balance         numeric(12,2),                       -- cash, dollars
  portfolio_value numeric(12,2)
);

-- One row per graded game (mirrors log/results.csv). This table is the scorecard.
create table if not exists results (
  id            bigint generated always as identity primary key,
  settled_at    timestamptz not null,
  game_id       text not null unique references games(id),
  sport         text,
  game          text,
  date_et       date,
  half          text,                                  -- "21-45" away-home
  total         numeric(5,1),
  home_spread   numeric(5,1),
  fair          numeric(5,1),                          -- model fair line at the half
  mkt           numeric(5,1),                          -- market line at the half
  final         text,                                  -- "CSU 24, TXST 52"
  final_total   int,
  model_err     numeric(5,1),
  mkt_err       numeric(5,1),
  n_plays       int,
  plays_cost    numeric(10,2),
  plays_pnl     numeric(10,2),
  mid_pnl       numeric(10,2),
  plays         text,
  rest_mid      text,
  rest_mid_pnl  numeric(10,2),
  sheet         jsonb                                  -- what the first push said, as graded
);

-- Lock every table down. The worker's secret key bypasses this; the app gets read policies in week 2.
alter table games               enable row level security;
alter table quote_snapshots     enable row level security;
alter table suggestions         enable row level security;
alter table alerts              enable row level security;
alter table bets                enable row level security;
alter table positions           enable row level security;
alter table portfolio_snapshots enable row level security;
alter table results             enable row level security;
