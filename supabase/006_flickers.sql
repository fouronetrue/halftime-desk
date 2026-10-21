-- Halftime Desk, Oct 21 2026: everything that cleared the edge at any moment of a half, graded.
-- Run once in the Supabase SQL Editor after 005_reverse.sql. Safe to run again.
--
-- The push is a snapshot at the first look of the half; Today re-prices every few seconds, and a line can clear
-- the edge after the push (the ask dropped) and vanish again (someone took it). Every priced row is already in
-- the suggestions table, so at the final the watcher grades every line that cleared in any row, pushed or not,
-- and keeps the list here: when it first and last cleared, how many rows, best price and edge, what it would
-- have done. The Record screen reads it to answer "the bets that came and went, did they hit".
alter table results add column if not exists flickers jsonb;
