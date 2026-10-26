"""Halftime Desk watcher.
Every run: read ESPN scoreboards, capture pregame lines for games not yet kicked off, and for games at the half
(or early third quarter, while the score is still the halftime score) pull Kalshi's full-game total markets,
price every strike with the second-half model, and push a notification when a single leg or a middle clears the
edge. A game is priced only off a line captured before kickoff (its own record, or the games table in Supabase
when its state was lost); nothing read from a feed after kickoff is ever used as the pregame line. Keeps polling
inside the run while any game is approaching or at the half, so a 5-minute cron still sees the whole halftime
window.

Usage:
  python watch.py                 # one pass, then keeps polling while a halftime is live (up to max_poll_minutes)
  python watch.py --once          # single pass, no in-run polling
  python watch.py --fixtures DIR  # run against saved JSON instead of the network (tests)
"""
import os, sys, json, csv, time, argparse, datetime as dt
import engine, feeds, notify, store, weather

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH, STATE_PATH, LOG_PATH = os.path.join(HERE, 'config.json'), os.path.join(HERE, 'state.json'), os.path.join(HERE, 'log', 'halftime_log.csv')
RESULTS_PATH = os.path.join(HERE, 'log', 'results.csv')
MIDS_KEPT = 40   # middles stored per priced row (plus any more that clear): all 230-odd ran 120 KB a row
RESULTS_COLUMNS = ['settled_utc', 'sport', 'game', 'date', 'half', 'total', 'home_spread', 'fair', 'mkt', 'final', 'final_total',
                   'model_err', 'mkt_err', 'n_plays', 'plays_cost', 'plays_pnl', 'mid_pnl', 'plays', 'rest_mid', 'rest_mid_pnl',
                   # the NBA's second window, the end of the third, graded the same way (supabase/007_q3.sql adds the columns)
                   'q3_score', 'q3_fair', 'q3_mkt', 'q3_n_plays', 'q3_plays_cost', 'q3_plays_pnl', 'q3_mid_pnl', 'q3_plays', 'q3_rest_mid', 'q3_rest_mid_pnl']
DEFAULTS = dict(bankroll=3000, risk_pct=2.5, cost_pct=7.5, margin_c=3, trust_pct=50, order='taker', sports=['nfl', 'cfb'],
                # Sports whose pushes lead with the middle and always carry the resting middles (tight and wide), and
                # how far from fair a resting strike may sit: Kalshi's NBA ladder runs every 2 points and the second
                # half has a 13.6-point sd, so 6.5 points of room gives a 4-wide and an 8-wide window to post.
                middle_focus=['nba'], rest_near_pts={'nba': 6.5},
                read_push={'nfl': 'default', 'cfb': 'default'}, poll_seconds=75, max_poll_minutes=22, keep_days=10, min_price_c=15, max_price_c=85, day_cost_pct=20,
                mid_loss_cap=None,
                # Per sport, the weight the model's own second-half number keeps against the market's center (Kalshi's
                # implied total at the half minus the first-half points). Football keeps its own center (100). The NBA
                # model's center never beats the market, so it keeps 25 and the ladder is shaped around the market's number.
                center_model_pct={'nba': 25},
                # Per sport, the weight the model keeps when a sharp second-half line is in hand at the half (The Odds
                # API, Pinnacle else the median of the books, one credit a game). On 944 NFL halftimes the model and
                # DraftKings' 2H line are a dead heat and agree within a point in 99 percent of games, so 50 halves the
                # model's own misses and keeps the view. On 873 CFB halftimes the model beats the book's 2H line (closer
                # 472 to 401, best blend 0.9), so it keeps 80. On 3,579 NBA halftimes the book's line beats the model at
                # every weight (closer 2,028 to 1,551, best blend 0.0), so the NBA keeps 0: the line is the center, the
                # model the shape. Without a sharp line the NBA falls back to Kalshi's center at center_model_pct.
                sharp_model_pct={'nfl': 50, 'cfb': 80, 'nba': 0})
CENTER_2H_RANGE = {'nba': (70, 160), 'nfl': (6, 60), 'cfb': (8, 90)}   # a center outside this (per sport, second-half points) is a bad read and is ignored
CENTER_Q4_RANGE = {'nba': (30, 95)}    # the same for the points left at the end of the third (a 4th quarter plus the overtime chance)


