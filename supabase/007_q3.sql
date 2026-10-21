-- Halftime Desk, Oct 21 2026: the NBA's second window, the end of the third quarter.
-- Run once in the Supabase SQL Editor after 006_flickers.sql. Safe to run again.
--
-- An NBA game now gets two pushes: the half (slot 'half') and the break before the fourth (slot 'q3', phases
-- q3end and early4 in suggestions and quote_snapshots; their half_away / half_home hold the end-of-third score the
-- row was priced at). The final grades both on the game's results row: the q3_ columns mirror the halftime ones.
-- Until this runs, the watcher writes the results row without them and prints one line saying so; pushes, the
-- CSV and the halftime grades are unaffected.
alter table results add column if not exists q3_score text;
alter table results add column if not exists q3_fair numeric(6,1);
alter table results add column if not exists q3_mkt numeric(6,1);
alter table results add column if not exists q3_n_plays int;
alter table results add column if not exists q3_plays_cost numeric(10,2);
alter table results add column if not exists q3_plays_pnl numeric(10,2);
alter table results add column if not exists q3_mid_pnl numeric(10,2);
alter table results add column if not exists q3_plays text;
alter table results add column if not exists q3_rest_mid text;
alter table results add column if not exists q3_rest_mid_pnl numeric(10,2);
alter table results add column if not exists sheet_q3 jsonb;
alter table results add column if not exists flickers_q3 jsonb;
