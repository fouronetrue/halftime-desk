-- Halftime Desk, Oct 20 2026: reverse middles and held positions at the half.
-- Run once in the Supabase SQL Editor after 004_alert_sheet.sql and 004_nba.sql. Safe to run again.
--
-- revs: every pass, the reverse middles the engine scored (NO on a lower strike plus YES on a higher one, both
-- lose on a final in the hole between them), best first, same shape as mids. The Desk screen reads it.
-- held: the open positions you had on this game's total when it was priced, with the sell-or-hold verdict and
-- the best pairing at that moment, the same block the push carried.
-- Until this runs the watcher writes the row without these two columns and prints one line saying so.
alter table suggestions add column if not exists revs jsonb;
alter table suggestions add column if not exists held jsonb;
