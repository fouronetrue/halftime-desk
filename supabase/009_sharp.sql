-- Halftime Desk, Oct 22 2026: the sharp second-half line at the half and the center the ladder was shaped around.
-- Run once in the Supabase SQL Editor after 008_pre_books.sql. Safe to run again.
--
-- With ODDS_API_KEY the watcher reads the sharp second-half total (Pinnacle, else the median of the books) once
-- at the half, one credit a game, and centers the ladder between the model and that line (config
-- sharp_model_pct). These columns keep, on every priced row, the model's own number, the center used and where
-- it came from (sharp, kalshi, or none), and the sharp line itself, so the model-versus-market study runs live.
alter table suggestions add column if not exists mu_model numeric(6,2);
alter table suggestions add column if not exists center numeric(6,2);
alter table suggestions add column if not exists center_src text;
alter table suggestions add column if not exists sharp_2h numeric(6,1);
