"""Halftime Desk always-on worker (Railway). Same Desk as watch.py, run in a loop that never sleeps through a half.

Pace:
  5 s    any game in Q2 under 5:00, at the half, or early Q3
  60 s   any game live, or a kickoff within 3 hours (keeps the pregame Kalshi market fresh)
  5 min  nothing going on
Portfolio sync every 2 minutes while anything is live or a kickoff is within 3 hours, every 30 otherwise, and a
held-position check (held.py) once a minute in that same window: a MIDDLE OPEN push when a total you own can be
paired cheaply enough, and the positions handed to the desk so the half push can say what to do with them.

State lives in Supabase (desk_state, id 'worker') so a redeploy or restart picks up where it left off, with
every alert slot already pushed still marked. The GitHub Actions watcher can keep running as a backup: before
either one pushes, it claims the game's slot in the alerts table, so a push never goes out twice.

Auto orders (trade.py) are planned here and nowhere else: with an "auto" block in config.json the worker records
what it would send at every break (shadow mode), and sends only in live mode with TRADE_ENABLED=1, the trade
key in this service's variables and the kill switch off. The GitHub Actions backup never carries the trade key.

Env: SUPABASE_URL, SUPABASE_SECRET_KEY, NTFY_TOPIC, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY (the last two optional),
     TRADE_ENABLED, KALSHI_TRADE_KEY_ID, KALSHI_TRADE_PRIVATE_KEY (live orders only).
"""
import os, sys, time, json, signal, datetime as dt
import watch, store, portfolio, held, trade

FAST, LIVE, IDLE = 5, 60, 300
STATE_ID = 'worker'
_stop = False


def _on_term(signum, frame):
    global _stop
    _stop = True
    print(f'signal {signum}: finishing the pass and saving state')


def load_state():
    rows = store.read('desk_state', {'select': 'state', 'id': f'eq.{STATE_ID}'})
    if rows and isinstance(rows[0].get('state'), dict):
        return rows[0]['state']
    # first boot: start from the repo's state.json so games already pushed by the backup are not pushed again
    return watch.load_json(watch.STATE_PATH, {})


def save_state(state, note):
    now = watch.now_iso()
    # a second, small row the Today screen reads: each upcoming game's live Kalshi total, keyed by game id
    pregame = {gid: r['mkt'] for gid, r in (state.get('games') or {}).items() if r.get('phase') == 'pre' and r.get('mkt')}
    store.write('desk_state', [dict(id=STATE_ID, state=state, last_beat=now, note=note, updated_at=now),
                               dict(id='pregame', state=pregame, last_beat=now, note=f'{len(pregame)} games', updated_at=now)], on_conflict='id')


def pace(desk, now=None):
    """Seconds to sleep after this pass, from what the pass saw."""
    ph = desk.phases or {}
    if ph.get('approaching') or ph.get('half') or ph.get('early3') or ph.get('approaching3') or ph.get('q3end') or ph.get('early4'):
        return FAST
    if ph.get('live'):
        return LIVE
    if desk.next_kick:
        now = now or dt.datetime.now(dt.timezone.utc)
        try:
            kick = dt.datetime.fromisoformat(desk.next_kick.replace('Z', '+00:00'))
            if (kick - now).total_seconds() < 3 * 3600:
                return LIVE
        except Exception:
            pass
    return IDLE


def boot_checks():
    """One line per key at start, so a rotated or mistyped variable reads as a sentence in the deploy logs
    instead of a heartbeat that quietly stops (Oct 23: the Railway credential reset)."""
    ok, detail = store.check()
    print(f'supabase: ok, {detail}' if ok else
          f"supabase: FAILED ({detail}); check SUPABASE_URL and SUPABASE_SECRET_KEY in this service's variables, then Deploy", flush=True)
    if portfolio.enabled():
        try:
            b = portfolio.pull_balance(portfolio.load_key())
            print(f"kalshi: ok, balance ${b['balance']:.2f}" if b.get('balance') is not None else 'kalshi: ok', flush=True)
        except Exception as e:
            print(f'kalshi: FAILED ({str(e)[:160]}); check KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY (the whole PEM file), then Deploy', flush=True)
    else:
        print('kalshi: sync off (no KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY)', flush=True)
    print(f"ntfy: {'topic set' if os.environ.get('NTFY_TOPIC') else 'OFF, no NTFY_TOPIC'}; odds api: {'key set' if os.environ.get('ODDS_API_KEY') else 'no ODDS_API_KEY, book lines off'}", flush=True)


