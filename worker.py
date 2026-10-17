"""Halftime Desk always-on worker (Railway). Same Desk as watch.py, run in a loop that never sleeps through a half.

Pace:
  5 s    any game in Q2 under 5:00, at the half, or early Q3
  60 s   any game live, or a kickoff within 20 minutes
  5 min  nothing going on
Portfolio sync every 10 minutes while games are live, every 30 otherwise.

State lives in Supabase (desk_state, id 'worker') so a redeploy or restart picks up where it left off, with
every alert slot already pushed still marked. The GitHub Actions watcher can keep running as a backup: before
either one pushes, it claims the game's slot in the alerts table, so a push never goes out twice.

Nothing here places, cancels or changes an order.

Env: SUPABASE_URL, SUPABASE_SECRET_KEY, NTFY_TOPIC, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY (the last two optional).
"""
import os, sys, time, json, signal, datetime as dt
import watch, store, portfolio

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
    store.write('desk_state', [dict(id=STATE_ID, state=state, last_beat=now, note=note, updated_at=now)], on_conflict='id')


def pace(desk, now=None):
    """Seconds to sleep after this pass, from what the pass saw."""
    ph = desk.phases or {}
    if ph.get('approaching') or ph.get('half') or ph.get('early3'):
        return FAST
    if ph.get('live'):
        return LIVE
    if desk.next_kick:
        now = now or dt.datetime.now(dt.timezone.utc)
        try:
            kick = dt.datetime.fromisoformat(desk.next_kick.replace('Z', '+00:00'))
            if (kick - now).total_seconds() < 20 * 60:
                return LIVE
        except Exception:
            pass
    return IDLE


def main():
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    if not store.enabled():
        sys.exit('worker: SUPABASE_URL and SUPABASE_SECRET_KEY are required (state lives in Supabase)')
    cfg = watch.load_json(watch.CONFIG_PATH, {})
    desk = watch.Desk(cfg, load_state())
    print(f"worker up: {len(desk.state.get('games', {}))} games in state, ntfy {'on' if os.environ.get('NTFY_TOPIC') else 'OFF'}, "
          f"kalshi sync {'on' if portfolio.enabled() else 'off'}", flush=True)
    last_sync, passes = 0.0, 0
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
        sync_every = 600 if (ph.get('live') or wait == FAST) else 1800
        if portfolio.enabled() and time.time() - last_sync > sync_every:
            last_sync = time.time()
            try:
                portfolio.sync()
            except Exception as e:
                print(f'portfolio sync failed: {e}', flush=True)
        while not _stop and time.time() - started < wait:
            time.sleep(1)
    save_state(desk.state, 'stopped')
    print('worker stopped', flush=True)


if __name__ == '__main__':
    main()
