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

Writes (Nov 8, after Supabase warned the project was spending its Disk IO budget): the state used to be one
jsonb row of about 0.8 MB (every game of the last ten days) rewritten on every pass, every 5 seconds around the
half, which is about 8 GB a day on a full Saturday into a free-tier database with half a gigabyte of memory. Now:
  every pass   a heartbeat on the 'worker' row (last_beat and the note; the state column is left alone, so its
               stored value is not rewritten)
  the state    written when something in it changed, at most once a minute (a change to the auto orders or the
               day's spend: on the pass it happens), and at least every 5 minutes. Fields every pass rewrites with
               nothing a restart needs (VOLATILE) are not a reason to write.
  finished     games (final and graded, or never priced) move to a second row, 'worker_archive', rewritten at most
               every 30 minutes, so the row written once a minute carries only the games still in play. A record
               leaves the 'worker' row only while the archive holds an identical copy of it.
  pregame row  when a price on it moves, or once a minute.
A restart loads both rows. What a crash between writes can lose is at most a minute of routine fields: the alert
slots are guarded by the alerts table, the orders by their client_order_id, and both are written as they happen.

Auto orders (trade.py) are planned here and nowhere else: with an "auto" block in config.json the worker records
what it would send at every break (the shadow planner, every sport in auto.sports). The pilot (auto.pilot) is the
only thing that sends: for the sports it lists, at pilot size, and only with TRADE_ENABLED=1, the trade key in
this service's variables, the kill switch off and its self-test passed in this process (two one-contract bids at
1c, posted, read back and cancelled; the worker runs it once the switches are on and every ten minutes until it
passes). The GitHub Actions backup never carries the trade key.

Env: SUPABASE_URL, SUPABASE_SECRET_KEY, NTFY_TOPIC, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY (the last two optional),
     TRADE_ENABLED, KALSHI_TRADE_KEY_ID, KALSHI_TRADE_PRIVATE_KEY (live orders only).
"""
import os, sys, time, json, signal, hashlib, datetime as dt
import watch, store, portfolio, held, trade

FAST, LIVE, IDLE = 5, 60, 300
STATE_ID, ARCHIVE_ID, PREGAME_ID = 'worker', 'worker_archive', 'pregame'
SAVE_GAP = 60        # seconds: the state is written at most this often for a routine change
SAVE_EVERY = 300     # seconds: and at least this often, whatever changed
ARCHIVE_GAP = 1800   # seconds between rewrites of the archive row
PREGAME_EVERY = 60   # seconds: the pregame row at least this often, so its read times stay fresh on Today
RETRY_GAP = 30       # seconds after a failed state write before the next try (a down database is not hammered)
FEE_CHECK = 6 * 3600 # seconds between reads of Kalshi's fee record for the total series (watch.Desk.fee_check)
PILOT_CHECK = 600    # seconds between tries of the pilot's self-test while it has not passed (trade.Trader.preflight)
# Game fields rewritten on (nearly) every pass that nothing needs after a restart: the next pass reads them again.
# A change to these alone is not a reason to write the state. (The pregame line's own 'at' stamp is the same
# kind of field: see durable_view.) A field missing here only means more writes, never a lost one.
VOLATILE = ('last_seen', 'mkt', 'poly', 'pre_ladder', 'last_eval', 'odds_asked', 'pre_asked')
# Game fields written on the pass they change: the auto orders (a live order's open list is what the refresh and
# the kill switch work from) and the marks that count a play against the day's spend (with day_spend itself).
URGENT = ('auto', 'counted_day', 'counted_day_q3')
_stop = False


def _on_term(signum, frame):
    global _stop
    _stop = True
    print(f'signal {signum}: finishing the pass and saving state')


def load_state():
    """The 'worker' row's state with the archive row's finished games folded back in (the 'worker' row wins a
    game both hold: it is the newer copy). With neither row there yet, the repo's state.json."""
    rows = store.read('desk_state', {'select': 'id,state', 'id': f'in.({STATE_ID},{ARCHIVE_ID})'})
    by_id = {r.get('id'): r.get('state') for r in rows if isinstance(r, dict)}
    state, archive = by_id.get(STATE_ID), by_id.get(ARCHIVE_ID)
    if isinstance(state, dict) and state:
        if isinstance(archive, dict) and isinstance(archive.get('games'), dict) and archive['games']:
            games = dict(archive['games'])
            games.update(state.get('games') or {})
            state = dict(state, games=games)
        return state
    # first boot: start from the repo's state.json so games already pushed by the backup are not pushed again
    return watch.load_json(watch.STATE_PATH, {})


def _fp(obj):
    """A short fingerprint of a JSON-able object, the same whatever order its keys were added in."""
    try:
        text = json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)
    except TypeError:   # keys of mixed types cannot be sorted; insertion order is stable from pass to pass
        text = json.dumps(obj, separators=(',', ':'), default=str)
    return hashlib.blake2b(text.encode(), digest_size=16).hexdigest()


