-- Halftime Desk, Oct 25 2026: the weather read at the half and the mismatch lane's shadow call, on every
-- priced row. Run once in the Supabase SQL Editor after 013_app_auto.sql. Safe to run again.
--
-- weather: the venue, roof, temperature, precipitation, wind, whether it counted as bad weather and the
--   haircut applied to the model's second-half mean (NFL: -1 in rain, snow or 16+ mph wind outdoors; tail study,
--   claude/tail-study-oct24.md).
-- shot: in a 28+ point college game, the sides a narrowed ladder (width 0.87) would take at 80c or more,
--   logged and shown as a SHOT line, graded as a what-if, never a play until config mismatch.cfb.mode is live.
-- Until this runs the watcher writes the row without the columns and prints one line saying so.
alter table suggestions add column if not exists weather jsonb;
alter table suggestions add column if not exists shot jsonb;
