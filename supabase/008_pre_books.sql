-- Halftime Desk, Oct 22 2026: the sharp pregame line, every book's close and ESPN's number beside it.
-- Run once in the Supabase SQL Editor after 007_q3.sql. Safe to run again.
--
-- With ODDS_API_KEY on the worker, the pregame line comes from The Odds API (Pinnacle's close, else the median
-- across the US books) instead of ESPN's consensus; pre_source reads odds:pinnacle or odds:median5. This column
-- keeps every book's (home spread, total) pair and ESPN's under "espn", so the ESPN-vs-sharp gap and closing
-- line value on Sharp bets can be studied without another feed.
alter table games add column if not exists pre_books jsonb;