def durable_view(rec):
    """A game record without the fields every pass rewrites (VOLATILE, and the pregame line's read stamp,
    which capture_pregame renews on every pregame pass)."""
    d = {k: v for k, v in rec.items() if k not in VOLATILE}
    pre = d.get('pre')
    if isinstance(pre, dict) and 'at' in pre:
        d['pre'] = {k: v for k, v in pre.items() if k != 'at'}
    return d


def finished(rec):
    """Final, and nothing left to grade (graded, or never priced so watch.settle has nothing to do). Such a
    record only changes again if ESPN reopens the game, and then its fingerprint moves and it is written in the
    'worker' row on that pass."""
    if rec.get('phase') != 'post':
        return False
    return bool(rec.get('settled')) or not any(rec.get(k) for k in ('half_at', 'half_at_q3', 'slots', 'sheet', 'sheet_q3'))


class Saver:
    """When and how the worker's state reaches Supabase (the module docstring has the rules and the why)."""

    def __init__(self):
        self.full_at = None              # time of the last state write that went through (None: none yet)
        self.fail_at = None              # time of the last one that did not
        self.durable = self.urgent = None
        self.archive_at = None           # time of the last archive row write
        self.archived = None             # game id -> fingerprint of the record as the archive row holds it (None: not
                                         # written by this process yet, so whatever the row holds is rewritten first)
        self.pre_key, self.pre_at = None, 0.0
        self.saves = self.beats = 0      # counts for the log line

    @staticmethod
    def digests(state):
        """(fingerprint per game, fingerprint of everything a restart needs, fingerprint of the urgent part)."""
        games = state.get('games') or {}
        fps = {gid: _fp(durable_view(rec)) for gid, rec in games.items()}
        top = {k: v for k, v in state.items() if k != 'games'}
        durable = _fp([top, sorted(fps.items())])
        urgent = _fp([state.get('day_spend'), sorted((gid, _fp({k: rec[k] for k in URGENT if k in rec}))
                                                     for gid, rec in games.items() if any(k in rec for k in URGENT))])
        return fps, durable, urgent

    def after_pass(self, state, note, now=None):
        """Once per pass: the state when it is due (that write carries the heartbeat), the heartbeat alone
        otherwise, and the pregame row when it moved."""
        now = time.time() if now is None else now
        fps, durable, urgent = self.digests(state)
        due = (self.full_at is None or urgent != self.urgent or now - self.full_at >= SAVE_EVERY
               or (durable != self.durable and now - self.full_at >= SAVE_GAP))
        if due and (self.fail_at is None or now - self.fail_at >= RETRY_GAP):
            self.save(state, note, now, (fps, durable, urgent))
        else:
            self.beat(note)
        self.pregame(state, now)

    def beat(self, note):
        """last_beat and the note on the 'worker' row. The row's state is not in the request, so the upsert
        leaves the stored value as it is (no rewrite of the big column)."""
        stamp = watch.now_iso()
        if store.write('desk_state', [dict(id=STATE_ID, last_beat=stamp, note=note, updated_at=stamp)], on_conflict='id'):
            self.beats += 1

    def save(self, state, note, now=None, digests=None, final=False):
        """Write the state now. The archive row goes in the same request (one statement, so both land or
        neither) when its finished games are behind and it has been ARCHIVE_GAP since its last write, or on
        the final write. True when it went through."""
        now = time.time() if now is None else now
        fps, durable, urgent = digests or self.digests(state)
        games = state.get('games') or {}
        want = {gid: fps[gid] for gid, rec in games.items() if finished(rec)}
        write_archive = ((self.archived is None or want != self.archived)
                         and (final or self.archive_at is None or now - self.archive_at >= ARCHIVE_GAP))
        archived = want if write_archive else (self.archived or {})
        # a game stays in the 'worker' row unless the archive row holds this exact record
        hot = {gid: rec for gid, rec in games.items() if archived.get(gid) != fps[gid]}
        stamp = watch.now_iso()
        rows = [dict(id=STATE_ID, state=dict(state, games=hot), last_beat=stamp, note=note, updated_at=stamp)]
        if write_archive:
            rows.append(dict(id=ARCHIVE_ID, state={'games': {gid: games[gid] for gid in archived}}, last_beat=stamp,
                             note=f'{len(archived)} finished games', updated_at=stamp))
        if not store.write('desk_state', rows, on_conflict='id'):
            self.fail_at = now
            return False
        self.full_at, self.durable, self.urgent, self.saves = now, durable, urgent, self.saves + 1
        if write_archive:
            self.archived, self.archive_at = archived, now
        return True

    def pregame(self, state, now):
        """The small row the Today screen reads: each upcoming game's live Kalshi total, keyed by game id.
        Written when a line or price on it moves, or PREGAME_EVERY seconds after the last write."""
        pre = {gid: r['mkt'] for gid, r in (state.get('games') or {}).items() if r.get('phase') == 'pre' and r.get('mkt')}
        key = _fp({gid: {k: v for k, v in m.items() if k != 'at'} if isinstance(m, dict) else m for gid, m in pre.items()})
        if key == self.pre_key and now - self.pre_at < PREGAME_EVERY:
            return
        stamp = watch.now_iso()
        if store.write('desk_state', [dict(id=PREGAME_ID, state=pre, last_beat=stamp, note=f'{len(pre)} games', updated_at=stamp)], on_conflict='id'):
            self.pre_key, self.pre_at = key, now


