-- Halftime Desk, Oct 20 2026: every push carries its sheet, and the final grades what was pushed.
-- Run once in the Supabase SQL Editor after 003_live_score.sql. Safe to run again.
--
-- Before this, each watcher graded a sheet frozen at the moment it first saw the game, and both wrote the same
-- results row (last one won). The Railway worker and the GitHub backup see a game at different moments, so a
-- PLAY the worker pushed could be graded by the backup's empty sheet as +0 (ARI @ LAR, Oct 18: three winning
-- unders shown as +0). Now the push's sheet rides on its alerts row, settling grades the first PLAY push for
-- the game from here, and the Alerts screen grades every push on its own text.
alter table alerts add column if not exists sheet jsonb;
