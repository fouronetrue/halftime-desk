-- Halftime Desk, Oct 23 2026: auto orders (trade.py) and the kill switch.
-- Run once in the Supabase SQL Editor after 010_spot.sql. Safe to run again.
--
-- orders: every order the executor planned, one row per leg. In shadow mode nothing is sent and the row says
-- whether the ladder reached the price (status touched, touched_at, touch_phase, touch_s seconds after the
-- first look at the break); in live mode it carries Kalshi's order id, status and fill count. pnl is graded at
-- the final for touched (shadow) and filled (live) rows. The Record screen and `python trade.py --readout` read it.
-- control: one row, id 'trade'. kill true stops every send and cancels what is resting; the Settings toggle
-- writes it, and the worker reads it before every order.
-- Until this runs the worker prints one line saying the table is missing and records nothing; pushes are unaffected.
create table if not exists orders (
  client_order_id text primary key,
  created_at timestamptz not null,
  game_id text not null,
  sport text,
  game text,
  date_et date,
  event_ticker text,
  market_ticker text,
  strike numeric,
  side text,                 -- yes (Over) or no (Under)
  action text,               -- buy
  kind text,                 -- rest (a resting limit, maker) or take (immediate-or-cancel at the ask)
  stage text,                -- half or q3
  price_c integer,
  count integer,
  cost numeric,
  expire_at timestamptz,
  reason text,               -- rest_mid, rest_mid wide, ladder, single, play_mid
  pair text,                 -- the middle the leg belongs to, e.g. 210.5/216.5
  mode text,                 -- shadow or live
  status text,               -- planned, sent, resting, touched, filled, partial, cancelled, expired, rejected, skipped
  kalshi_order_id text,
  sent_at timestamptz,
  filled_count numeric,
  fill_price_c numeric,
  filled_at timestamptz,
  touched_at timestamptz,
  touch_phase text,
  touch_s integer,
  pnl numeric,
  graded_at timestamptz,
  final_total integer,
  note text
);
create index if not exists orders_game on orders (game_id);
create index if not exists orders_date on orders (date_et);
alter table orders enable row level security;

create table if not exists control (
  id text primary key,
  kill boolean not null default false,
  note text,
  updated_at timestamptz
);
insert into control (id, kill, note, updated_at) values ('trade', false, 'auto orders: kill true stops every send', now())
  on conflict (id) do nothing;
alter table control enable row level security;
