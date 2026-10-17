"""Halftime Desk watcher.
Every run: read ESPN scoreboards, capture pregame lines for games not yet kicked off, and for games at the half
(or early third quarter) pull Kalshi's full-game total markets, price every strike with the second-half model,
and push a notification when a single leg or a middle clears the edge. Keeps polling inside the run while any game
is approaching or at the half, so a 5-minute cron still sees the whole halftime window.

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
RESULTS_COLUMNS = ['settled_utc', 'sport', 'game', 'date', 'half', 'total', 'home_spread', 'fair', 'mkt', 'final', 'final_total',
                   'model_err', 'mkt_err', 'n_plays', 'plays_cost', 'plays_pnl', 'mid_pnl', 'plays', 'rest_mid', 'rest_mid_pnl']
DEFAULTS = dict(bankroll=3000, risk_pct=2.5, cost_pct=7.5, margin_c=3, trust_pct=50, order='taker', sports=['nfl', 'cfb'],
                read_push={'nfl': 'default', 'cfb': 'default'}, poll_seconds=75, max_poll_minutes=22, keep_days=10, min_price_c=15, max_price_c=85, day_cost_pct=20)


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
        self._db_evals = {}   # game id -> (quote key, time written): skip identical priced rows inside 30 s
        self._db_games = {}   # game id -> (row hash, time sent), so Supabase only hears about games that changed

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
        for sport in self.cfg['sports']:
            try:
                games = self.games(sport)
            except Exception as e:
                print(f'espn {sport} unavailable: {e}')
                continue
            for g in games:
                ph = feeds.phase(g)
                rec = self.state['games'].setdefault(g['id'], dict(sport=sport, name=g['name'], date=g['date_et'], first_seen=now_iso()))
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
                    active = True
                    self.capture_pregame(g, rec, late=True)
                elif ph == 'post':
                    try:
                        self.settle(g, rec)
                    except Exception as e:  # grading must never block the watch
                        print(f"settle {g.get('short')} failed: {e}")
                seen.append((g, rec))
        self.prune()
        self.db_games(seen)
        return active

    # ---- Supabase mirror: the same facts the CSVs and state.json hold, one request per table per pass ----
    def db_games(self, seen):
        """Upsert the games this pass saw. A game is sent when anything about it changed, and at least every
        ten minutes so last_seen stays fresh."""
        if not store.enabled():
            return
        rows, now = [], time.time()
        for g, rec in seen:
            pre, half, post = rec.get('pre') or {}, rec.get('half') or {}, g['state'] == 'post'
            row = dict(id=g['id'], sport=g['sport'], name=g['name'], short=g['short'], date_et=g['date_et'], start_utc=g['start_utc'],
                       away_abbr=g['away']['abbr'], home_abbr=g['home']['abbr'],
                       away_name=g['away']['short'] or g['away']['abbr'], home_name=g['home']['short'] or g['home']['abbr'],
                       pre_total=pre.get('total'), pre_home_spread=pre.get('home_spread'), pre_source=pre.get('source'), pre_at=pre.get('at'),
                       kalshi_total_event=rec.get('kalshi_total_event'), phase=rec.get('phase'), status=g['status'],
                       half_away=half.get('away'), half_home=half.get('home'), half_at=rec.get('half_at'),
                       final_away=g['away']['score'] if post else None, final_home=g['home']['score'] if post else None,
                       first_seen=rec.get('first_seen'),
                       away_score=g['away']['score'], home_score=g['home']['score'], period=g['period'], clock=g['clock'], detail=g['detail'])
            h = hash(json.dumps(row, sort_keys=True, default=str))
            prev = self._db_games.get(g['id'])
            if prev and prev[0] == h and now - prev[1] < 600:
                continue
            self._db_games[g['id']] = (h, now)
            rows.append(dict(row, last_seen=rec.get('last_seen'), updated_at=now_iso()))
        store.write('games', rows, on_conflict='id')

    def db_eval(self, ts, g, rec, m, total, spread, quotes, rows, sug, ev, sizing):
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
            mu=round(m.mu, 2), sd=round(m.sd, 2), fair_line=engine.fair_line(m), market_line=feeds.kalshi_total_line(ev),
            best_single=f"{best_single['kind']} {best_single['line']} @{best_single['price_c']}" if best_single else None,
            best_single_edge_c=round(100 * best_single['edge'], 1) if best_single else None,
            best_mid=f"Y{best_mid['a']['line']}@{best_mid['a']['price_c']}+N{best_mid['b']['line']}@{best_mid['b']['price_c']}" if best_mid else None,
            best_mid_edge_c=round(100 * best_mid['ev'], 1) if best_mid else None,
            n_plays=sum(1 for x in sug['mids'] + sug['singles'] if x['ok']),
            singles=sug['singles'], mids=sug['mids'],
            bankroll=sizing['bankroll'], max_risk=sizing['max_risk'], max_cost=sizing['max_cost'])], on_conflict='taken_at,game_id')
        snaps = []
        for r in rows:
            q = quotes.get(r['line']) or {}
            snaps.append(dict(taken_at=ts, game_id=g['id'], event_ticker=ev.get('event_ticker'), market_ticker=q.get('ticker'),
                              strike=r['line'], phase=rec.get('phase'), yes_bid=q.get('yb'), yes_ask=q.get('y'), no_bid=q.get('nb'), no_ask=q.get('n'),
                              p_over=r['p_over'], p_push=r['p_push'], over_take=r['over_take'], over_rest=r['over_rest'],
                              under_take=r['under_take'], under_rest=r['under_rest']))
        store.write('quote_snapshots', snaps, on_conflict='taken_at,game_id,strike')

    def claim_alert(self, ts, g, slot, kind, priority, title, body, ev):
        """Reserve this game's slot in the alerts table before pushing, so the always-on worker and the GitHub
        Actions backup never both push the same alert. False means the other one already did."""
        return store.claim('alerts', dict(sent_at=now_iso(), game_id=g['id'], sport=g['sport'], slot=slot, kind=kind, priority=priority,
                                          title=title, body=body, event_ticker=ev.get('event_ticker'), channels=None, suggestion_at=ts),
                           on_conflict='game_id,slot')

    def db_alert(self, ts, g, slot, kind, priority, title, body, ev, sent):
        if not store.enabled():
            return
        store.write('alerts', [dict(sent_at=now_iso(), game_id=g['id'], sport=g['sport'], slot=slot, kind=kind, priority=priority,
                                    title=title, body=body, event_ticker=ev.get('event_ticker'), channels=', '.join(sent), suggestion_at=ts)],
                    on_conflict='game_id,slot')

    def capture_pregame(self, g, rec, late=False):
        """Lines at kickoff: ESPN odds when present, Kalshi's 50-50 strikes as the fallback. Kept fresh until kickoff."""
        pre = rec.setdefault('pre', {})
        if late and pre.get('total'):
            return
        spread, total = feeds.espn_lines(g)
        if total:
            pre.update(total=total, source='espn', at=now_iso())
            if spread is not None:
                pre['home_spread'] = spread
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

    def evaluate(self, g, rec):
        hs = feeds.half_score(g)
        if hs is None:
            return
        away_pts, home_pts = hs
        rec['half'] = dict(away=away_pts, home=home_pts)
        pre = rec.get('pre') or {}
        spread, total = feeds.espn_lines(g)
        total = pre.get('total') or total
        spread = pre.get('home_spread') if pre.get('home_spread') is not None else spread
        if (not total or spread is None) and not self.fixtures and not rec.get('tried_odds_endpoint'):
            rec['tried_odds_endpoint'] = True
            s2, t2 = feeds.espn_odds_endpoint(g['sport'], g['id'])
            total = total or t2
            spread = spread if spread is not None else s2
            if total:
                pre.update(total=total, source='espn-odds', at=now_iso())
                rec['pre'] = pre
            if spread is not None:
                pre['home_spread'] = spread
        if spread is None:
            spread = 0.0
        if not total:
            if not rec.get('noted_no_line'):
                print(f"{g['short']}: no pregame total found, skipping")
                rec['noted_no_line'] = True
            return
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
        m = engine.HalfModel(g['sport'], total, spread, home_pts, away_pts)
        rows = engine.price_lines(m, list(quotes), 'fg', self.cfg['margin_c'] / 100)
        bank = float(self.cfg['bankroll'])
        # daily cap: plays already pushed today (by cost) count against day_cost_pct of bankroll
        day = self.state.setdefault('day_spend', {})
        spent = float(day.get(g['date_et'], 0))
        remaining = max(0.0, bank * self.cfg['day_cost_pct'] / 100 - spent)
        max_risk = min(bank * self.cfg['risk_pct'] / 100, remaining)
        max_cost = min(bank * self.cfg['cost_pct'] / 100, remaining)
        sug = engine.suggest(rows, quotes, self.cfg['order'], self.cfg['margin_c'] / 100, self.cfg['trust_pct'] / 100,
                             bank, max_risk, max_cost, (self.cfg['min_price_c'], self.cfg['max_price_c']))
        inp = dict(away=g['away']['abbr'], home=g['home']['abbr'], away_name=g['away']['short'] or g['away']['abbr'], home_name=g['home']['short'] or g['home']['abbr'], h1a=away_pts, h1h=home_pts)
        sizing = dict(bankroll=bank, max_risk=max_risk, max_cost=max_cost, margin=self.cfg['margin_c'] / 100)
        kind, head, text = engine.order_sheet(m, inp, rows, sug, sizing)
        plays = [x for x in sug['mids'] if x['ok']] + [x for x in sug['singles'] if x['ok']]
        ts = now_iso()
        rec.setdefault('half_at', ts)
        self.log_row(g, rec, m, total, spread, quotes, sug, ev, ts)
        self.db_eval(ts, g, rec, m, total, spread, quotes, rows, sug, ev, sizing)
        if 'sheet' not in rec:
            rec['sheet'] = self.sheet(g, m, total, spread, away_pts, home_pts, rows, sug, ev, sizing)
        # Two pushes per game at most: one the first time it is seen at the half (as close to the end of Q2 as the
        # polling allows), one the first time it is seen after the Q3 kick while the score is still the
        # halftime score. A PLAY goes out whenever something clears; a read goes out per read_push, which maps a
        # sport to an ntfy priority ('min' is silent and only shows in the app's list).
        slot = 'q3' if rec.get('phase') == 'early3' else 'half'
        if slot == 'q3' and (g['away']['score'], g['home']['score']) != (away_pts, home_pts):
            rec['last_eval'] = now_iso()
            return   # someone scored since the half; the halftime model no longer describes the state
        slots = rec.setdefault('slots', {})
        if slots.get(slot):
            rec['last_eval'] = now_iso()
            return
        when = 'half' if slot == 'half' else 'Q3'
        title = f"{head} ({when}, {g['sport'].upper()})"
        rp = self.cfg['read_push']
        read_pri = (rp.get(g['sport']) if isinstance(rp, dict) else ('default' if g['sport'] in rp else 'off')) or 'off'
        if plays:
            if remaining < 20:
                text += f"\nDaily cap reached (${spent:.0f} suggested today): sizes above are scaled down."
            body = text + f"\n\n{ev.get('event_ticker')}"
            if not self.claim_alert(ts, g, slot, 'play', 'high', title, body, ev):
                slots[slot] = 'elsewhere'
                rec['last_eval'] = now_iso()
                return
            sent = notify.push(title, body, priority='high', tags='moneybag')
            slots[slot] = 'play'
            self.pushed.append(title)
            self.db_alert(ts, g, slot, 'play', 'high', title, body, ev, sent)
            top = ([x for x in sug['mids'] if x['ok']][:1] or [x for x in sug['singles'] if x['ok']][:1])
            if top and not rec.get('counted_day'):
                day[g['date_et']] = round(spent + top[0]['cost'], 2)
                rec['counted_day'] = True
        elif read_pri != 'off':
            body = text + f"\n\n{ev.get('event_ticker')}"
            if not self.claim_alert(ts, g, slot, 'update', read_pri, title, body, ev):
                slots[slot] = 'elsewhere'
                rec['last_eval'] = now_iso()
                return
            sent = notify.push(title, body, priority=read_pri)
            slots[slot] = 'read'
            self.pushed.append(title)
            self.db_alert(ts, g, slot, 'update', read_pri, title, body, ev, sent)
        rec['last_eval'] = now_iso()

    def sheet(self, g, m, total, spread, away_pts, home_pts, rows, sug, ev, sizing):
        """What the first push said, kept so the final can grade it: cleared plays at their prices and sizes, the
        resting middle when nothing cleared (graded as a what-if), and the model and market fair lines."""
        singles, mid = engine.chosen(sug)
        out = dict(at=now_iso(), total=total, spread=spread, h1a=away_pts, h1h=home_pts, mu=round(m.mu, 2), sd=round(m.sd, 2),
                   fair=engine.fair_line(m), mkt=feeds.kalshi_total_line(ev),
                   singles=[dict(kind=s['kind'], line=s['line'], price_c=s['price_c'], contracts=s['contracts'], cost=s['cost']) for s in singles],
                   mid=None, rest_mid=None)
        if mid:
            out['mid'] = dict(a_line=mid['a']['line'], a_price=mid['a']['price_c'], b_line=mid['b']['line'], b_price=mid['b']['price_c'], pairs=mid['pairs'], cost=mid['cost'])
        else:
            rp = engine.rest_plan(m, rows, 'fg', sizing['margin'], sizing['bankroll'], sizing['max_risk'], sizing['max_cost'])
            rm = rp.get('middle')
            if rm:
                out['rest_mid'] = dict(a_line=rm['a']['line'], a_price=rm['a']['over_rest'], b_line=rm['b']['line'], b_price=rm['b']['under_rest'], pairs=rm['pairs'],
                                       cost=round(rm['pairs'] * (rm['a']['over_rest'] + rm['b']['under_rest']) / 100, 2))
        return out

    def settle(self, g, rec):
        """Grade the sheet against the final score and append a row to log/results.csv."""
        sh = rec.get('sheet')
        if not sh or rec.get('settled') or g['state'] != 'post':
            return
        T = g['away']['score'] + g['home']['score']
        # The push lists the best single first and the rest as backups, so only the first single counts as the play.
        # The middle is an alternative structure and is graded on its own.
        pnl, cost, detail = 0.0, 0.0, []
        for i, s in enumerate(sh['singles']):
            win = T > s['line'] if s['kind'] == 'over' else T < s['line']
            p = (s['contracts'] - s['cost']) if win else -s['cost']
            if i == 0:
                pnl += p; cost += s['cost']
            detail.append(f"{'' if i == 0 else 'alt '}{s['kind']} {s['line']:g}@{s['price_c']} {'W' if win else 'L'} {p:+.0f}")
        m, mid_pnl = sh.get('mid'), ''
        if m:
            hit = m['a_line'] < T < m['b_line']
            mid_pnl = round((2 * m['pairs'] - m['cost']) if hit else (m['pairs'] - m['cost']), 2)
            detail.append(f"mid {m['a_line']:g}/{m['b_line']:g} {'HIT' if hit else 'miss'} {mid_pnl:+.0f}")
        rm, rest_pnl = sh.get('rest_mid'), ''
        if rm:
            hit = rm['a_line'] < T < rm['b_line']
            rest_pnl = round((2 * rm['pairs'] - rm['cost']) if hit else (rm['pairs'] - rm['cost']), 2)
        fair, mkt = sh.get('fair'), sh.get('mkt')
        row = [now_iso(), g['sport'], g['short'], g['date_et'], f"{sh['h1a']}-{sh['h1h']}", sh['total'], sh['spread'], fair, mkt,
               f"{g['away']['abbr']} {g['away']['score']}, {g['home']['abbr']} {g['home']['score']}", T,
               round(abs(T - fair), 1) if fair is not None else '', round(abs(T - mkt), 1) if mkt is not None else '',
               len(sh['singles']) + (1 if m else 0), round(cost, 2), round(pnl, 2), mid_pnl, '; '.join(detail),
               f"over {rm['a_line']:g}@{rm['a_price']} / under {rm['b_line']:g}@{rm['b_price']} x{rm['pairs']}" if rm else '', rest_pnl]
        os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
        newfile = not os.path.exists(RESULTS_PATH)
        with open(RESULTS_PATH, 'a', newline='') as f:
            wr = csv.writer(f)
            if newfile:
                wr.writerow(RESULTS_COLUMNS)
            wr.writerow(row)
        rec['settled'] = dict(at=now_iso(), final_total=T, plays_pnl=round(pnl, 2), mid_pnl=mid_pnl)
        if store.enabled():
            # same row, same column names (settled_utc becomes settled_at), blanks become nulls, plus the graded sheet
            db = {('settled_at' if k == 'settled_utc' else 'date_et' if k == 'date' else k): (None if v == '' else v) for k, v in zip(RESULTS_COLUMNS, row)}
            db['game_id'], db['sheet'] = g['id'], sh
            store.write('results', [db], on_conflict='game_id')
        print(f"settled {g['short']}: final {T}, fair {fair}, market {mkt}, single {pnl:+.0f}, middle {mid_pnl or 0:+.0f}")

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
    out = [f"scorecard: {len(rows)} halftimes graded, {len(played)} with a single: ${pnl:+.0f} on ${cost:.0f} risked ({100 * pnl / cost:+.1f}%)" if cost else
           f"scorecard: {len(rows)} halftimes graded, none with a single"]
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
