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
import engine, feeds, notify, store

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH, STATE_PATH, LOG_PATH = os.path.join(HERE, 'config.json'), os.path.join(HERE, 'state.json'), os.path.join(HERE, 'log', 'halftime_log.csv')
RESULTS_PATH = os.path.join(HERE, 'log', 'results.csv')
MIDS_KEPT = 40   # middles stored per priced row (plus any more that clear): all 230-odd ran 120 KB a row
RESULTS_COLUMNS = ['settled_utc', 'sport', 'game', 'date', 'half', 'total', 'home_spread', 'fair', 'mkt', 'final', 'final_total',
                   'model_err', 'mkt_err', 'n_plays', 'plays_cost', 'plays_pnl', 'mid_pnl', 'plays', 'rest_mid', 'rest_mid_pnl']
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
                center_model_pct={'nba': 25})
CENTER_2H_RANGE = {'nba': (70, 160)}   # a market center outside this (per sport, second-half points) is a bad read and is ignored


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

    # ---- one pass over both sports ----
    def run_pass(self):
        active = False
        seen = []
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
            for g in games:
                ph = feeds.phase(g)
                rec = self.state['games'][g['id']]
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
                elif ph == 'approaching':
                    active = True   # the half is minutes away: poll fast, and read nothing as a pregame line
                elif ph == 'post':
                    try:
                        self.settle(g, rec)
                    except Exception as e:  # grading must never block the watch
                        print(f"settle {g.get('short')} failed: {e}")
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
            h = hash(json.dumps(row, sort_keys=True, default=str))
            prev = self._db_games.get(g['id'])
            if prev and prev[0] == h and now - prev[1] < 600:
                continue
            self._db_games[g['id']] = (h, now)
            (lined if pre.get('total') else unlined).append(dict(row, last_seen=rec.get('last_seen'), updated_at=now_iso()))
        # Two writes per sport: a game with no pregame line on record sends no pre_* columns at all, so a watcher
        # that lost its state (or first saw the game in play) never nulls out the line the other watcher captured
        # before kickoff. One batch per sport, so a sport the games table does not accept yet (NBA before
        # supabase/004_nba.sql has run) is rejected on its own and never takes the other sports' rows down with it.
        for sport in sorted({r['sport'] for r in lined + unlined}):
            store.write('games', [r for r in lined if r['sport'] == sport], on_conflict='id')
            store.write('games', [r for r in unlined if r['sport'] == sport], on_conflict='id')

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

    def db_eval(self, ts, g, rec, m, total, spread, quotes, rows, sug, ev, sizing, held=None):
        """One suggestions row (the halftime_log row plus the full ranked singles and middles) and one
        quote_snapshots row per strike: Kalshi's bid and ask next to the model's fair probability and limits."""
        if not store.enabled():
            return
        # At a 5-second pace most passes see the same quotes. Write a priced row only when the quotes, score or
        # phase changed, or 30 seconds have passed, so Supabase keeps a full record without 3x the rows.
        key = (rec.get('phase'), rec['half']['away'], rec['half']['home'], total,
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
            phase=rec.get('phase'), total=total, home_spread=spread, half_away=rec['half']['away'], half_home=rec['half']['home'],
            away_score=g['away']['score'], home_score=g['home']['score'],   # the live score when priced: equal to the half by construction
            mu=round(m.mu, 2), sd=round(m.sd, 2), fair_line=engine.fair_line(m), market_line=feeds.kalshi_total_line(ev),
            best_single=f"{best_single['kind']} {best_single['line']} @{best_single['price_c']}" if best_single else None,
            best_single_edge_c=round(100 * best_single['edge'], 1) if best_single else None,
            best_mid=f"Y{best_mid['a']['line']}@{best_mid['a']['price_c']}+N{best_mid['b']['line']}@{best_mid['b']['price_c']}" if best_mid else None,
            best_mid_edge_c=round(100 * best_mid['ev'], 1) if best_mid else None,
            n_plays=sum(1 for x in sug['mids'] + sug['singles'] + (sug.get('revs') or []) if x['ok']),
            singles=sug['singles'], mids=sug['mids'][:max(MIDS_KEPT, sum(1 for x in sug['mids'] if x['ok']))],   # best first, every cleared one kept
            # reverse middles the same way (supabase/005_reverse.sql adds the column; written without it until then)
            revs=(sug.get('revs') or [])[:max(10, sum(1 for x in sug.get('revs') or [] if x['ok']))],
            held=held or [],   # the open positions on this total when priced, with the sell-or-hold verdict and the pairings (same file adds the column)
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
        if total:
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

    def market_center(self, g, ev, h1):
        """(expected second-half points from the market, weight the model keeps) for sports that center on the
        market; (None, 1.0) for the rest. The market center is Kalshi's implied full-game line at the half (the
        50-50 crossing of the ladder's bid-ask midpoints) minus the first-half points. A line the ladder cannot
        give, or one outside the sport's plausible range, leaves the model on its own center."""
        cmp = self.cfg.get('center_model_pct') or {}
        pct = cmp.get(g['sport']) if isinstance(cmp, dict) else None
        if pct is None or pct >= 100:
            return None, 1.0
        line = feeds.kalshi_total_line(ev)
        if line is None:
            return None, 1.0
        c = line - h1
        lo, hi = CENTER_2H_RANGE.get(g['sport'], (0, 10**6))
        if not lo <= c <= hi:
            return None, 1.0
        return c, pct / 100

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

    def evaluate(self, g, rec):
        hs = feeds.half_score(g)
        if hs is None:
            return
        away_pts, home_pts = hs
        rec['half'] = dict(away=away_pts, home=home_pts)
        live = (g['away']['score'], g['home']['score'])
        if live != (away_pts, home_pts):
            # Someone scored since the half. The halftime model no longer describes the game, so from here on
            # nothing is priced, logged or written: the newest suggestions row stays the last one priced at the
            # halftime score, and the app marks it stale by comparing it with the live score on the games row.
            # (Oct 17: a Q3 touchdown at 13:20 left "Under 35.5 at 27c" showing as a 10.7c edge for five minutes.)
            if not rec.get('moved_at'):
                rec['moved_at'] = now_iso()
                rec['moved'] = dict(away=live[0], home=live[1])
                print(f"{g['short']}: score moved from {away_pts}-{home_pts} to {live[0]}-{live[1]} after the half, pricing stopped")
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
        center, center_w = self.market_center(g, ev, away_pts + home_pts)
        self.first_half_box(g, rec)
        m = engine.HalfModel(g['sport'], total, spread, home_pts, away_pts, center=center, center_w=center_w)
        rows = engine.price_lines(m, list(quotes), 'fg', self.cfg['margin_c'] / 100)
        bank = float(self.cfg['bankroll'])
        # daily cap: plays already pushed today (by cost) count against day_cost_pct of bankroll
        day = self.state.setdefault('day_spend', {})
        spent = float(day.get(g['date_et'], 0))
        remaining = max(0.0, bank * self.cfg['day_cost_pct'] / 100 - spent)
        max_risk = min(bank * self.cfg['risk_pct'] / 100, remaining)
        max_cost = min(bank * self.cfg['cost_pct'] / 100, remaining)
        sug = engine.suggest(rows, quotes, self.cfg['order'], self.cfg['margin_c'] / 100, self.cfg['trust_pct'] / 100,
                             bank, max_risk, max_cost, (self.cfg['min_price_c'], self.cfg['max_price_c']), self.cfg.get('mid_loss_cap'))
        inp = dict(away=g['away']['abbr'], home=g['home']['abbr'], away_name=g['away']['short'] or g['away']['abbr'], home_name=g['home']['short'] or g['home']['abbr'], h1a=away_pts, h1h=home_pts)
        sizing = dict(bankroll=bank, max_risk=max_risk, max_cost=max_cost, margin=self.cfg['margin_c'] / 100, mid_loss=self.cfg.get('mid_loss_cap'),
                      near_pts=(self.cfg.get('rest_near_pts') or {}).get(g['sport'], 3.5))
        focus = 'middles' if g['sport'] in (self.cfg.get('middle_focus') or []) else None
        kind, head, text = engine.order_sheet(m, inp, rows, sug, sizing, focus=focus)
        plays = [x for x in sug['mids'] if x['ok']] + [x for x in sug['singles'] if x['ok']] + [x for x in sug.get('revs') or [] if x['ok']]
        # What you already own on this total, priced off the same ladder: sell or hold against fair, the middle
        # completion or the lay-off when that leg clears, a free completion when the ask allows one. On a read it
        # goes first (it is the actionable part) and lifts the push to high priority when there is something to do.
        held_lines, held_rows, held_act = self.held_block(ev, rows, quotes)
        if held_lines:
            text = ('\n'.join(held_lines) + '\n\n' + text) if (not plays and held_act) else (text + '\n\n' + '\n'.join(held_lines))
        ts = now_iso()
        rec.setdefault('half_at', ts)
        self.log_row(g, rec, m, total, spread, quotes, sug, ev, ts)
        self.db_eval(ts, g, rec, m, total, spread, quotes, rows, sug, ev, sizing, held=held_rows)
        sheet = self.sheet(g, m, total, spread, away_pts, home_pts, rows, sug, ev, sizing, rec)
        if held_rows:
            sheet['held'] = held_rows
        # Two pushes per game at most: one the first time it is seen at the half (as close to the end of Q2 as the
        # polling allows), one the first time it is seen after the Q3 kick while the score is still the
        # halftime score (the moved-score check above already returned otherwise). A PLAY goes out whenever
        # something clears; a read goes out per read_push, which maps a sport to an ntfy priority ('min' is
        # silent and only shows in the app's list).
        slot = 'q3' if rec.get('phase') == 'early3' else 'half'
        slots = rec.setdefault('slots', {})
        if slots.get(slot):
            rec['last_eval'] = now_iso()
            return
        when = 'half' if slot == 'half' else 'Q3'
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
            sent = notify.push(title, body, priority='high', tags='moneybag')
            slots[slot] = 'play'
            self.pushed.append(title)
            self.db_alert(ts, g, slot, 'play', 'high', title, body, ev, sent, sheet)
            # The game's record is the first PLAY push (the half, or Q3 when the half was a read). The alerts
            # table holds the same for both watchers; these are the fallback when it cannot be reached.
            rec.setdefault('play_sheet', sheet)
            rec.setdefault('sheet', sheet)
            top = ([x for x in sug['mids'] if x['ok']][:1] or [x for x in sug['singles'] if x['ok']][:1] or [x for x in sug.get('revs') or [] if x['ok']][:1])
            if top and not rec.get('counted_day'):
                day[g['date_et']] = round(spent + top[0]['cost'], 2)
                rec['counted_day'] = True
        elif read_pri != 'off' or held_act:
            if held_act:
                read_pri = 'high'   # something to do with a position you hold: this one buzzes whatever the sport's read setting
            body = text + f"\n\n{ev.get('event_ticker')}"
            if not self.claim_alert(ts, g, slot, 'update', read_pri, title, body, ev, sheet):
                slots[slot] = 'elsewhere'
                rec['last_eval'] = now_iso()
                return
            sent = notify.push(title, body, priority=read_pri)
            slots[slot] = 'read'
            self.pushed.append(title)
            self.db_alert(ts, g, slot, 'update', read_pri, title, body, ev, sent, sheet)
            rec.setdefault('sheet', sheet)
        rec['last_eval'] = now_iso()

    def held_block(self, ev, rows, quotes):
        """YOU HOLD lines for the open positions on this game's total, from self.holdings (held.holdings() rows,
        keyed by event ticker, which the worker refreshes once a minute from the Kalshi sync; a plain watch.py run
        loads them once at the start). Returns (lines, rows for the sheet, whether anything is actionable:
        a SELL verdict, a pairing or a lay-off that clears, or a free completion)."""
        hs = self.holdings.get(ev.get('event_ticker')) or []
        lines, kept, act = [], [], False
        for h in hs:
            k = next((k for k, v in quotes.items() if v.get('ticker') == h.get('ticker')), None)
            if k is None:
                continue
            hh = dict(h, strike=k)
            o = engine.held_options(rows, quotes, hh, self.cfg['margin_c'] / 100, self.cfg['order'], (self.cfg['min_price_c'], self.cfg['max_price_c']))
            if not o:
                continue
            if lines:
                lines.append('')
            lines += engine.held_lines(hh, o)
            kept.append(dict(ticker=h.get('ticker'), side=h['side'], strike=k, shares=int(h['shares']), paid_c=h['paid_c'], fee=h.get('fee'), options=o))
            act = act or bool(o.get('pair') or o.get('layoff') or o.get('free') or (o.get('sell') or {}).get('verdict') == 'SELL')
        return lines, kept, act

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
        out = dict(at=now_iso(), lead=lead, total=total, spread=spread, h1a=away_pts, h1h=home_pts, mu=round(m.mu, 2), sd=round(m.sd, 2),
                   mu_model=round(m.mu_model, 2), center=None if m.center is None else round(m.center, 2), center_w=m.center_w,
                   pace=(rec or {}).get('pace'),
                   fair=engine.fair_line(m), mkt=feeds.kalshi_total_line(ev),
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

    def record_sheet(self, g, rec):
        """The sheet the final grades: the first PLAY push for the game (the half, or Q3 when the half was a
        read), else the first push of any kind. Read from the alerts table, which both watchers share and which
        holds exactly what went out; an alert pushed before sheets were kept is rebuilt from its suggestions row.
        Falls back to this watcher's own pushes when the table cannot be reached. None when nothing was pushed."""
        if store.enabled():
            alerts = store.read('alerts', {'select': 'kind,slot,sent_at,suggestion_at,sheet', 'game_id': f"eq.{g['id']}", 'order': 'sent_at'})
            if alerts:
                pick = next((a for a in alerts if a.get('kind') == 'play'), alerts[0])
                sh = pick.get('sheet')
                if not sh:
                    sh = self.sheet_from_suggestion(g['id'], pick.get('suggestion_at'))
                if sh:
                    sh.setdefault('kind', pick.get('kind'))
                    sh.setdefault('slot', pick.get('slot'))
                    return sh
        return rec.get('play_sheet') or rec.get('sheet')

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
        """Grade what was pushed against the final score: a row in log/results.csv and the results table."""
        if rec.get('settled') or g['state'] != 'post' or not (rec.get('half_at') or rec.get('slots') or rec.get('sheet')):
            return
        sh = self.record_sheet(g, rec)
        if not sh:
            rec['settled'] = dict(at=now_iso(), nothing_pushed=True)
            return
        T = g['away']['score'] + g['home']['score']
        gr = grade_sheet(sh, T)
        fair, mkt = sh.get('fair'), sh.get('mkt')
        row = [now_iso(), g['sport'], g['short'], g['date_et'], f"{sh['h1a']}-{sh['h1h']}", sh['total'], sh['spread'], fair, mkt,
               f"{g['away']['abbr']} {g['away']['score']}, {g['home']['abbr']} {g['home']['score']}", T,
               round(abs(T - fair), 1) if fair is not None else '', round(abs(T - mkt), 1) if mkt is not None else '',
               gr['n_plays'], gr['cost'], gr['pnl'], gr['mid_pnl'] if gr['mid_pnl'] is not None else '', gr['detail'],
               gr['rest_text'], gr['rest_pnl'] if gr['rest_pnl'] is not None else '']
        os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
        newfile = not os.path.exists(RESULTS_PATH)
        with open(RESULTS_PATH, 'a', newline='') as f:
            wr = csv.writer(f)
            if newfile:
                wr.writerow(RESULTS_COLUMNS)
            wr.writerow(row)
        rec['settled'] = dict(at=now_iso(), final_total=T, plays_pnl=gr['pnl'], mid_pnl=gr['mid_pnl'])
        if store.enabled():
            # same row, same column names (settled_utc becomes settled_at), blanks become nulls, plus the graded sheet
            db = {('settled_at' if k == 'settled_utc' else 'date_et' if k == 'date' else k): (None if v == '' else v) for k, v in zip(RESULTS_COLUMNS, row)}
            db['game_id'], db['sheet'] = g['id'], sh
            store.write('results', [db], on_conflict='game_id')
        print(f"settled {g['short']}: final {T}, fair {fair}, market {mkt}, play {gr['pnl']:+.0f}, middle {gr['mid_pnl'] or 0:+.0f}")

    def log_row(self, g, rec, m, total, spread, quotes, sug, ev, ts=None):
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
            w.writerow([ts or now_iso(), g['sport'], g['short'], g['date_et'], ev.get('event_ticker'), rec.get('phase'), total, spread, rec['half']['away'], rec['half']['home'],
                        round(m.mu, 1), round(m.sd, 1), engine.fair_line(m), q,
                        f"{best_single['kind']} {best_single['line']} @{best_single['price_c']}" if best_single else '', round(100 * best_single['edge'], 1) if best_single else '',
                        f"Y{best_mid['a']['line']}@{best_mid['a']['price_c']}+N{best_mid['b']['line']}@{best_mid['b']['price_c']}" if best_mid else '', round(100 * best_mid['ev'], 1) if best_mid else '',
                        sum(1 for x in sug['mids'] + sug['singles'] if x['ok'])])

    def prune(self):
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=self.cfg['keep_days'])).isoformat()
        for k in [k for k, v in self.state['games'].items() if (v.get('last_seen') or '') < cutoff]:
            del self.state['games'][k]


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
    if lead == 'mid' and m:
        pnl, cost, win = mid_pnl, round(m['cost'], 2), mid_hit
    elif lead == 'single' and options:
        pnl, cost, win = options[0]['pnl'], round(options[0]['cost'], 2), options[0]['win']
    elif lead == 'rev' and rv:
        pnl, cost, win = rev_pnl, round(rv['cost'], 2), not rev_hole
    else:
        pnl, cost, win = 0.0, 0.0, None
    return dict(lead=lead, pnl=round(pnl, 2), cost=cost, win=win, options=options, mid_pnl=mid_pnl, mid_hit=mid_hit,
                rev_pnl=rev_pnl, rev_hole=rev_hole,
                rest_pnl=rest_pnl, rest_hit=rest_hit, n_plays=len(singles) + (1 if m else 0) + (1 if rv else 0), detail='; '.join(detail),
                rest_text=f"over {rm['a_line']:g}@{rm['a_price']} / under {rm['b_line']:g}@{rm['b_price']} x{rm['pairs']}" if rm else '')


def results_rows(path=RESULTS_PATH):
    """Graded games: the Supabase results table when it is reachable (it holds what both the worker and the
    GitHub Actions backup graded, one row per game), log/results.csv otherwise."""
    if store.enabled():
        rows = store.read('results', {'select': '*', 'order': 'settled_at', 'limit': 10000})
        if rows:
            return rows
    try:
        return list(csv.DictReader(open(path, newline='')))
    except FileNotFoundError:
        return []


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
