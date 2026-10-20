-- Halftime Desk, Oct 19 2026 fixes: the live score on every priced row.
-- Run once in the Supabase SQL Editor after schema.sql and 002_week2.sql. Safe to run again.
--
-- Every suggestions row is priced off the halftime score. From this build the watcher stops writing rows the
-- moment the live score moves off it (claude/desk-issues-oct17.md, issue 3), and these two columns record
-- the live score it saw when it priced, so a row priced off a score that no longer existed can never hide.
-- Until this runs, the watcher writes the row without them and prints one line saying so.
alter table suggestions add column if not exists away_score int;
alter table suggestions add column if not exists home_score int;
