-- Halftime Desk, Oct 27 2026: indexes for the nightly export (scripts/export_desk.py) and the readouts.
-- Run once in the Supabase SQL Editor after 014_weather_shot.sql. Safe to run again. Takes a few seconds on the
-- quote tables; writes wait for it, so run it outside a game window.
--
-- The export picks a slate by date_et (games, suggestions, results, orders) or by a taken_at / sent_at window
-- (quote_snapshots, alerts, venue_quotes). None of those columns had an index, so every page scanned the whole
-- table: on Oct 27 the suggestions read hit Supabase's statement timeout and the backfill of Oct 17 and Oct 23
-- failed. The results and orders indexes also serve the scorecard and the shadow summary.
create index if not exists suggestions_date on suggestions (date_et, id);
create index if not exists quote_snapshots_time on quote_snapshots (taken_at, id);
create index if not exists alerts_sent on alerts (sent_at, id);
create index if not exists results_date on results (date_et, id);
create index if not exists venue_quotes_time on venue_quotes (taken_at);
create index if not exists games_date on games (date_et);
