"""One-time backfill of log/halftime_log.csv into Supabase (games, suggestions, quote_snapshots), for the
halftimes the watcher priced before the mirror existed. Safe to run again: every write is an upsert.

The CSV kept Kalshi's asks but not its bids, so backfilled quote rows have yes_ask and no_ask and null bids.
The model side of each strike is rebuilt from the logged inputs (total, spread, halftime score), which is
exactly what the watcher computed at the time. Game ids come from ESPN's scoreboard for that date; if ESPN
cannot be reached the row is filed under a synthetic id built from the Kalshi event ticker.

Usage: python scripts/backfill_logs.py [--dry-run]   (needs SUPABASE_URL and SUPABASE_SECRET_KEY)
"""
import os, sys, csv, json, argparse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engine, feeds, store, watch

LOG = os.path.join(ROOT, 'log', 'halftime_log.csv')


def parse_quotes(s):
    out = {}
    for part in s.split():
        k, yn = part.split(':')
        y, n = yn.split('/')
        out[float(k)] = dict(y=int(y), n=int(n), yb=None, nb=None, ticker=None)
    return out


def market_line(quotes):
    pts = [(k, (q['y'] + (100 - q['n'])) / 200) for k, q in quotes.items() if q['y'] and q['n']]
    return feeds.implied_line(pts)


def resolve_games(rows):
    """(sport, date, event ticker) -> ESPN game dict, via the scoreboard for that date."""
    out, cache = {}, {}
    for r in rows:
        key = (r['sport'], r['date'], r['event'])
        if key in out:
            continue
        if (r['sport'], r['date']) not in cache:
            try:
                cache[(r['sport'], r['date'])] = feeds.espn_games(r['sport'], r['date'].replace('-', ''))
            except Exception as e:
                print(f"espn {r['sport']} {r['date']} unreachable ({e}); using synthetic ids")
                cache[(r['sport'], r['date'])] = []
        _, codes = feeds.ticker_date(r['event'])
        match = None
        for g in cache[(r['sport'], r['date'])]:
            ab, hb = g['away']['abbr'], g['home']['abbr']
            if g['date_et'] == r['date'] and codes in (ab + hb, hb + ab):
                match = g
                break
        out[key] = match
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    cfg = {**watch.DEFAULTS, **watch.load_json(watch.CONFIG_PATH, {})}
    rows = list(csv.DictReader(open(LOG, newline='')))
    games = resolve_games(rows)
    game_rows, sug_rows, snap_rows = {}, [], []
    for r in rows:
        g = games.get((r['sport'], r['date'], r['event']))
        away_abbr, home_abbr = r['game'].split(' @ ') if ' @ ' in r['game'] else (None, None)
        gid = g['id'] if g else f"csv:{r['event']}"
        half_a, half_h = int(r['half_away']), int(r['half_home'])
        total, spread = float(r['total']), float(r['home_spread'] or 0)
        if gid not in game_rows:
            post = bool(g) and g['state'] == 'post'
            game_rows[gid] = dict(id=gid, sport=r['sport'], name=g['name'] if g else r['game'], short=r['game'], date_et=r['date'],
                                  start_utc=g['start_utc'] if g else None, away_abbr=away_abbr, home_abbr=home_abbr,
                                  away_name=(g['away']['short'] or away_abbr) if g else away_abbr, home_name=(g['home']['short'] or home_abbr) if g else home_abbr,
                                  pre_total=total, pre_home_spread=spread, pre_source='log', pre_at=None, kalshi_total_event=r['event'],
                                  phase='post' if post else r['phase'], status=g['status'] if g else None,
                                  half_away=half_a, half_home=half_h, half_at=r['time_utc'],
                                  final_away=g['away']['score'] if post else None, final_home=g['home']['score'] if post else None,
                                  first_seen=r['time_utc'], last_seen=r['time_utc'], updated_at=watch.now_iso())
        quotes = parse_quotes(r['quotes'])
        m = engine.HalfModel(r['sport'], total, spread, half_h, half_a)
        priced = engine.price_lines(m, list(quotes), 'fg', cfg['margin_c'] / 100)
        bank = float(cfg['bankroll'])
        sug = engine.suggest(priced, quotes, cfg['order'], cfg['margin_c'] / 100, cfg['trust_pct'] / 100, bank,
                             bank * cfg['risk_pct'] / 100, bank * cfg['cost_pct'] / 100, (cfg['min_price_c'], cfg['max_price_c']))
        sug_rows.append(dict(taken_at=r['time_utc'], game_id=gid, sport=r['sport'], game=r['game'], date_et=r['date'], event_ticker=r['event'],
                             phase=r['phase'], total=total, home_spread=spread, half_away=half_a, half_home=half_h,
                             mu=float(r['mu']), sd=float(r['sd']), fair_line=float(r['fair_line']), market_line=market_line(quotes),
                             best_single=r['best_single'] or None, best_single_edge_c=float(r['best_single_edge_c']) if r['best_single_edge_c'] else None,
                             best_mid=r['best_mid'] or None, best_mid_edge_c=float(r['best_mid_edge_c']) if r['best_mid_edge_c'] else None,
                             n_plays=int(r['plays'] or 0), singles=sug['singles'], mids=sug['mids'],
                             bankroll=bank, max_risk=bank * cfg['risk_pct'] / 100, max_cost=bank * cfg['cost_pct'] / 100))
        for p in priced:
            q = quotes[p['line']]
            snap_rows.append(dict(taken_at=r['time_utc'], game_id=gid, event_ticker=r['event'], market_ticker=None, strike=p['line'], phase=r['phase'],
                                  yes_bid=None, yes_ask=q['y'], no_bid=None, no_ask=q['n'], p_over=p['p_over'], p_push=p['p_push'],
                                  over_take=p['over_take'], over_rest=p['over_rest'], under_take=p['under_take'], under_rest=p['under_rest']))
    print(f'{len(rows)} log rows -> {len(game_rows)} games, {len(sug_rows)} suggestions, {len(snap_rows)} quote snapshots'
          f" ({sum(1 for k in game_rows if k.startswith('csv:'))} games on synthetic ids)")
    if a.dry_run:
        print(json.dumps(store.clean(dict(games=list(game_rows.values())[:1], suggestions=sug_rows[:1], quote_snapshots=snap_rows[:2])), indent=1, default=str))
        return
    if not store.enabled():
        raise SystemExit('SUPABASE_URL and SUPABASE_SECRET_KEY are not set')
    ok = store.write('games', list(game_rows.values()), on_conflict='id')
    ok = store.write('suggestions', sug_rows, on_conflict='taken_at,game_id') and ok
    for i in range(0, len(snap_rows), 500):
        ok = store.write('quote_snapshots', snap_rows[i:i + 500], on_conflict='taken_at,game_id,strike') and ok
    print('backfill: done' if ok else 'backfill: some writes failed, see above')


if __name__ == '__main__':
    main()
