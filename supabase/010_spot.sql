-- Halftime Desk, Oct 22 2026: the game-state label on every priced row.
-- Run once in the Supabase SQL Editor after 009_sharp.sql. Safe to run again.
--
-- spot: the label the model gives the half (blowout, favorite trailing, favorite chasing, no strong lean).
-- It left the push text in the rewrite of Oct 22 (it read as a lean next to a fair number that said
-- otherwise) and lives here instead, so the Record can still split the scorecard by spot.
-- Until this runs the watcher writes the row without the column and prints one line saying so.
alter table suggestions add column if not exists spot text;
