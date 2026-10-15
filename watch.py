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
import engine, feeds, notify

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH, STATE_PATH, LOG_PATH = os.path.join(HERE, 'config.json'), os.path.join(HERE, 'state.json'), os.path.join(HERE, 'log', 'halftime_log.csv')
DEFAULTS = dict(bankroll=3000, risk_pct=2.5, cost_pct=7.5, margin_c=3, trust_pct=50, order='taker', sports=['nfl', 'cfb'],
                read_push=['nfl'], realert_gain_c=2, poll_seconds=75, max_poll_minutes=22, keep_days=10, min_price_c=15, max_price_c=85, day_cost_pct=20)


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
                if ph == 'pre':
                    self.capture_pregame(g, rec)
                elif ph in ('half', 'early3'):
                    active = True
                    self.evaluate(g, rec)
                elif ph == 'approaching':
                    active = True
                    self.capture_pregame(g, rec, late=True)
        self.prune()
        return active

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
        inp = dict(away=g['away']['abbr'], home=g['home']['abbr'], h1a=away_pts, h1h=home_pts)
        text = engine.describe(m, inp, rows, sug, tickers={k: v.get('ticker') for k, v in quotes.items()})
        plays = [x for x in sug['mids'] if x['ok']] + [x for x in sug['singles'] if x['ok']]
        self.log_row(g, rec, m, total, spread, quotes, sug, ev)
        title = f"{g['away']['abbr']} {away_pts}, {g['home']['abbr']} {home_pts} at the half ({g['sport'].upper()})"
        alerted = rec.setdefault('alerted', {})
        new = []
        for x in plays:
            key = (f"mid-{x['a']['line']}-{x['b']['line']}" if 'a' in x else f"{x['kind']}-{x['line']}")
            edge_c = round(100 * (x['ev'] if 'a' in x else x['edge']), 1)
            if key not in alerted or edge_c >= alerted[key] + self.cfg['realert_gain_c']:
                alerted[key] = edge_c
                new.append(key)
        if new:
            if remaining < 20:
                text += f"\nDaily cap reached (${spent:.0f} suggested today): sizes above are scaled down."
            notify.push('PLAY: ' + title, text + f"\n{ev.get('event_ticker')}", priority='high', tags='moneybag')
            self.pushed.append(title)
            top = ([x for x in sug['mids'] if x['ok']][:1] or [x for x in sug['singles'] if x['ok']][:1])
            if top and not rec.get('counted_day'):
                day[g['date_et']] = round(spent + top[0]['cost'], 2)
                rec['counted_day'] = True
        elif g['sport'] in self.cfg['read_push'] and not rec.get('read_pushed'):
            notify.push('Halftime read: ' + title, text + f"\n{ev.get('event_ticker')}", priority='default')
            rec['read_pushed'] = True
            self.pushed.append(title)
        rec['last_eval'] = now_iso()

    def log_row(self, g, rec, m, total, spread, quotes, sug, ev):
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
            w.writerow([now_iso(), g['sport'], g['short'], g['date_et'], ev.get('event_ticker'), rec.get('phase'), total, spread, rec['half']['away'], rec['half']['home'],
                        round(m.mu, 1), round(m.sd, 1), engine.fair_line(m), q,
                        f"{best_single['kind']} {best_single['line']} @{best_single['price_c']}" if best_single else '', round(100 * best_single['edge'], 1) if best_single else '',
                        f"Y{best_mid['a']['line']}@{best_mid['a']['price_c']}+N{best_mid['b']['line']}@{best_mid['b']['price_c']}" if best_mid else '', round(100 * best_mid['ev'], 1) if best_mid else '',
                        sum(1 for x in sug['mids'] + sug['singles'] if x['ok'])])

    def prune(self):
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=self.cfg['keep_days'])).isoformat()
        for k in [k for k, v in self.state['games'].items() if (v.get('last_seen') or '') < cutoff]:
            del self.state['games'][k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--fixtures')
    args = ap.parse_args()
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


if __name__ == '__main__':
    main()
