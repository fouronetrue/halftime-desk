-- Halftime Desk, Oct 23 2026: another venue's ladder at the break, beside Kalshi's.
-- Run once in the Supabase SQL Editor after 011_orders.sql. Safe to run again.
--
-- venue_quotes: at every break the worker reads Polymarket's total lines for the same game (the full game and
-- the first half) every 15 seconds and writes each line's bid and ask in cents next to Kalshi's at that strike
-- at the same moment. Nothing prices off it; the cross-venue question (does one ladder lag the other, and by how
-- much) is read from this table. Until this runs the worker prints the usual missing-table line and the pass goes on.
create table if not exists venue_quotes (
  taken_at timestamptz not null,
  game_id text not null,
  sport text,
  venue text not null,          -- polymarket
  kind text not null,           -- fg (the full game) or 1h (the first half)
  strike numeric not null,
  phase text,
  stage text,                   -- half or q3
  yes_bid integer,              -- Over, cents
  yes_ask integer,
  no_bid integer,               -- Under, cents (the mirror of the Over side on a two-outcome book)
  no_ask integer,
  market_id text,
  kalshi_yes_bid integer,       -- Kalshi's quote at the same strike at the same moment, when Kalshi lists it
  kalshi_yes_ask integer,
  kalshi_no_bid integer,
  kalshi_no_ask integer,
  primary key (taken_at, game_id, venue, kind, strike)
);
create index if not exists venue_quotes_game on venue_quotes (game_id, taken_at);
alter table venue_quotes enable row level security;