def save_state(state, note, saver=None):
    """Write the whole state now, the archive row too when it is behind: the final write at a stop."""
    return (saver or Saver()).save(state, note, final=True)


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
    print(f"worker up: {len(desk.state.get('games', {}))} games in state, ntfy {'on' if os.environ.get('NTFY_TOPIC') else 'OFF'}, "
          f"kalshi sync {'on' if portfolio.enabled() else 'off'}, {trader.status_line()}", flush=True)
    last_sync, last_held, last_refresh, last_fees, last_pilot, passes = 0.0, 0.0, 0.0, 0.0, 0.0, 0
    killed = False
    saver = Saver()
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
        try:
            saver.after_pass(desk.state, note)
        except Exception as e:   # a failed save never stops the watch; the next pass tries again
            print(f'state save failed: {e}', flush=True)
        passes += 1
        if passes == 1 or passes % 12 == 0:
            # how often the big write happened, for the deploy logs: state writes and heartbeats since the last line
            print(f'{watch.now_iso()} {note}; state written {saver.saves}x, heartbeat {saver.beats}x since the last line', flush=True)
            saver.saves = saver.beats = 0
        elif wait == FAST:
            print(f'{watch.now_iso()} {note}', flush=True)
        if wait != FAST and time.time() - last_fees > FEE_CHECK:
            # what Kalshi charges in the total series the desk prices: a push the day a series moves onto maker fees.
            # Never around a break: four reads of a slow API are not worth one late look at a half.
            last_fees = time.time()
            try:
                desk.fee_check()
                fees = desk.state.get('fees') or {}
                # one line for the deploy log, so "no push" can be told from "not read"
                print(f"{watch.now_iso()} fees: " + (', '.join(f"{k} {v.get('fee_type')} x{v.get('fee_multiplier')}" for k, v in sorted(fees.items())) or 'no series read'), flush=True)
            except Exception as e:   # a look at the fee record never touches the watch
                print(f'fee check failed: {e}', flush=True)
        sync_every = 120 if wait <= LIVE else 1800
        if portfolio.enabled() and time.time() - last_sync > sync_every:
            last_sync = time.time()
            try:
                portfolio.sync()
            except Exception as e:
                print(f'portfolio sync failed: {e}', flush=True)
        if desk.trader and trader.ready() and not (trader.verified or {}).get('ok') and time.time() - last_pilot > PILOT_CHECK:
            # the pilot's self-test: once every switch is on, and every ten minutes until it passes. Two one-contract
            # bids at 1c go up and come down; the result goes to the phone once per distinct answer, not per restart.
            last_pilot = time.time()
            try:
                res = trader.preflight([e for sp in trader.pilot_sports() for e in desk.events(sp, 'total')])
                title, body, pri, sig = trader.preflight_push(res)
                print(f"{watch.now_iso()} pilot self-test: {'passed' if res.get('ok') else 'waiting' if res.get('wait') else 'FAILED'} ({res.get('step')}"
                      + (f": {res.get('error')}" if res.get('error') else '') + f"); {trader.status_line()}", flush=True)
                if not res.get('wait') and (desk.state.get('pilot') or {}).get('sig') != sig:
                    watch.notify.push(title, body, pri, 'robot')
                    desk.state['pilot'] = dict(sig=sig, at=watch.now_iso())
            except Exception as e:   # the self-test never touches the watch, and a test that could not run is not a pass
                print(f'pilot self-test failed to run: {e}', flush=True)
        if desk.trader and trader.pilot_sports() and trade.key_present() and wait <= LIVE and time.time() - last_refresh > 30:
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
                    if trader.has_live_open(rec):
                        trader.refresh(rec)
            except Exception as e:
                print(f'order refresh failed: {e}', flush=True)
        if desk.trader:
            for title, body, pri in trader.drain():   # what the pilot has to say: a refusal, a night's summary
                try:
                    watch.notify.push(title, body, pri, 'robot')
                    print(f'{watch.now_iso()} pushed {title}', flush=True)
                except Exception as e:
                    print(f'pilot push failed: {e}', flush=True)
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
    print('worker stopped' if saver.save(desk.state, 'stopped', final=True) else 'worker stopped (the final state write failed)', flush=True)


if __name__ == '__main__':
    main()
