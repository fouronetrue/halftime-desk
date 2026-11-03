-- Halftime Desk, Nov 3 2026: college basketball.
-- Run once in the Supabase SQL Editor (outside a game window). Safe to run again.
--
-- The games table only accepted 'nfl', 'cfb' and 'nba'. Until this runs, every college basketball games row the
-- watcher sends is rejected (the watcher prints one line per pass and keeps going), so the app shows no college
-- basketball games and their suggestions, alerts and results rows have no games row to hang off. Nothing else
-- changes: the other tables' sport column has no check.
alter table games drop constraint if exists games_sport_check;
alter table games add constraint games_sport_check check (sport in ('nfl', 'cfb', 'nba', 'cbb'));
