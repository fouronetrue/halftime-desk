-- Halftime Desk week 2: worker state, live scores on games, and read access for the app.
-- Run once in the Supabase SQL Editor after schema.sql. Safe to run again.

-- The always-on worker keeps its state here (the GitHub Actions watcher keeps using state.json),
-- and stamps last_beat on every pass so the app can show whether the worker is alive.
create table if not exists desk_state (
  id         text primary key,                         -- 'worker'
  state      jsonb not null default '{}'::jsonb,
  last_beat  timestamptz,
  note       text,                                     -- one line: what the last pass saw
  updated_at timestamptz not null default now()
);
alter table desk_state enable row level security;

-- Live score and clock for the Today screen.
alter table games add column if not exists away_score int;
alter table games add column if not exists home_score int;
alter table games add column if not exists period     int;
alter table games add column if not exists clock      text;
alter table games add column if not exists detail     text;   -- ESPN's short status, "Half", "8:12 - 3rd"

-- Read access for the app. Sign-ups get turned off in the dashboard, so the only signed-in users are the
-- ones you add by hand. Anyone else (including someone holding the publishable key) sees nothing.
-- Nothing here lets the app write; every write still goes through the worker's secret key.
do $$
declare t text;
begin
  foreach t in array array['games','quote_snapshots','suggestions','alerts','bets','positions',
                           'portfolio_snapshots','results','desk_state'] loop
    execute format('drop policy if exists "signed in can read" on %I', t);
    execute format('create policy "signed in can read" on %I for select to authenticated using (true)', t);
  end loop;
end $$;
