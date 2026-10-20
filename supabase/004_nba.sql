-- Halftime Desk, Oct 20 2026: NBA.
-- Run once in the Supabase SQL Editor after 003_live_score.sql. Safe to run again.
--
-- The games table only accepted 'nfl' and 'cfb'. Until this runs, every NBA games row the watcher sends is
-- rejected (the watcher prints one line per pass and keeps going), so the app shows no NBA games and the
-- suggestions, alerts and results rows for them have no games row to hang off. Nothing else changes.
alter table games drop constraint if exists games_sport_check;
alter table games add constraint games_sport_check check (sport in ('nfl', 'cfb', 'nba'));