def send_push(title, body, priority='default', tags='football', url=None):
    """notify.push with the market link; a stand-in push without the url argument (the tests') still works."""
    try:
        return notify.push(title, body, priority=priority, tags=tags, url=url)
    except TypeError:
        return notify.push(title, body, priority=priority, tags=tags)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class Desk:
    def __init__(self, config, state, fixtures=None):
        self.cfg = {**DEFAULTS, **config}
        self.state = state
        self.state.setdefault('games', {})
        self.fixtures = fixtures
        self._events = {}
        self.pushed = []
        self._pre_last = {}   # game id -> (quote key, time written) for the pregame line history
        self._db_evals = {}   # game id -> (quote key, time written): skip identical priced rows inside 30 s
        self._db_games = {}   # game id -> (row hash, time sent), so Supabase only hears about games that changed
        self.holdings = {}   # event ticker -> open positions on that total (held.holdings rows), refreshed by the worker once a minute
        self._odds_rows = {}   # sport -> the Odds API's upcoming games (feeds.parse_odds_api rows), refreshed by odds_lines()
        self.trader = None   # trade.Trader when this process plans auto orders (the worker; a plain run never does)
        self._poly = {}      # game id -> time of the last Polymarket read, so a break reads it every 15 s, not every pass
        self._venue_ok = True   # False after the first failed venue_quotes write (table missing), so the log is not spammed

    # ---- feeds (fixture-aware) ----
    def games(self, sport):
        if self.fixtures:
            return feeds.parse_espn(load_json(os.path.join(self.fixtures, f'espn_{sport}.json'), {}), sport)
        return feeds.espn_games(sport)

    def events(self, sport, kind):
        key = (sport, kind)
        if key not in self._events:
            series = feeds.SERIES[sport][kind]
            if self.fixtures:
                self._events[key] = load_json(os.path.join(self.fixtures, f'kalshi_{series}.json'), {}).get('events', [])
            else:
                try:
                    self._events[key] = feeds.kalshi_events(series)
                except Exception as e:
                    print(f'kalshi {series} unavailable: {e}')
                    self._events[key] = []
        return self._events[key]

    def odds_lines(self, sport, games):
        """Refresh the Odds API's lines for a sport when a kickoff is near, inside the free quota. One call returns
        every upcoming game of the sport, so the question is only how often: once when a game is within three
        hours (and the last call is older than 150 minutes) and once more inside the last 25 minutes before a
        kickoff (last call older than 20 minutes), the closing read. Two credits a call, 500 free a month; under
        40 left only the closing read runs, under 10 nothing does, and a sport gets at most 12 calls a day.
        Off without ODDS_API_KEY (the GitHub backup never carries it, so the quota is spent once) and on fixtures."""
        key = (os.environ.get('ODDS_API_KEY') or '').strip()
        if not key or self.fixtures or sport not in feeds.ODDS_SPORT:
            return
        now = time.time()
        soon = close = False
        for g in games:
            if feeds.phase(g) != 'pre' or not g.get('start_utc'):
                continue
            try:
                left = dt.datetime.fromisoformat(g['start_utc'].replace('Z', '+00:00')).timestamp() - now
            except Exception:
                continue
            soon = soon or 0 <= left <= 3 * 3600
            close = close or 0 <= left <= 25 * 60
        if not soon:
            return
        st = self.state.setdefault('odds_api', {})
        rec = st.setdefault(sport, {})
        last, day = float(rec.get('at') or 0), dt.datetime.now(feeds.ET).strftime('%Y-%m-%d')
        if rec.get('day') != day:
            rec.update(day=day, calls=0)
        remaining = st.get('remaining')
        want = (close and now - last > 20 * 60) or (now - last > 150 * 60)
        if not want or rec.get('calls', 0) >= 12 or now - float(rec.get('failed_at') or 0) < 20 * 60:
            return
        if remaining is not None and (remaining < 10 or (remaining < 40 and not close)):
            return
        try:
            rows, usage = feeds.odds_api_lines(sport, key)
        except Exception as e:
            rec['failed_at'] = now
            print(f'odds api {sport}: {e}')
            return
        self._odds_rows[sport] = rows
        rec.update(at=now, calls=rec.get('calls', 0) + 1, games=len(rows))
        if usage:
            st.update(remaining=usage.get('remaining'), used=usage.get('used'), usage_at=now_iso())
        pin = sum(1 for r in rows if r['source'] == 'pinnacle')
        print(f"odds api {sport}: {len(rows)} games ({pin} with Pinnacle), {'closing read' if close else 'early read'}, "
              f"{usage.get('remaining', '?')} credits left this month")

    # ---- bankroll from the live balance ----
    def sync_bankroll(self):
        """The bankroll every cap is a percentage of, from Kalshi instead of a number typed into config.json
        (Nick, Oct 23). The rule: the first time this runs with no stored bankroll, and every Tuesday after that
        (the unit-reset day), the bankroll becomes the newest portfolio snapshot's cash plus positions at market,
        rounded to the dollar, if that snapshot is under 36 hours old and the number is at least $500. Stored in
        desk_state (id 'bankroll') so the worker and the GitHub backup size alike; config.json is the seed and the
        fallback. Off with "bankroll_auto": false in config.json. Checked at most once an hour."""
        if not store.enabled() or self.fixtures or self.cfg.get('bankroll_auto') is False:
            return
        now = time.time()
        if now - getattr(self, '_bank_checked', 0) < 3600:
            return
        self._bank_checked = now
        rows = store.read('desk_state', {'select': 'state,updated_at', 'id': 'eq.bankroll'})
        cur = rows[0].get('state') if rows and isinstance(rows[0].get('state'), dict) else None
        if cur and cur.get('bankroll'):
            self.cfg['bankroll'] = float(cur['bankroll'])
            if self.trader:
                self.trader.bank = self.cfg['bankroll']
        today = dt.datetime.now(feeds.ET)
        due = cur is None or (today.weekday() == 1 and (cur.get('set_on') or '') != today.strftime('%Y-%m-%d'))
        if not due:
            return
        snap = store.read('portfolio_snapshots', {'select': 'taken_at,balance,portfolio_value', 'order': 'taken_at.desc', 'limit': 1})
        if not snap:
            return
        s = snap[0]
        taken = dt.datetime.fromisoformat(str(s.get('taken_at')).replace('Z', '+00:00'))
        if (dt.datetime.now(dt.timezone.utc) - taken).total_seconds() > 36 * 3600:
            return
        bank = round(float(s.get('balance') or 0) + float(s.get('portfolio_value') or 0))
        if bank < 500:
            return
        prev = self.cfg.get('bankroll')
        state = dict(bankroll=bank, set_on=today.strftime('%Y-%m-%d'), set_at=now_iso(), balance=s.get('balance'), portfolio_value=s.get('portfolio_value'), prev=prev)
        if store.write('desk_state', [dict(id='bankroll', state=state, last_beat=now_iso(), note=f'bankroll ${bank} from the Kalshi balance', updated_at=now_iso())], on_conflict='id'):
            self.cfg['bankroll'] = float(bank)
            if self.trader:
                self.trader.bank = float(bank)
            print(f"bankroll set to ${bank} from the Kalshi balance (was ${prev:.0f}); caps follow it")

    # ---- one pass over both sports ----
    def run_pass(self):
        active = False
        seen = []
        try:
            self.sync_bankroll()
        except Exception as e:   # the bankroll read never blocks a pass
            print(f'bankroll sync failed: {e}')
        self.phases, self.next_kick = {}, None   # read by worker.py to pick its polling pace
        self._pre_snaps = []
        for sport in self.cfg['sports']:
            try:
                games = self.games(sport)
            except Exception as e:
                print(f'espn {sport} unavailable: {e}')
                continue
            for g in games:
                self.state['games'].setdefault(g['id'], dict(sport=sport, name=g['name'], date=g['date_et'], first_seen=now_iso()))
            self.restore_pregame([g for g in games if feeds.phase(g) not in ('pre', 'post')])
            try:
                self.odds_lines(sport, games)
            except Exception as e:   # a sharp line is a bonus, never a reason to miss a pass
                print(f'odds api {sport} failed: {e}')
            for g in games:
                rec = self.state['games'][g['id']]
                feeds.note_clock(g, rec)
                ph = feeds.phase(g)
                # a break ESPN reports before it could have happened (the end of the first as the half, the start
                # of the third as its end) is not a break: the label and the pacing stay with the quarter
                if ph == 'half' and (feeds.break_too_early(g, rec, 'half') or not feeds.period_played(g, 2, rec)):
                    ph = 'approaching'
                elif ph == 'q3end' and (feeds.break_too_early(g, rec, 'q3') or not feeds.period_played(g, 3, rec)):
                    ph = 'approaching3'
                rec['last_seen'] = now_iso()
                rec['phase'] = ph
                self.phases[ph] = self.phases.get(ph, 0) + 1
                if ph == 'pre' and g['start_utc'] and (self.next_kick is None or g['start_utc'] < self.next_kick):
                    self.next_kick = g['start_utc']
                if ph == 'pre':
                    self.capture_pregame(g, rec)
                elif ph in ('half', 'early3'):
                    active = True
                    self.evaluate(g, rec)
                elif ph in ('q3end', 'early4'):
                    active = True
                    self.evaluate_q3(g, rec)
                elif ph in ('approaching', 'approaching3'):
                    active = True   # a break is minutes away: poll fast, and read nothing as a pregame line
                elif ph == 'post':
                    try:
                        self.settle(g, rec)
                    except Exception as e:  # grading must never block the watch
                        print(f"settle {g.get('short')} failed: {e}")
                if self.trader and ph not in ('pre', 'post'):
                    try:
                        self.watch_orders(g, rec, ph)
                    except Exception as e:   # the order log never blocks the watch
                        print(f"orders {g.get('short')}: {e}")
                seen.append((g, rec))
        self.prune()
        self.db_games(seen)
        if self._pre_snaps and store.enabled():   # after db_games, so every game row exists first
            store.write('quote_snapshots', self._pre_snaps, on_conflict='taken_at,game_id,strike')
        return active

    # ---- Supabase mirror: the same facts the CSVs and state.json hold, one request per table per pass ----
    def db_games(self, seen):
        """Upsert the games this pass saw. A game is sent when anything about it changed, and at least every
        ten minutes so last_seen stays fresh."""
        if not store.enabled():
            return
        lined, unlined, now = [], [], time.time()
        for g, rec in seen:
            pre, half, post = rec.get('pre') or {}, rec.get('half') or {}, g['state'] == 'post'
            row = dict(id=g['id'], sport=g['sport'], name=g['name'], short=g['short'], date_et=g['date_et'], start_utc=g['start_utc'],
                       away_abbr=g['away']['abbr'], home_abbr=g['home']['abbr'],
                       away_name=g['away']['short'] or g['away']['abbr'], home_name=g['home']['short'] or g['home']['abbr'],
                       kalshi_total_event=rec.get('kalshi_total_event'), phase=rec.get('phase'), status=g['status'],
                       half_away=half.get('away'), half_home=half.get('home'), half_at=rec.get('half_at'),
                       final_away=g['away']['score'] if post else None, final_home=g['home']['score'] if post else None,
                       first_seen=rec.get('first_seen'),
                       away_score=g['away']['score'], home_score=g['home']['score'], period=g['period'], clock=g['clock'], detail=g['detail'])
            if pre.get('total'):
                row.update(pre_total=pre.get('total'), pre_home_spread=pre.get('home_spread'), pre_source=pre.get('source'), pre_at=pre.get('at'))
                if pre.get('books'):   # every book's close and ESPN's number beside the line used (supabase/008_pre_books.sql)
                    row['pre_books'] = dict(pre['books'], espn=pre.get('espn'))
            h = hash(json.dumps(row, sort_keys=True, default=str))
            prev = self._db_games.get(g['id'])
            if prev and prev[0] == h and now - prev[1] < 600:
                continue
            self._db_games[g['id']] = (h, now)
            (lined if pre.get('total') else unlined).append(dict(row, last_seen=rec.get('last_seen'), updated_at=now_iso()))
        # One write per sport and per shape. A game with no pregame line on record sends no pre_* columns at all,
        # and a game whose line has no book closes sends no pre_books, so a watcher that lost its state (or first
        # saw the game in play) never nulls out what the other watcher captured before kickoff. Every row in one
        # write must carry the same keys: Supabase rejects a batch whose rows differ (PGRST102), and on Oct 22 the
        # college batch mixed rows with and without pre_books and failed every pass, which left Today showing
        # kicked-off games as coming up. One batch per sport, so a sport the games table does not accept yet is
        # rejected on its own and never takes the other sports' rows down with it.
        for sport in sorted({r['sport'] for r in lined + unlined}):
            for batch in (lined, unlined):
                mine = [r for r in batch if r['sport'] == sport]
                for keys in sorted({tuple(sorted(r)) for r in mine}):
                    store.write('games', [r for r in mine if tuple(sorted(r)) == keys], on_conflict='id')

    def db_pregame(self, ids):
        """The pregame line columns of the games table for these ids, keyed by id. Under --fixtures the rows come
        from tests/fixtures/supabase_games.json instead of Supabase."""
        if self.fixtures:
            rows = load_json(os.path.join(self.fixtures, 'supabase_games.json'), [])
        elif store.enabled() and ids:
            rows = store.read('games', {'select': 'id,pre_total,pre_home_spread,pre_source,pre_at', 'id': 'in.(' + ','.join(ids) + ')'})
        else:
            rows = []
        want = set(ids)
        return {r['id']: r for r in rows if r.get('id') in want}

    def restore_pregame(self, games):
        """Games already kicked off whose record has no pregame line (state lost, or first seen in play): take the
        line the games table captured before kickoff, and only that. ESPN's odds block and Kalshi's 50-50 line
        are the live line once the game is on, and a live line saved as the pregame line priced nine halftimes
        off the wrong number on Oct 17. One read per pass covers every game that needs it; a game that came
        back empty is asked about again after two minutes."""
        now = time.time()
        need = []
        for g in games:
            rec = self.state['games'][g['id']]
            if (rec.get('pre') or {}).get('total') or now - float(rec.get('pre_asked') or 0) < 120:
                continue
            need.append(g)
        if not need:
            return
        rows = self.db_pregame([g['id'] for g in need])
        for g in need:
            rec = self.state['games'][g['id']]
            rec['pre_asked'] = round(now)
            row = rows.get(g['id']) or {}
            if not row.get('pre_total'):
                continue
            pre = dict(total=float(row['pre_total']), source=row.get('pre_source'), at=row.get('pre_at'), restored=now_iso())
            if row.get('pre_home_spread') is not None:
                pre['home_spread'] = float(row['pre_home_spread'])
            rec['pre'] = pre
            print(f"{g['short']}: pregame line restored from the games table (o/u {pre['total']}, spread {pre.get('home_spread')})")

    def db_eval(self, ts, g, rec, m, total, spread, quotes, rows, sug, ev, sizing, held=None, score=None):
        """One suggestions row (the halftime_log row plus the full ranked singles and middles) and one
        quote_snapshots row per strike: Kalshi's bid and ask next to the model's fair probability and limits."""
        if not store.enabled():
            return
        # At a 5-second pace most passes see the same quotes. Write a priced row only when the quotes, score or
        # phase changed, or 30 seconds have passed, so Supabase keeps a full record without 3x the rows.
        score = score or rec['half']   # half_away / half_home hold the break score the row was priced at (the end-of-third score for a q3end row)
        key = (rec.get('phase'), score['away'], score['home'], total,
               tuple((r['line'],) + tuple((quotes.get(r['line']) or {}).get(k) for k in ('yb', 'y', 'nb', 'n')) for r in rows))
        last = self._db_evals.get(g['id'])
        now = time.time()
        if last and last[0] == key and now - last[1] < 30:
            return
        self._db_evals[g['id']] = (key, now)
        best_mid = sug['mids'][0] if sug['mids'] else None
        best_single = sug['singles'][0] if sug['singles'] else None
        store.write('suggestions', [dict(
            taken_at=ts, game_id=g['id'], sport=g['sport'], game=g['short'], date_et=g['date_et'], event_ticker=ev.get('event_ticker'),
            phase=rec.get('phase'), total=total, home_spread=spread, half_away=score['away'], half_home=score['home'],
            away_score=g['away']['score'], home_score=g['home']['score'],   # the live score when priced: equal to the half by construction
            mu=round(m.mu, 2), sd=round(m.sd, 2), fair_line=engine.fair_line(m), market_line=feeds.kalshi_total_line(ev),
            # the center the ladder was shaped around and the sharp 2H line when one was read (supabase/009_sharp.sql)
            mu_model=round(m.mu_model, 2), center=None if m.center is None else round(m.center, 2), center_src=rec.get('center_src'),
            sharp_2h=(rec.get('h2') or {}).get('line'),
            best_single=f"{best_single['kind']} {best_single['line']} @{best_single['price_c']}" if best_single else None,
            best_single_edge_c=round(100 * best_single['edge'], 1) if best_single else None,
            best_mid=f"Y{best_mid['a']['line']}@{best_mid['a']['price_c']}+N{best_mid['b']['line']}@{best_mid['b']['price_c']}" if best_mid else None,
            best_mid_edge_c=round(100 * best_mid['ev'], 1) if best_mid else None,
            n_plays=sum(1 for x in sug['mids'] + sug['singles'] + (sug.get('revs') or []) if x['ok']),
            singles=sug['singles'], mids=sug['mids'][:max(MIDS_KEPT, sum(1 for x in sug['mids'] if x['ok']))],   # best first, every cleared one kept
            # reverse middles the same way (supabase/005_reverse.sql adds the column; written without it until then)
            revs=(sug.get('revs') or [])[:max(10, sum(1 for x in sug.get('revs') or [] if x['ok']))],
            held=held or {},   # what you hold on this total, read as one position: legs with verdicts, the finals in dollars, the hedge (supabase/005_reverse.sql adds the column)
            spot=m.spot(),     # the game-state label (blowout, favorite trailing, ...), for the Record split; it left the push text on Oct 22 (supabase/010_spot.sql)
            # the weather read at the half and the mismatch lane's shadow call (supabase/014_weather_shot.sql adds both columns)
            weather=rec.get('weather') if rec.get('phase') != 'q3end' else None, shot=rec.get('shot') if rec.get('phase') != 'q3end' else None,
            bankroll=sizing['bankroll'], max_risk=sizing['max_risk'], max_cost=sizing['max_cost'])], on_conflict='taken_at,game_id')
        snaps = []
        for r in rows:
            q = quotes.get(r['line']) or {}
            snaps.append(dict(taken_at=ts, game_id=g['id'], event_ticker=ev.get('event_ticker'), market_ticker=q.get('ticker'),
                              strike=r['line'], phase=rec.get('phase'), yes_bid=q.get('yb'), yes_ask=q.get('y'), no_bid=q.get('nb'), no_ask=q.get('n'),
                              p_over=r['p_over'], p_push=r['p_push'], over_take=r['over_take'], over_rest=r['over_rest'],
                              under_take=r['under_take'], under_rest=r['under_rest']))
        store.write('quote_snapshots', snaps, on_conflict='taken_at,game_id,strike')

    def claim_alert(self, ts, g, slot, kind, priority, title, body, ev, sheet=None):
        """Reserve this game's slot in the alerts table before pushing, so the always-on worker and the GitHub
        Actions backup never both push the same alert. False means the other one already did. The row carries
        the push's sheet (the plays at their prices and sizes), which is what the final grades."""
        return store.claim('alerts', dict(sent_at=now_iso(), game_id=g['id'], sport=g['sport'], slot=slot, kind=kind, priority=priority,
                                          title=title, body=body, event_ticker=ev.get('event_ticker'), channels=None, suggestion_at=ts, sheet=sheet),
                           on_conflict='game_id,slot')

    def db_alert(self, ts, g, slot, kind, priority, title, body, ev, sent, sheet=None):
        if not store.enabled():
            return
        store.write('alerts', [dict(sent_at=now_iso(), game_id=g['id'], sport=g['sport'], slot=slot, kind=kind, priority=priority,
                                    title=title, body=body, event_ticker=ev.get('event_ticker'), channels=', '.join(sent), suggestion_at=ts, sheet=sheet)],
                    on_conflict='game_id,slot')

    def capture_pregame(self, g, rec):
        """Lines before kickoff: ESPN's odds block, then ESPN's odds endpoint, then Kalshi's 50-50 strikes. Kept
        fresh until kickoff. Only ever called while the game is in the 'pre' phase: from kickoff on every feed
        shows the live line, and nothing read then may be stored as the pregame line (see restore_pregame)."""
        pre = rec.setdefault('pre', {})
        spread, total = feeds.espn_lines(g)
        row = feeds.match_odds(g, self._odds_rows.get(g['sport']) or [])
        if row:
            # the sharp line wins: Pinnacle's close, or the median across the US books. ESPN's number is kept
            # beside it, and every book's, so the gap between the two is on record for the line study.
            pre.update(total=row['total'], home_spread=row['home_spread'], source='odds:' + row['source'], at=now_iso())
            pre['books'] = {k: list(v) for k, v in row['books'].items()}
            pre['odds_event'] = row.get('id')   # the Odds API event, for the sharp second-half line at the half
            pre.pop('spread_source', None)
            if total:
                pre['espn'] = [spread, total]
        elif total:
            pre.update(total=total, source='espn', at=now_iso())
            if spread is not None:
                pre['home_spread'] = spread
        if (not pre.get('total') or pre.get('home_spread') is None) and not self.fixtures and time.time() - float(rec.get('odds_asked') or 0) > 1800:
            rec['odds_asked'] = round(time.time())   # the odds endpoint is tried every 30 minutes until the line shows up
            s2, t2 = feeds.espn_odds_endpoint(g['sport'], g['id'])
            if t2 and not pre.get('total'):
                pre.update(total=t2, source='espn-odds', at=now_iso())
            if s2 is not None and pre.get('home_spread') is None:
                pre['home_spread'] = s2
        if not pre.get('total') or pre.get('home_spread') is None:
            ev = feeds.match_event(g, self.events(g['sport'], 'total'))
            if ev:
                kt = feeds.kalshi_total_line(ev)
                if kt and not pre.get('total'):
                    pre.update(total=kt, source='kalshi', at=now_iso())
                rec['kalshi_total_event'] = ev.get('event_ticker')
            if pre.get('home_spread') is None:
                sev = feeds.match_event(g, self.events(g['sport'], 'spread'))
                if sev:
                    ks = feeds.kalshi_spread_line(sev, g)
                    if ks is not None:
                        pre['home_spread'] = ks
                        pre['spread_source'] = 'kalshi'
        try:
            self.pregame_market(g, rec)
        except Exception as e:
            print(f"pregame market {g.get('short')} failed: {e}")

    def pregame_market(self, g, rec):
        """Kalshi's live full-game total before kickoff: the market's 50-50 line and the asks on the strike just
        below it (Yes, over) and just above it (No, under). Read from the events list the pass already pulled."""
        ev = feeds.match_event(g, self.events(g['sport'], 'total'))
        if not ev:
            return
        rec['kalshi_total_event'] = ev.get('event_ticker')
        line = feeds.kalshi_total_line(ev)
        q = feeds.total_quotes(ev)
        if not line or not q:
            return
        lo = max((k for k in q if k < line), default=None)
        hi = min((k for k in q if k > line), default=None)
        legs = []
        if lo is not None:
            legs.append(dict(side='over', k=lo, c=q[lo]['y']))
        if hi is not None:
            legs.append(dict(side='under', k=hi, c=q[hi]['n']))
        rec['mkt'] = dict(line=line, legs=legs, at=now_iso())
        # Pregame line history: the strikes within 6 points of the market line, saved to quote_snapshots with
        # phase 'pre' when they change (at most every 2 minutes) or every 10 minutes regardless.
        near = sorted(k for k in q if abs(k - line) <= 6)
        key = (line,) + tuple((k, q[k]['yb'], q[k]['y'], q[k]['nb'], q[k]['n']) for k in near)
        last = self._pre_last.get(g['id'])
        t = time.time()
        if last and ((last[0] == key and t - last[1] < 600) or t - last[1] < 120):
            return
        self._pre_last[g['id']] = (key, t)
        ts = now_iso()
        for k in near:
            self._pre_snaps.append(dict(taken_at=ts, game_id=g['id'], event_ticker=ev.get('event_ticker'), market_ticker=q[k].get('ticker'),
                                        strike=k, phase='pre', yes_bid=q[k]['yb'], yes_ask=q[k]['y'], no_bid=q[k]['nb'], no_ask=q[k]['n'],
                                        p_over=None, p_push=None, over_take=None, over_rest=None, under_take=None, under_rest=None))

    def sharp_2h(self, g, rec):
        """The sharp second-half total on this game at the half, read once from The Odds API (one credit) and
        kept on the record; read again once if the first look was more than four minutes ago (the line moves as
        the break goes on). Needs the key, the game's Odds API event (matched before kickoff, or against the
        cached list now), and at least ten credits left. Off on fixtures. None when there is nothing."""
        key = (os.environ.get('ODDS_API_KEY') or '').strip()
        if not key or self.fixtures or g['sport'] not in feeds.ODDS_SPORT:
            return None
        h2 = rec.get('h2')
        now = time.time()
        if h2 and (h2.get('line') is None or now - float(h2.get('at_s') or 0) < 240 or int(h2.get('calls') or 0) >= 2):
            return h2 if h2.get('line') is not None else None
        remaining = (self.state.get('odds_api') or {}).get('remaining')
        if remaining is not None and remaining < 10:
            return h2 if h2 and h2.get('line') is not None else None
        event = (rec.get('pre') or {}).get('odds_event')
        if not event:
            row = feeds.match_odds(g, self._odds_rows.get(g['sport']) or [])
            event = row.get('id') if row else None
            if event:
                rec.setdefault('pre', {})['odds_event'] = event
        if not event:
            return None
        try:
            books, usage = feeds.odds_api_h2(g['sport'], event, key)
        except Exception as e:
            print(f"{g['short']}: sharp 2H line failed ({e})")
            rec['h2'] = dict(h2 or {}, at_s=now, calls=int((h2 or {}).get('calls') or 0) + 1)
            return h2 if h2 and h2.get('line') is not None else None
        if usage:
            self.state.setdefault('odds_api', {}).update(remaining=usage.get('remaining'), used=usage.get('used'), usage_at=now_iso())
        line, source, n = feeds.sharp_h2(books)
        rec['h2'] = dict(line=line, source=source, n=n, books=books, at=now_iso(), at_s=now, calls=int((h2 or {}).get('calls') or 0) + 1)
        if line is None:
            print(f"{g['short']}: no sharp 2H line posted yet")
            return None
        print(f"{g['short']}: sharp 2H {line} ({source}, {n} books)")
        return rec['h2']

    def market_center(self, g, ev, h1, stage='half', rec=None):
        """(expected points left, weight the model keeps, source) for the center of the ladder; (None, 1.0, None)
        when the model is on its own. At the half the sharp second-half line comes first when one is in hand
        (sharp_model_pct per sport). Otherwise, for sports that center on the market (center_model_pct), the
        market center is Kalshi's implied full-game line at the break (the 50-50 crossing of the ladder's bid-ask
        midpoints) minus the points so far. A line outside the sport's plausible range for the stage is ignored."""
        lo, hi = (CENTER_Q4_RANGE if stage == 'q3' else CENTER_2H_RANGE).get(g['sport'], (0, 10**6))
        if stage == 'half' and rec is not None:
            spct = (self.cfg.get('sharp_model_pct') or {}).get(g['sport'])
            h2 = self.sharp_2h(g, rec) if spct is not None and spct < 100 else None
            if h2 and lo <= h2['line'] <= hi:
                return h2['line'], spct / 100, 'sharp'
        cmp = self.cfg.get('center_model_pct') or {}
        pct = cmp.get(g['sport']) if isinstance(cmp, dict) else None
        if pct is None or pct >= 100:
            return None, 1.0, None
        line = feeds.kalshi_total_line(ev)
        if line is None:
            return None, 1.0, None
        c = line - h1
        if not lo <= c <= hi:
            return None, 1.0, None
        return c, pct / 100, 'kalshi'

    def weather(self, g, rec):
        """The weather at the venue, read once per break (kept 45 minutes on the record), for sports with a block
        in config weather. The shift it carries is the haircut HalfModel applies to the model's own mean."""
        cfg = (self.cfg.get('weather') or {}).get(g['sport'])
        if not cfg:
            return None
        wx = rec.get('weather')
        if wx and wx.get('at'):
            try:
                age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(wx['at'])).total_seconds()
            except Exception:
                age = 10**6
            if age < 45 * 60:
                return wx
        try:
            wx = weather.for_game(g, cfg, self.fixtures)
        except Exception as e:   # a weather read never blocks a pass
            print(f"{g['short']}: weather read failed ({e})")
            wx = None
        if wx:
            rec['weather'] = wx
            print(f"{g['short']}: weather {wx['why']} at {wx['venue']}" + (f", model {wx['shift']:+.1f}" if wx['bad'] else ''))
        return wx

    def mismatch(self, g, spread):
        """config mismatch.<sport>: a pregame spread at or past `spread` points puts the game in the lane, with the
        ladder's width (`width`, 0.87) and the band's upper edge (`band_hi`, 90c). mode shadow logs and shows what
        it would call; live prices the desk with it. None when the game is not in the lane."""
        cfg = (self.cfg.get('mismatch') or {}).get(g['sport'])
        if not cfg or spread is None or abs(float(spread)) < float(cfg.get('spread', 28)):
            return None
        return dict(mode=cfg.get('mode', 'shadow'), width=float(cfg.get('width', 0.87)), band_hi=int(cfg.get('band_hi', 90)), spread=abs(float(spread)))

    def shot_lane(self, g, lane, total, spread, home_pts, away_pts, center, center_w, quotes, bank, max_risk, max_cost, m0):
        """The narrowed ladder's own suggest() over the band's extended top, kept as the sides it would take at
        80c or more (the high-probability sides the tail study found underpriced in these games). The lane
        prices with the narrowed model alone (trust 1.0): the question it is logging is whether Kalshi's ladder
        is too wide in these games, so blending Kalshi's own price in would halve the signal under test. Each
        pick carries Kalshi's implied number and the live desk's fair for the same leg. In live mode the width
        goes into the desk's own model and the usual trust blend applies."""
        m = engine.HalfModel(g['sport'], total, spread, home_pts, away_pts, center=center, center_w=center_w, shift=m0.shift, width=lane['width'])
        rows = engine.price_lines(m, list(quotes), 'fg', self.cfg['margin_c'] / 100)
        sug = engine.suggest(rows, quotes, self.cfg['order'], self.cfg['margin_c'] / 100, 1.0, bank, max_risk, max_cost,
                             (self.cfg['min_price_c'], lane['band_hi']), None)
        live = {(r['line'],): r for r in engine.price_lines(m0, list(quotes), 'fg', self.cfg['margin_c'] / 100)}
        picks = []
        for x in sug['singles']:
            if not x['ok'] or x['price_c'] < 80:
                continue
            r0 = live.get((x['line'],)) or {}
            picks.append(dict(kind=x['kind'], line=x['line'], price_c=x['price_c'], fair_model=round(x['fair_model'], 4), fair_used=round(x['fair_used'], 4),
                              fair_kalshi=None if x.get('fair_mkt') is None else round(x['fair_mkt'], 4),
                              fair_live=round(r0.get('p_over' if x['kind'] == 'over' else 'p_under', 0.0), 4), edge=round(x['edge'], 4),
                              contracts=x['contracts'], cost=x['cost'], win=x['win']))
        return dict(mode=lane['mode'], spread=lane['spread'], width=lane['width'], band_hi=lane['band_hi'], mu=round(m.mu, 2), sd=round(m.sd, 2),
                    fair=engine.fair_line(m), picks=picks[:2])

    def first_half_box(self, g, rec):
        """NBA only: the first-half box score (shots, free throws, offensive rebounds, turnovers, fouls, and the
        possession count they imply), read once per game at the half from ESPN's summary and kept on the record
        and the graded sheet. Logged, not priced: first-half possessions carry about 0.2 points of second-half
        total per possession above average in 8,900 games of history (t 3.0), the sharp 2H line half-prices it,
        and whether Kalshi's ladder prices it at all is what the graded NBA halftimes will show
        (claude/nba-halftime.md, section 11). Under --fixtures the box comes from espn_box_<id>.json if present."""
        if g['sport'] != 'nba' or rec.get('pace') or rec.get('pace_asked'):
            return
        rec['pace_asked'] = True
        if self.fixtures:
            box = feeds.parse_box_stats(load_json(os.path.join(self.fixtures, f"espn_box_{g['id']}.json"), {}))
        else:
            box = feeds.espn_box_stats(g['sport'], g['id'])
        if box:
            rec['pace'] = dict(box, at=now_iso(), half=f"{g['away']['score']}-{g['home']['score']}")
            print(f"{g['short']}: first-half box read, {box['poss']} possessions a side")

    def spread_at_half(self, g, rec, spread, home_pts, away_pts):
        """NBA only, once per game at the half: Kalshi's spread ladder (KXNBASPREAD, 'X wins by over k') read as
        an implied full-game home spread, next to the margin model's number and the naive one. Logged on the
        record and the graded sheet; no pricing, no push. After 150 graded halftimes the question is whether
        Kalshi's ladder shrinks the lead the way the sharp 2H spread does (then there is nothing here) or quotes
        the naive line (then the leader's side of the ladder is 3+ points dear in 44 percent of games)."""
        if g['sport'] not in engine.MARGIN_2H or rec.get('spread_half') or rec.get('spread_asked'):
            return
        rec['spread_asked'] = True
        model_m, naive_m = engine.expected_margin(g['sport'], spread, home_pts, away_pts)
        row = dict(at=now_iso(), half_home_margin=home_pts - away_pts, pregame_home_spread=spread, model_home_margin=model_m, naive_home_margin=naive_m, mkt_home_spread=None)
        try:
            sev = feeds.match_event(g, self.events(g['sport'], 'spread'))
            if sev:
                row['event_ticker'] = sev.get('event_ticker')
                row['mkt_home_spread'] = feeds.kalshi_spread_line(sev, g)
        except Exception as e:
            print(f"spread ladder {g.get('short')} failed: {e}")
        rec['spread_half'] = row
        if row['mkt_home_spread'] is not None:
            print(f"{g['short']}: spread ladder at the half: Kalshi home {row['mkt_home_spread']:+.1f}, model home margin {model_m:+.1f}, naive {naive_m:+.1f}")

    def evaluate(self, g, rec):
        """The halftime window (and football's first minute of Q3)."""
        self.evaluate_stage(g, rec, 'half')

    def evaluate_q3(self, g, rec):
        """The NBA's second window: the break before the fourth quarter, and its first 30 seconds while the score
        is still the end-of-third score. Same ladder, rules and pushes; the model is the end-of-third one
        (engine.LateModel), the slot is 'q3', the record keys carry a _q3 suffix."""
        if (g['sport'] + '_q3') not in engine.MODEL:
            return
        self.evaluate_stage(g, rec, 'q3')

    def evaluate_stage(self, g, rec, stage):
        q3 = stage == 'q3'
        K = (lambda k: k + '_q3') if q3 else (lambda k: k)   # record keys: half / half_at / moved / clear / sheet, or the _q3 versions
        hs = feeds.third_score(g, rec) if q3 else feeds.half_score(g, rec)
        if hs is None:
            return
        early = feeds.break_too_early(g, rec, stage)
        if early:
            if rec.get(K('noted_early')) != early:
                rec[K('noted_early')] = early
                print(f"{g['short']}: {early}, not a break, nothing priced")
            return
        # The break score is taken once. Every later pass compares the live score with it, so a score that moves
        # while ESPN still shows the break (a stuck 0:00 clock, Oct 24) stops the pricing instead of re-pricing
        # the new score as the break.
        key = 'third' if q3 else 'half'
        if not rec.get(key):
            rec[key] = dict(away=hs[0], home=hs[1])
        score = rec[key]
        away_pts, home_pts = score['away'], score['home']
        live = (g['away']['score'], g['home']['score'])
        if live != (away_pts, home_pts):
            # Someone scored since the break. The model no longer describes the game, so from here on nothing is
            # priced, logged or written: the newest suggestions row stays the last one priced at the break score,
            # and the app marks it stale by comparing it with the live score on the games row.
            # (Oct 17: a Q3 touchdown at 13:20 left "Under 35.5 at 27c" showing as a 10.7c edge for five minutes.)
            if not rec.get(K('moved_at')):
                rec[K('moved_at')] = now_iso()
                rec[K('moved')] = dict(away=live[0], home=live[1])
                print(f"{g['short']}: score moved from {away_pts}-{home_pts} to {live[0]}-{live[1]} after the {'third' if q3 else 'half'}, pricing stopped")
            rec['last_eval'] = now_iso()
            return
        # Only a line captured before kickoff prices the half. Nothing is read from a feed here: by now ESPN's
        # odds block and Kalshi's 50-50 line are the live line (restore_pregame has the Oct 17 damage).
        pre = rec.get('pre') or {}
        total, spread = pre.get('total'), pre.get('home_spread')
        if not total:
            if not rec.get('noted_no_line'):
                print(f"{g['short']}: no pregame line on record, skipping (a line is never read once the game is on)")
                rec['noted_no_line'] = True
            return
        if spread is None:
            if not rec.get('noted_no_spread'):
                print(f"{g['short']}: no pregame spread on record, pricing as a pick")
                rec['noted_no_spread'] = True
            spread = 0.0
        ev = feeds.match_event(g, self.events(g['sport'], 'total'))
        if not ev:
            if not rec.get('noted_no_market'):
                print(f"{g['short']}: no Kalshi total market, skipping")
                rec['noted_no_market'] = True
            return
        rec['kalshi_total_event'] = ev.get('event_ticker')
        quotes = feeds.total_quotes(ev)
        if not quotes:
            return
        center, center_w, center_src = self.market_center(g, ev, away_pts + home_pts, stage, rec)
        rec['center_src'] = center_src
        if center is None and g['sport'] in self.cfg.get('require_center', ['nba']):
            # The NBA model is a ruler, not a compass (trust study): without a market center it never prices.
            # A center the plausible range rejected is also the surest sign the break score is wrong.
            if not rec.get(K('noted_no_center')):
                rec[K('noted_no_center')] = True
                print(f"{g['short']}: no usable market center at the {'end of the 3rd' if q3 else 'half'} ({away_pts}-{home_pts}), the NBA never prices on the model alone")
            return
        if q3:
            m = engine.LateModel(g['sport'], total, spread, home_pts, away_pts, center=center, center_w=center_w)
        else:
            self.first_half_box(g, rec)
            self.spread_at_half(g, rec, spread, home_pts, away_pts)
            wx = self.weather(g, rec)
            lane = self.mismatch(g, spread)
            m = engine.HalfModel(g['sport'], total, spread, home_pts, away_pts, center=center, center_w=center_w,
                                 shift=(wx or {}).get('shift') or 0.0, width=lane['width'] if lane and lane['mode'] == 'live' else 1.0)
        rows = engine.price_lines(m, list(quotes), 'fg', self.cfg['margin_c'] / 100)
        bank = float(self.cfg['bankroll'])
        # daily cap: plays already pushed today (by cost) count against day_cost_pct of bankroll
        day = self.state.setdefault('day_spend', {})
        spent = float(day.get(g['date_et'], 0))
        remaining = max(0.0, bank * self.cfg['day_cost_pct'] / 100 - spent)
        max_risk = min(bank * self.cfg['risk_pct'] / 100, remaining)
        max_cost = min(bank * self.cfg['cost_pct'] / 100, remaining)
        # What you already own on this total counts against the middle loss cap before anything new is sized
        # (Nick, Oct 22): a built middle's miss comes out of the cap first.
        held_legs = self.held_legs(ev, quotes)
        cap = self.cfg.get('mid_loss_cap')
        held_miss = engine.held_miss_loss(held_legs) if held_legs else 0.0
        mid_loss = None if cap is None else max(0.0, cap - held_miss)
        sug = engine.suggest(rows, quotes, self.cfg['order'], self.cfg['margin_c'] / 100, self.cfg['trust_pct'] / 100,
                             bank, max_risk, max_cost, (self.cfg['min_price_c'], self.cfg['max_price_c']), mid_loss)
        inp = dict(away=g['away']['abbr'], home=g['home']['abbr'], away_name=g['away']['short'] or g['away']['abbr'], home_name=g['home']['short'] or g['home']['abbr'], h1a=away_pts, h1h=home_pts,
                   sharp=(rec.get('h2') or {}).get('line') if center_src == 'sharp' else None,
                   weather=weather.text(rec.get('weather')) if not q3 else None)
        # the mismatch lane (shadow): what a narrowed ladder would call in a 28+ point college game, logged and
        # shown as a SHOT line, never a play until config mismatch.<sport>.mode is live
        shot = None
        if not q3 and lane and lane['mode'] == 'shadow':
            shot = self.shot_lane(g, lane, total, spread, home_pts, away_pts, center, center_w, quotes, bank, max_risk, max_cost, m)
            rec['shot'] = shot
        sizing = dict(bankroll=bank, max_risk=max_risk, max_cost=max_cost, margin=self.cfg['margin_c'] / 100, mid_loss=mid_loss,
                      mid_loss_cap=cap, held_miss=held_miss, near_pts=(self.cfg.get('rest_near_pts') or {}).get(g['sport'], 3.5))
        focus = 'middles' if g['sport'] in (self.cfg.get('middle_focus') or []) else None
        # What you already own on this total, read as one position off the same ladder: a verdict a leg, the
        # finals together, and the hedge that leaves no final losing when one exists. It lifts a read to high
        # priority when there is something to do (a SELL verdict or a hedge).
        pos = engine.held_position(rows, quotes, held_legs, self.cfg['margin_c'] / 100, self.cfg['order'], (self.cfg['min_price_c'], self.cfg['max_price_c'])) if held_legs else None
        held_lines = engine.held_block(pos) if pos else []
        held_act = bool(pos) and (bool(pos.get('hedge')) or any((h.get('sell') or {}).get('verdict') == 'SELL' for h in pos['legs']))
        kind, head, text = engine.order_sheet(m, inp, rows, sug, sizing, focus=focus, held=held_lines, shot=engine.shot_lines(shot) if shot else None)
        plays = [x for x in sug['mids'] if x['ok']] + [x for x in sug['singles'] if x['ok']] + [x for x in sug.get('revs') or [] if x['ok']]
        ts = now_iso()
        rec.setdefault(K('half_at'), ts)
        # Every cleared line gets stamped with when it first cleared this break, so Today can say "clear for 2 min"
        # and a one-look flicker reads differently from a line that has held. The full history (every priced row)
        # is in the suggestions table; settle() grades all of it, pushed or not.
        clear = rec.setdefault(K('clear'), {})
        for x in sug['singles']:
            if x.get('ok'):
                e = clear.setdefault(f"single {x['kind']} {x['line']}", dict(first=ts, n=0))
                e['last'], e['n'] = ts, e['n'] + 1
                x['since'] = e['first']
        for x in sug['mids']:
            if x.get('ok'):
                e = clear.setdefault(f"mid {x['a']['line']} {x['b']['line']}", dict(first=ts, n=0))
                e['last'], e['n'] = ts, e['n'] + 1
                x['since'] = e['first']
        self.log_row(g, rec, m, total, spread, quotes, sug, ev, ts, score)
        self.db_eval(ts, g, rec, m, total, spread, quotes, rows, sug, ev, sizing, held=pos, score=score)
        try:
            self.db_venues(ts, g, rec, stage, quotes)
        except Exception as e:   # another venue's ladder is a log, never a reason to miss a pass
            print(f"{g['short']}: venue log failed ({e})")
        sheet = self.sheet(g, m, total, spread, away_pts, home_pts, rows, sug, ev, sizing, rec)
        sheet['stage'] = stage
        if not q3:
            if rec.get('weather'):
                sheet['weather'] = rec['weather']
            if shot:
                sheet['shot'] = shot
        if pos:
            sheet['held'] = pos
        # Auto orders (trade.py): planned once per break, at the first look, whatever the push slot did. Shadow
        # mode records what it would have sent; live mode sends only when every switch in trade.Trader.armed is on.
        if self.trader and not (rec.get('auto') or {}).get(stage):
            try:
                orders, note = self.trader.plan(g, rec, stage, m, rows, sug, quotes, ev, sizing, ts, held_legs)
                done = self.trader.act(orders)
                rec.setdefault('auto', {})[stage] = dict(at=ts, n=len(done), note=note, mode=self.trader.mode(),
                                                        open=[o for o in done if o.get('status') in ('planned', 'sent', 'resting')])
                if done or note:
                    print(f"auto {self.trader.mode()} {g['short']} ({stage}): {len(done)} orders" + (f"; {note}" if note else ''))
            except Exception as e:   # the executor never blocks a push
                print(f"auto {g['short']} failed: {e}")
                rec.setdefault('auto', {})[stage] = dict(at=ts, n=0, note=f'failed: {e}'[:200], open=[])
        # Two pushes per game at most: one the first time it is seen at the half (as close to the end of Q2 as the
        # polling allows), one the first time it is seen after the Q3 kick while the score is still the
        # halftime score (the moved-score check above already returned otherwise). For the NBA the second slot
        # is the end of the third instead (a basket comes in seconds, so the early-Q3 look never happens there).
        # A PLAY goes out whenever something clears; a read goes out per read_push, which maps a sport to an
        # ntfy priority ('min' is silent and only shows in the app's list).
        slot = 'q3' if (q3 or rec.get('phase') == 'early3') else 'half'
        slots = rec.setdefault('slots', {})
        if slots.get(slot):
            rec['last_eval'] = now_iso()
            return
        when = 'end of 3rd' if q3 else ('half' if slot == 'half' else 'Q3')
        title = f"{head} ({when}, {g['sport'].upper()})"
        rp = self.cfg['read_push']
        read_pri = (rp.get(g['sport']) if isinstance(rp, dict) else ('default' if g['sport'] in rp else 'off')) or 'off'
        sheet.update(slot=slot, kind='play' if plays else 'update', title=title)
        if plays:
            if remaining < 20:
                text += f"\nDaily cap reached (${spent:.0f} suggested today): sizes above are scaled down."
            body = text + f"\n\n{ev.get('event_ticker')}"
            if not self.claim_alert(ts, g, slot, 'play', 'high', title, body, ev, sheet):
                slots[slot] = 'elsewhere'
                rec['last_eval'] = now_iso()
                return
            sent = send_push(title, body, priority='high', tags='moneybag', url=feeds.kalshi_url(ev.get('event_ticker')))
            slots[slot] = 'play'
            self.pushed.append(title)
            self.db_alert(ts, g, slot, 'play', 'high', title, body, ev, sent, sheet)
            # The game's record is the first PLAY push (the half, or Q3 when the half was a read). The alerts
            # table holds the same for both watchers; these are the fallback when it cannot be reached.
            rec.setdefault(K('play_sheet'), sheet)
            rec.setdefault(K('sheet'), sheet)
            top = ([x for x in sug['mids'] if x['ok']][:1] or [x for x in sug['singles'] if x['ok']][:1] or [x for x in sug.get('revs') or [] if x['ok']][:1])
            if top and not rec.get(K('counted_day')):
                day[g['date_et']] = round(spent + top[0]['cost'], 2)
                rec[K('counted_day')] = True
        elif read_pri != 'off' or held_act:
            if held_act:
                read_pri = 'high'   # something to do with a position you hold: this one buzzes whatever the sport's read setting
            body = text + f"\n\n{ev.get('event_ticker')}"
            if not self.claim_alert(ts, g, slot, 'update', read_pri, title, body, ev, sheet):
                slots[slot] = 'elsewhere'
                rec['last_eval'] = now_iso()
                return
            sent = send_push(title, body, priority=read_pri, url=feeds.kalshi_url(ev.get('event_ticker')))
            slots[slot] = 'read'
            self.pushed.append(title)
            self.db_alert(ts, g, slot, 'update', read_pri, title, body, ev, sent, sheet)
            rec.setdefault(K('sheet'), sheet)
        rec['last_eval'] = now_iso()

    def db_venues(self, ts, g, rec, stage, quotes):
        """Polymarket's total lines for the same game, read at the break every 15 seconds and written to the
        venue_quotes table beside Kalshi's ladder at the same moment (supabase/012_venues.sql). The cross-venue
        question (does one ladder lag the other, and by how much) is read from this table, nothing prices off
        it. Off on fixtures and for a sport Polymarket does not slug; one line when the event is not found."""
        if self.fixtures or g['sport'] not in feeds.POLY_SLUG:
            return
        now = time.time()
        if now - self._poly.get(g['id'], 0) < 15:
            return
        self._poly[g['id']] = now
        try:
            ev = feeds.polymarket_event(g)
        except Exception as e:
            if not rec.get('noted_no_poly'):
                print(f"{g['short']}: polymarket read failed ({e})")
                rec['noted_no_poly'] = True
            return
        if not ev:
            if not rec.get('noted_no_poly'):
                print(f"{g['short']}: no Polymarket event ({feeds.polymarket_slug(g)})")
                rec['noted_no_poly'] = True
            return
        rows = []
        for kind in ('fg', '1h'):
            pq = feeds.polymarket_totals(ev, kind)
            for k, q in pq.items():
                kq = quotes.get(k) or {}
                rows.append(dict(taken_at=ts, game_id=g['id'], sport=g['sport'], venue='polymarket', kind=kind, strike=k, phase=rec.get('phase'), stage=stage,
                                 yes_bid=q['yb'], yes_ask=q['y'], no_bid=q['nb'], no_ask=q['n'], market_id=q.get('ticker'),
                                 kalshi_yes_bid=kq.get('yb'), kalshi_yes_ask=kq.get('y'), kalshi_no_bid=kq.get('nb'), kalshi_no_ask=kq.get('n')))
            if kind == 'fg':
                rec['poly'] = dict(at=ts, quotes={f'{k:g}': q for k, q in pq.items()}, event=ev.get('slug'))
        if rows and store.enabled() and self._venue_ok:
            if not store.write('venue_quotes', rows, on_conflict='taken_at,game_id,venue,kind,strike'):
                self._venue_ok = False   # the table is not there yet (run supabase/012_venues.sql); one line, then quiet until the next start
                print('venue_quotes: not written again this run (run supabase/012_venues.sql)')

    def watch_orders(self, g, rec, ph):
        """A game with open auto orders: read its ladder on every pass (the break and the third quarter alike) and
        let the trader mark what a resting price has reached (the shadow fill model) or has expired. One events
        call per sport per pass, the same one the break pricing uses."""
        auto = rec.get('auto') or {}
        if not any(st.get('open') for st in auto.values()):
            return
        tk = rec.get('kalshi_total_event')
        ev = next((e for e in self.events(g['sport'], 'total') if e.get('event_ticker') == tk), None) if tk else None
        if not ev:
            return
        self.trader.touch(g, rec, feeds.total_quotes(ev), ph)

    def held_legs(self, ev, quotes):
        """The open positions on this game's total (self.holdings: held.holdings() rows keyed by event ticker,
        which the worker refreshes once a minute from the Kalshi sync; a plain watch.py run loads them once at
        the start), each with its strike read off the ladder. Legs on a strike the ladder does not quote are left out."""
        out = []
        for h in self.holdings.get(ev.get('event_ticker')) or []:
            k = next((k for k, v in quotes.items() if v.get('ticker') == h.get('ticker')), None)
            if k is None:
                continue
            out.append(dict(ticker=h.get('ticker'), side=h['side'], strike=k, shares=int(h['shares']), paid_c=h['paid_c'], fee=h.get('fee')))
        return out

    def sheet(self, g, m, total, spread, away_pts, home_pts, rows, sug, ev, sizing, rec=None):
        """What the first push said, kept so the final can grade it: cleared plays at their prices and sizes, the
        resting middle when nothing cleared (graded as a what-if), and the model and market fair lines."""
        singles, mid = engine.chosen(sug)
        rev = engine.chosen_rev(sug)
        focus = g['sport'] in (self.cfg.get('middle_focus') or [])
        # what the push led with, which is what the record grades as the play: the middle in a middle-focus
        # sport whenever one cleared, otherwise the best single, the reverse middle only when it is all that
        # cleared; a read has only the resting what-if
        lead = 'mid' if (mid and (focus or not singles)) else 'single' if singles else 'rev' if rev else 'rest'
        out = dict(at=now_iso(), lead=lead, total=total, spread=spread, h1a=away_pts, h1h=home_pts, mu=round(m.mu, 2), sd=round(m.sd, 2), spot=m.spot(),
                   mu_model=round(m.mu_model, 2), center=None if m.center is None else round(m.center, 2), center_w=m.center_w,
                   center_src=(rec or {}).get('center_src'), sharp=((rec or {}).get('h2') or {}).get('line'), sharp_books=((rec or {}).get('h2') or {}).get('books'),
                   pace=(rec or {}).get('pace'), spread_half=(rec or {}).get('spread_half'),
                   fair=engine.fair_line(m), mkt=feeds.kalshi_total_line(ev), held_miss=sizing.get('held_miss') or 0,
                   singles=[dict(kind=s['kind'], line=s['line'], price_c=s['price_c'], contracts=s['contracts'], cost=s['cost']) for s in singles],
                   mid=None, rest_mid=None)
        if rev:
            # a_line is the under's strike (the lower one), b_line the over's; the hole is the numbers between
            out['rev'] = dict(a_line=rev['a']['line'], a_price=rev['a']['price_c'], b_line=rev['b']['line'], b_price=rev['b']['price_c'], pairs=rev['pairs'], cost=rev['cost'])
        if mid:
            out['mid'] = dict(a_line=mid['a']['line'], a_price=mid['a']['price_c'], b_line=mid['b']['line'], b_price=mid['b']['price_c'], pairs=mid['pairs'], cost=mid['cost'])
        else:
            rp = engine.rest_plan(m, rows, 'fg', sizing['margin'], sizing['bankroll'], sizing['max_risk'], sizing['max_cost'], mid_loss=sizing.get('mid_loss'),
                                  near_pts=sizing.get('near_pts', 3.5))
            # Football grades the best resting middle, as before. A middle-focus sport posts a tight one first and a
            # wide one second, so the what-if grades the tight one (rest_mid) and keeps the wide one (rest_mid_wide).
            mids = rp.get('middles') or []
            rm = (mids[0] if mids else None) if focus else rp.get('middle')
            def rest_row(r):
                return dict(a_line=r['a']['line'], a_price=r['a']['over_rest'], b_line=r['b']['line'], b_price=r['b']['under_rest'], pairs=r['pairs'],
                            cost=round(r['pairs'] * (r['a']['over_rest'] + r['b']['under_rest']) / 100, 2))
            if rm:
                out['rest_mid'] = rest_row(rm)
            if focus and len(mids) > 1:
                out['rest_mid_wide'] = rest_row(mids[1])
        return out

    def record_sheet(self, g, rec, stage='half'):
        """The sheet the final grades: the first PLAY push for the game (the half, or Q3 when the half was a
        read), else the first push of any kind. Read from the alerts table, which both watchers share and which
        holds exactly what went out; an alert pushed before sheets were kept is rebuilt from its suggestions row.
        Falls back to this watcher's own pushes when the table cannot be reached. None when nothing was pushed.
        A sport with a second window (the NBA's end of the third) has two records: stage 'half' is the half
        slot's alerts, stage 'q3' the q3 slot's; football's two slots are both the half stage."""
        two = (g['sport'] + '_q3') in engine.MODEL
        if store.enabled():
            alerts = store.read('alerts', {'select': 'kind,slot,sent_at,suggestion_at,sheet', 'game_id': f"eq.{g['id']}", 'order': 'sent_at'})
            if two:
                alerts = [a for a in alerts if (a.get('slot') == 'q3') == (stage == 'q3')]
            if alerts:
                pick = next((a for a in alerts if a.get('kind') == 'play'), alerts[0])
                sh = pick.get('sheet')
                if not sh:
                    sh = self.sheet_from_suggestion(g['id'], pick.get('suggestion_at'))
                if sh:
                    sh.setdefault('kind', pick.get('kind'))
                    sh.setdefault('slot', pick.get('slot'))
                    return sh
        if stage == 'q3':
            return rec.get('play_sheet_q3') or rec.get('sheet_q3')
        return rec.get('play_sheet') or rec.get('sheet')

    def flickers(self, game_id, T, pushed=None, stage='half'):
        """Everything that cleared the edge at any moment of this break, graded. Read from the suggestions table
        (every priced row, from both watchers), so both grade the same set; [] when it cannot be reached."""
        if not store.enabled():
            return []
        rows = store.read('suggestions', {'select': 'taken_at,phase,singles,mids,revs', 'game_id': f'eq.{game_id}',
                                          'phase': 'in.(q3end,early4)' if stage == 'q3' else 'in.(half,early3)', 'order': 'taken_at', 'limit': 2000})
        return flickers_from_rows(rows, T, pushed)

    def sheet_from_suggestion(self, game_id, taken_at):
        """A sheet for a push that was sent before sheets were kept: the plays the push named, from the
        suggestions row it came from (the first three cleared singles, one per line, and the best cleared middle)."""
        if not taken_at:
            return None
        rows = store.read('suggestions', {'select': 'total,home_spread,half_away,half_home,mu,sd,fair_line,market_line,singles,mids',
                                          'game_id': f'eq.{game_id}', 'taken_at': f'eq.{taken_at}', 'limit': 1})
        if not rows:
            return None
        r = rows[0]
        singles, mid = engine.chosen(dict(singles=r.get('singles') or [], mids=r.get('mids') or []))
        out = dict(at=taken_at, lead='single' if singles else 'mid' if mid else 'rest', rebuilt=True,
                   total=r.get('total'), spread=r.get('home_spread'), h1a=r.get('half_away'), h1h=r.get('half_home'),
                   mu=r.get('mu'), sd=r.get('sd'), fair=r.get('fair_line'), mkt=r.get('market_line'),
                   singles=[dict(kind=x['kind'], line=x['line'], price_c=x['price_c'], contracts=x['contracts'], cost=x['cost']) for x in singles],
                   mid=None, rest_mid=None)
        if mid:
            out['mid'] = dict(a_line=mid['a']['line'], a_price=mid['a']['price_c'], b_line=mid['b']['line'], b_price=mid['b']['price_c'], pairs=mid['pairs'], cost=mid['cost'])
        return out

    def settle(self, g, rec):
        """Grade what was pushed against the final score: a row in log/results.csv and the results table. A sport
        with a second window (the NBA's end of the third) gets that push graded on the same row, in the q3_ columns."""
        if rec.get('settled') or g['state'] != 'post' or not (rec.get('half_at') or rec.get('half_at_q3') or rec.get('slots') or rec.get('sheet') or rec.get('sheet_q3')):
            return
        sh = self.record_sheet(g, rec)
        two = (g['sport'] + '_q3') in engine.MODEL
        sh3 = self.record_sheet(g, rec, 'q3') if two else None
        T = g['away']['score'] + g['home']['score']
        auto = None
        if self.trader and rec.get('auto'):
            try:
                auto = self.trader.grade(g, rec, T)
            except Exception as e:
                print(f"auto grade {g['short']} failed: {e}")
        if not sh and not sh3:
            rec['settled'] = dict(at=now_iso(), nothing_pushed=True)
            return
        pre = rec.get('pre') or {}
        gr = grade_sheet(sh, T) if sh else None
        fl = self.flickers(g['id'], T, sh) if sh else []
        fair, mkt = (sh.get('fair'), sh.get('mkt')) if sh else (None, None)
        row = [now_iso(), g['sport'], g['short'], g['date_et'], f"{sh['h1a']}-{sh['h1h']}" if sh else '', (sh or {}).get('total', pre.get('total')), (sh or {}).get('spread', pre.get('home_spread')), fair, mkt,
               f"{g['away']['abbr']} {g['away']['score']}, {g['home']['abbr']} {g['home']['score']}", T,
               round(abs(T - fair), 1) if fair is not None else '', round(abs(T - mkt), 1) if mkt is not None else '',
               gr['n_plays'] if gr else 0, gr['cost'] if gr else '', gr['pnl'] if gr else '', gr['mid_pnl'] if gr and gr['mid_pnl'] is not None else '', gr['detail'] if gr else '',
               gr['rest_text'] if gr else '', gr['rest_pnl'] if gr and gr['rest_pnl'] is not None else '']
        gr3, fl3 = None, []
        if sh3:
            gr3 = grade_sheet(sh3, T)
            fl3 = self.flickers(g['id'], T, sh3, 'q3')
            f3, m3 = sh3.get('fair'), sh3.get('mkt')
            row += [f"{sh3['h1a']}-{sh3['h1h']}", f3, m3, gr3['n_plays'], gr3['cost'], gr3['pnl'], gr3['mid_pnl'] if gr3['mid_pnl'] is not None else '', gr3['detail'],
                    gr3['rest_text'], gr3['rest_pnl'] if gr3['rest_pnl'] is not None else '']
        else:
            row += [''] * 10
        os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
        upgrade_results_csv(RESULTS_PATH)
        newfile = not os.path.exists(RESULTS_PATH)
        with open(RESULTS_PATH, 'a', newline='') as f:
            wr = csv.writer(f)
            if newfile:
                wr.writerow(RESULTS_COLUMNS)
            wr.writerow(row)
        rec['settled'] = dict(at=now_iso(), final_total=T, plays_pnl=gr['pnl'] if gr else None, mid_pnl=gr['mid_pnl'] if gr else None,
                              q3_plays_pnl=gr3['pnl'] if gr3 else None, q3_mid_pnl=gr3['mid_pnl'] if gr3 else None)
        if store.enabled():
            # same row, same column names (settled_utc becomes settled_at), blanks become nulls, plus the graded sheets
            db = {('settled_at' if k == 'settled_utc' else 'date_et' if k == 'date' else k): (None if v == '' else v) for k, v in zip(RESULTS_COLUMNS, row)}
            db['game_id'], db['sheet'], db['flickers'] = g['id'], sh, fl
            if sh3:
                db['sheet_q3'], db['flickers_q3'] = sh3, fl3
            store.write('results', [db], on_conflict='game_id')
        print(f"settled {g['short']}: final {T}, fair {fair}, market {mkt}, play {gr['pnl'] if gr else 0:+.0f}, middle {(gr or {}).get('mid_pnl') or 0:+.0f}"
              + (f"; end of 3rd: fair {sh3.get('fair')}, play {gr3['pnl']:+.0f}, middle {gr3['mid_pnl'] or 0:+.0f}" if gr3 else '')
              + (f"; auto {self.trader.mode()}: {auto['fills']} fills of {auto['orders']} orders, {auto['pnl']:+.0f}" if auto else ''))

    def log_row(self, g, rec, m, total, spread, quotes, sug, ev, ts=None, score=None):
        score = score or rec['half']
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        newfile = not os.path.exists(LOG_PATH)
        best_mid = sug['mids'][0] if sug['mids'] else None
        best_single = sug['singles'][0] if sug['singles'] else None
        with open(LOG_PATH, 'a', newline='') as f:
            w = csv.writer(f)
            if newfile:
                w.writerow(['time_utc', 'sport', 'game', 'date', 'event', 'phase', 'total', 'home_spread', 'half_away', 'half_home', 'mu', 'sd', 'fair_line',
                            'quotes', 'best_single', 'best_single_edge_c', 'best_mid', 'best_mid_edge_c', 'plays'])
            q = ' '.join(f"{k:g}:{v['y']}/{v['n']}" for k, v in sorted(quotes.items()))
            w.writerow([ts or now_iso(), g['sport'], g['short'], g['date_et'], ev.get('event_ticker'), rec.get('phase'), total, spread, score['away'], score['home'],
                        round(m.mu, 1), round(m.sd, 1), engine.fair_line(m), q,
                        f"{best_single['kind']} {best_single['line']} @{best_single['price_c']}" if best_single else '', round(100 * best_single['edge'], 1) if best_single else '',
                        f"Y{best_mid['a']['line']}@{best_mid['a']['price_c']}+N{best_mid['b']['line']}@{best_mid['b']['price_c']}" if best_mid else '', round(100 * best_mid['ev'], 1) if best_mid else '',
                        sum(1 for x in sug['mids'] + sug['singles'] if x['ok'])])

    def prune(self):
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=self.cfg['keep_days'])).isoformat()
        for k in [k for k, v in self.state['games'].items() if (v.get('last_seen') or '') < cutoff]:
            del self.state['games'][k]