def main():
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    if not store.enabled():
        sys.exit('worker: SUPABASE_URL and SUPABASE_SECRET_KEY are required (state lives in Supabase)')
    boot_checks()
    cfg = watch.load_json(watch.CONFIG_PATH, {})
    desk = watch.Desk(cfg, load_state())
    trader = trade.Trader(cfg, desk.cfg['bankroll'])
    if trader.on:
        desk.trader = trader
    auto_note = (f"auto {trader.mode()} for {', '.join(trader.cfg.get('sports') or [])}"
                 + (f", {'ARMED' if trader.armed() else 'not armed'}" if trader.mode() == 'live' else '')) if trader.on else 'auto off'
    print(f"worker up: {len(desk.state.get('games', {}))} games in state, ntfy {'on' if os.environ.get('NTFY_TOPIC') else 'OFF'}, "
          f"kalshi sync {'on' if portfolio.enabled() else 'off'}, {auto_note}", flush=True)
    last_sync, last_held, last_refresh, passes = 0.0, 0.0, 0.0, 0
    killed = False
    while not _stop:
        started = time.time()
        desk._events = {}
        try:
            desk.run_pass()
        except Exception as e:   # one bad pass never kills the worker
            print(f'pass failed: {e}', flush=True)
        wait = pace(desk)
        ph = desk.phases or {}
        note = f"{sum(ph.values())} games: " + ', '.join(f'{k} {v}' for k, v in sorted(ph.items())) + f'; next pass {wait}s'
        save_state(desk.state, note)
        passes += 1
        if passes == 1 or wait == FAST or passes % 12 == 0:
            print(f'{watch.now_iso()} {note}', flush=True)
        sync_every = 120 if wait <= LIVE else 1800
        if portfolio.enabled() and time.time() - last_sync > sync_every:
            last_sync = time.time()
            try:
                portfolio.sync()
            except Exception as e:
                print(f'portfolio sync failed: {e}', flush=True)
        if desk.trader and trader.mode() == 'live' and wait <= LIVE and time.time() - last_refresh > 30:
            last_refresh = time.time()
            try:
                # the kill switch pulls every resting order once; while it stays on nothing new is sent (armed() is false)
                if trader.kill() and not killed:
                    for rec in desk.state.get('games', {}).values():
                        trader.cancel_game(rec, 'kill switch')
                    killed = True
                    print(f'{watch.now_iso()} kill switch on: resting orders cancelled', flush=True)
                elif not trader.kill():
                    killed = False
                for rec in desk.state.get('games', {}).values():
                    if any(st.get('open') for st in (rec.get('auto') or {}).values()):
                        trader.refresh(rec)
            except Exception as e:
                print(f'order refresh failed: {e}', flush=True)
        if wait <= LIVE and time.time() - last_held > 60:
            last_held = time.time()
            try:
                for title, _ in held.check(desk):
                    print(f'{watch.now_iso()} pushed {title}', flush=True)
                desk.holdings = held.by_event(held.holdings())   # what the half push prices as YOU HOLD
                summary = held.summary(desk)   # what Today shows under Your totals
                store.write('desk_state', [dict(id='held', state=summary, last_beat=watch.now_iso(), note=f'{len(summary)} events', updated_at=watch.now_iso())], on_conflict='id')
            except Exception as e:   # a bad look at the ledger never touches the watch
                print(f'held check failed: {e}', flush=True)
        while not _stop and time.time() - started < wait:
            time.sleep(1)
    save_state(desk.state, 'stopped')
    print('worker stopped', flush=True)


if __name__ == '__main__':
    main()
