-- Halftime Desk, Oct 23 2026: the app reads the auto orders and the venue log, and flips the kill switch.
-- Run once in the Supabase SQL Editor after 012_venues.sql. Safe to run again.
--
-- Signed-in users (the ones added by hand in the dashboard; sign-ups are off) can read orders and venue_quotes,
-- and read and update the control row, which is what the kill switch on the Record screen writes. Nothing here
-- lets the app insert an order; every order still comes from the worker's trade key, when that is ever turned on.
drop policy if exists "signed in can read" on orders;
create policy "signed in can read" on orders for select to authenticated using (true);
drop policy if exists "signed in can read" on venue_quotes;
create policy "signed in can read" on venue_quotes for select to authenticated using (true);
drop policy if exists "signed in can read" on control;
create policy "signed in can read" on control for select to authenticated using (true);
drop policy if exists "signed in can flip" on control;
create policy "signed in can flip" on control for update to authenticated using (true) with check (true);