def upgrade_results_csv(path=RESULTS_PATH):
    """log/results.csv was written with fewer columns before the end-of-third window existed. When the file's
    header is shorter than RESULTS_COLUMNS, rewrite it with the full header, old rows padded with blanks, so a
    row appended today lines up with the header. Nothing else about the old rows changes."""
    try:
        with open(path, newline='') as f:
            rows = list(csv.reader(f))
    except FileNotFoundError:
        return
    if not rows or rows[0] == RESULTS_COLUMNS or len(rows[0]) >= len(RESULTS_COLUMNS):
        return
    old_n = len(rows[0])
    tmp = path + '.tmp'
    with open(tmp, 'w', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(RESULTS_COLUMNS)
        for r in rows[1:]:
            wr.writerow(list(r[:old_n]) + [''] * (len(RESULTS_COLUMNS) - old_n))
    os.replace(tmp, path)


def grade_sheet(sh, T):
    """Grade a push's sheet against the final total T. The play is what the push led with: the first single
    (the rest are backups, one or the other, never a stack), or the middle when the push led with one. The
    middle is also graded on its own, and a read's resting middle as a what-if. Same rule as app/lib/desk.js
    gradeSheet(), so every screen and the results table agree."""
    singles = sh.get('singles') or []
    lead = sh.get('lead') or ('single' if singles else 'mid' if sh.get('mid') else 'rest')
    detail, options = [], []
    for i, x in enumerate(singles):
        win = T > x['line'] if x['kind'] == 'over' else T < x['line']
        p = round((x['contracts'] - x['cost']) if win else -x['cost'], 2)
        options.append(dict(kind=x['kind'], line=x['line'], price_c=x['price_c'], contracts=x['contracts'], cost=x['cost'], win=win, pnl=p, play=i == 0 and lead == 'single'))
        detail.append(f"{'' if i == 0 else 'alt '}{x['kind']} {x['line']:g}@{x['price_c']} {'W' if win else 'L'} {p:+.0f}")
    m, mid_pnl, mid_hit = sh.get('mid'), None, None
    if m:
        mid_hit = m['a_line'] < T < m['b_line']
        mid_pnl = round((2 * m['pairs'] - m['cost']) if mid_hit else (m['pairs'] - m['cost']), 2)
        detail.append(f"mid {m['a_line']:g}/{m['b_line']:g} {'HIT' if mid_hit else 'miss'} {mid_pnl:+.0f}")
    # the reverse middle: one leg pays on any final outside the hole, both lose inside it
    rv, rev_pnl, rev_hole = sh.get('rev'), None, None
    if rv:
        rev_hole = rv['a_line'] < T < rv['b_line']
        rev_pnl = round(-rv['cost'] if rev_hole else (rv['pairs'] - rv['cost']), 2)
        detail.append(f"rev {rv['a_line']:g}/{rv['b_line']:g} {'HOLE' if rev_hole else 'clear'} {rev_pnl:+.0f}")
    rm, rest_pnl, rest_hit = sh.get('rest_mid'), None, None
    if rm:
        rest_hit = rm['a_line'] < T < rm['b_line']
        rest_pnl = round((2 * rm['pairs'] - rm['cost']) if rest_hit else (rm['pairs'] - rm['cost']), 2)
    # the mismatch lane's shadow call, graded as a what-if (the first pick), never part of the play's P&L
    shot_pnl, shot_win = None, None
    for x in ((sh.get('shot') or {}).get('picks') or [])[:1]:
        shot_win = T > x['line'] if x['kind'] == 'over' else T < x['line']
        shot_pnl = round((x['contracts'] - x['cost']) if shot_win else -x['cost'], 2)
        detail.append(f"shot {x['kind']} {x['line']:g}@{x['price_c']} {'W' if shot_win else 'L'} {shot_pnl:+.0f}")
    if lead == 'mid' and m:
        pnl, cost, win = mid_pnl, round(m['cost'], 2), mid_hit
    elif lead == 'single' and options:
        pnl, cost, win = options[0]['pnl'], round(options[0]['cost'], 2), options[0]['win']
    elif lead == 'rev' and rv:
        pnl, cost, win = rev_pnl, round(rv['cost'], 2), not rev_hole
    else:
        pnl, cost, win = 0.0, 0.0, None
    return dict(lead=lead, pnl=round(pnl, 2), cost=cost, win=win, options=options, mid_pnl=mid_pnl, mid_hit=mid_hit,
                rev_pnl=rev_pnl, rev_hole=rev_hole, shot_pnl=shot_pnl, shot_win=shot_win,
                rest_pnl=rest_pnl, rest_hit=rest_hit, n_plays=len(singles) + (1 if m else 0) + (1 if rv else 0), detail='; '.join(detail),
                rest_text=f"over {rm['a_line']:g}@{rm['a_price']} / under {rm['b_line']:g}@{rm['b_price']} x{rm['pairs']}" if rm else '')


def flickers_from_rows(rows, T, pushed=None):
    """Every line that cleared the edge in any priced row of a half, graded against the final total T. One entry
    per distinct single (side and line), middle (both lines) or reverse middle, with when it first and last
    cleared, how many priced rows it cleared in, the best price and edge it showed and the size at that moment,
    whether it was in the push that was graded as the record, and what it would have done. These are what Today
    showed between the pushes: the answer to "the bets that came and went, did they hit"."""
    seen = {}
    pushed = pushed or {}
    was = set()
    for x in pushed.get('singles') or []:
        was.add(('single', x['kind'], float(x['line'])))
    if pushed.get('mid'):
        was.add(('mid', float(pushed['mid']['a_line']), float(pushed['mid']['b_line'])))
    if pushed.get('rev'):
        was.add(('rev', float(pushed['rev']['a_line']), float(pushed['rev']['b_line'])))
    n_rows = 0
    for r in sorted(rows or [], key=lambda r: r.get('taken_at') or ''):
        n_rows += 1
        ts = r.get('taken_at')
        for x in r.get('singles') or []:
            if not x.get('ok'):
                continue
            key = ('single', x['kind'], float(x['line']))
            e = seen.setdefault(key, dict(kind='single', side=x['kind'], line=float(x['line']), first=ts, last=ts, n=0, best_edge_c=-999))
            e['last'], e['n'] = ts, e['n'] + 1
            if 100 * x['edge'] > e['best_edge_c']:
                e.update(best_edge_c=round(100 * x['edge'], 1), price_c=x['price_c'], contracts=x['contracts'], cost=x['cost'], at=ts)
        for x in r.get('mids') or []:
            if not x.get('ok'):
                continue
            key = ('mid', float(x['a']['line']), float(x['b']['line']))
            e = seen.setdefault(key, dict(kind='mid', a_line=float(x['a']['line']), b_line=float(x['b']['line']), first=ts, last=ts, n=0, best_edge_c=-999))
            e['last'], e['n'] = ts, e['n'] + 1
            if 100 * x['ev'] > e['best_edge_c']:
                e.update(best_edge_c=round(100 * x['ev'], 1), a_price=x['a']['price_c'], b_price=x['b']['price_c'], pairs=x['pairs'], cost=x['cost'], at=ts)
        for x in r.get('revs') or []:
            if not x.get('ok'):
                continue
            key = ('rev', float(x['a']['line']), float(x['b']['line']))
            e = seen.setdefault(key, dict(kind='rev', a_line=float(x['a']['line']), b_line=float(x['b']['line']), first=ts, last=ts, n=0, best_edge_c=-999))
            e['last'], e['n'] = ts, e['n'] + 1
            if 100 * x['ev'] > e['best_edge_c']:
                e.update(best_edge_c=round(100 * x['ev'], 1), a_price=x['a']['price_c'], b_price=x['b']['price_c'], pairs=x['pairs'], cost=x['cost'], at=ts)
    out = []
    for key, e in seen.items():
        e['rows'] = n_rows
        e['pushed'] = key in was
        try:
            e['secs'] = max(0, int((dt.datetime.fromisoformat(e['last'].replace('Z', '+00:00')) - dt.datetime.fromisoformat(e['first'].replace('Z', '+00:00'))).total_seconds()))
        except Exception:
            e['secs'] = None
        if e['kind'] == 'single':
            e['win'] = T > e['line'] if e['side'] == 'over' else T < e['line']
            e['pnl'] = round((e['contracts'] - e['cost']) if e['win'] else -e['cost'], 2)
        elif e['kind'] == 'mid':
            e['win'] = e['a_line'] < T < e['b_line']
            e['pnl'] = round((2 * e['pairs'] - e['cost']) if e['win'] else (e['pairs'] - e['cost']), 2)
        else:
            e['win'] = not (e['a_line'] < T < e['b_line'])
            e['pnl'] = round((e['pairs'] - e['cost']) if e['win'] else -e['cost'], 2)
        out.append(e)
    out.sort(key=lambda e: e['first'] or '')
    return out


def results_rows(path=RESULTS_PATH):
    """Graded games: the Supabase results table when it is reachable (it holds what both the worker and the
    GitHub Actions backup graded, one row per game), log/results.csv otherwise."""
    if store.enabled():
        rows = store.read('results', {'select': '*', 'order': 'settled_at', 'limit': 10000})
        if rows:
            return rows
    try:
        # a header line that landed among the rows (a bad merge) is not a game
        return [r for r in csv.DictReader(open(path, newline='')) if r.get('settled_utc') != 'settled_utc']
    except FileNotFoundError:
        return []


def drift_lines(rows):
    """The live drift line per sport (Roadmap v2, S1): this season's graded games against the model's own
    second-half number, as a mean miss with its standard error. Rows from the results table carry the sheet
    (mu_model and the break score); CSV rows carry only the fair line, so they are scored against that and say
    so. Past 2 SE is the watch flag; the recency rule lives in scripts/drift.py."""
    by = {}
    for r in rows:
        try:
            T = float(r.get('final_total'))
        except (TypeError, ValueError):
            continue
        sh = r.get('sheet') if isinstance(r.get('sheet'), dict) else None
        if sh and sh.get('mu_model') is not None and sh.get('h1a') is not None and sh.get('h1h') is not None:
            resid, how = T - sh['h1a'] - sh['h1h'] - float(sh['mu_model']), 'model'
        else:
            try:
                resid, how = T - float(r.get('fair')), 'fair line'
            except (TypeError, ValueError):
                continue
        by.setdefault((r.get('sport'), how), []).append(resid)
    out = []
    for (sport, how), rs in sorted(by.items(), key=lambda kv: str(kv[0])):
        n = len(rs)
        mean = sum(rs) / n
        sd = (sum((x - mean) ** 2 for x in rs) / (n - 1)) ** 0.5 if n > 1 else 0.0
        se = sd / n ** 0.5 if n > 1 else 0.0
        z = mean / se if se else 0.0
        out.append(f"drift {sport}: finals vs the {how} {mean:+.1f} on {n} games ({z:+.1f} SE)" + (' <-- past 2 SE, watch' if abs(z) >= 2 and n >= 30 else ''))
    return out


def scorecard(path=RESULTS_PATH, rows=None):
    """Season to date: are the plays making money, and is the model closer to the final than the market?"""
    rows = results_rows(path) if rows is None else rows
    if not rows:
        return 'scorecard: nothing settled yet'
    f = lambda r, k: float(r[k]) if r.get(k) not in (None, '') else None
    played = [r for r in rows if f(r, 'plays_cost')]
    cost = sum(f(r, 'plays_cost') or 0 for r in played)
    pnl = sum(f(r, 'plays_pnl') or 0 for r in played)
    mids = [r for r in rows if f(r, 'mid_pnl') is not None]
    mid_pnl = sum(f(r, 'mid_pnl') for r in mids)
    both = [r for r in rows if f(r, 'model_err') is not None and f(r, 'mkt_err') is not None]
    closer = sum(1 for r in both if f(r, 'model_err') < f(r, 'mkt_err'))
    ties = sum(1 for r in both if f(r, 'model_err') == f(r, 'mkt_err'))
    rest = [r for r in rows if r.get('rest_mid_pnl') not in (None, '')]
    rest_pnl = sum(f(r, 'rest_mid_pnl') for r in rest)
    out = [f"scorecard: {len(rows)} halftimes graded, {len(played)} with a play: ${pnl:+.0f} on ${cost:.0f} risked ({100 * pnl / cost:+.1f}%)" if cost else
           f"scorecard: {len(rows)} halftimes graded, none with a play"]
    if mids:
        out.append(f"middles called: {len(mids)}, ${mid_pnl:+.0f}")
    if both:
        out.append(f"model closer to the final than the market in {closer} of {len(both)} ({ties} ties); mean miss model {sum(f(r, 'model_err') for r in both) / len(both):.1f}, market {sum(f(r, 'mkt_err') for r in both) / len(both):.1f}")
    if rest:
        out.append(f"resting middles (what-if, assumes both sides filled): {len(rest)} games, ${rest_pnl:+.0f}")
    q3 = [r for r in rows if r.get('q3_score') not in (None, '')]
    if q3:
        q3p = [r for r in q3 if f(r, 'q3_plays_cost')]
        c3 = sum(f(r, 'q3_plays_cost') or 0 for r in q3p); p3 = sum(f(r, 'q3_plays_pnl') or 0 for r in q3p)
        r3 = [r for r in q3 if r.get('q3_rest_mid_pnl') not in (None, '')]
        out.append(f"end of 3rd (NBA): {len(q3)} graded, {len(q3p)} with a play: ${p3:+.0f} on ${c3:.0f} risked" + (f" ({100 * p3 / c3:+.1f}%)" if c3 else '')
                   + (f"; resting middles what-if {len(r3)} games, ${sum(f(r, 'q3_rest_mid_pnl') for r in r3):+.0f}" if r3 else ''))
    out += drift_lines(rows)
    if store.enabled():
        try:   # the auto orders' own line (trade.py): shadow or live, fills at the break vs in play, P&L
            import trade
            line = trade.readout()
            if line and not line.startswith('auto: no'):
                out.append(line)
        except Exception as e:
            out.append(f'auto readout unavailable: {e}')
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--fixtures')
    ap.add_argument('--scorecard', action='store_true', help='print the season scorecard and exit')
    args = ap.parse_args()
    if args.scorecard:
        print(scorecard())
        return
    cfg = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {})
    desk = Desk(cfg, state, args.fixtures)
    if not args.fixtures and store.enabled():
        try:
            import held
            desk.holdings = held.by_event(held.holdings())
        except Exception as e:
            print(f'holdings unavailable: {e}')
    started = time.time()
    while True:
        active = desk.run_pass()
        save_json(STATE_PATH, desk.state)
        if args.once or not active or args.fixtures:
            break
        if time.time() - started > desk.cfg['max_poll_minutes'] * 60:
            print('poll window over')
            break
        desk._events = {}
        time.sleep(desk.cfg['poll_seconds'])
    print(f"done. pushes: {len(desk.pushed)}")
    if not args.fixtures:
        try:   # read-only pull of balance, positions and fills into Supabase; never blocks the watch
            import portfolio
            portfolio.sync()
        except Exception as e:
            print(f'portfolio sync failed: {e}')
    print(scorecard())


if __name__ == '__main__':
    main()
