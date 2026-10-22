"""Pull the market's second-half total at halftime for past games from The Odds API's historical endpoints.

For every game in a halftime timetable (scripts/build_half_times.py) that the output does not have yet:
  1. the day's event list, once per game date, to find the Odds API event id (teams and start time must agree);
  2. the event's odds snapshot at halftime plus OFFSET minutes, market totals_h2, up to ten books (one region):
     10 credits a game. When no book shows a 2H line (the snapshot fell before the lines were posted) one more
     snapshot four minutes later is tried, then the game is recorded empty so it is not asked again.
The output grows one row per game as it goes, so a stopped run resumes where it left off. The run stops when
the credits it was allowed are spent or the account's remaining credits fall to the reserve the live desk needs.

Historical period markets exist from May 3, 2023, snapshots every five minutes, paid plans only. Needs
ODDS_API_KEY (.github/workflows/odds_history.yml passes the repo secret; this sandbox cannot reach the API).

Usage: python scripts/odds_history.py SPORT data/half_times_SPORT.csv data/odds_h2_SPORT.csv [--max-credits 9000]
       [--reserve 1500] [--offset-min 7]
"""
import os, sys, csv, json, time, argparse, datetime as dt
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import feeds

HIST = 'https://api.the-odds-api.com/v4/historical/sports/{key}'
FIELDS = ['game_id', 'date', 'away', 'home', 'event_id', 'req_utc', 'snap_utc', 'n_books', 'line_med', 'pinnacle_line', 'books', 'tries']


parse_h2 = feeds.parse_h2      # one parser for the live read and the history pull


def match_event(game, events, window_s=2 * 3600):
    """The historical event for a timetable row: same two teams (full names), start within two hours."""
    try:
        kick = dt.datetime.fromisoformat(str(game['kick_utc']).replace('Z', '+00:00')).timestamp()
    except Exception:
        kick = None
    best, best_s = None, 0.0
    for ev in events or []:
        s = min(feeds.sim(game['home_full'], ev.get('home_team')), feeds.sim(game['away_full'], ev.get('away_team')))
        if s < 2.0:
            continue
        if kick is not None:
            try:
                t = dt.datetime.fromisoformat(str(ev.get('commence_time')).replace('Z', '+00:00')).timestamp()
                if abs(t - kick) > window_s:
                    continue
            except Exception:
                continue
        if s > best_s:
            best, best_s = ev, s
    return best


def iso_plus(ts, minutes):
    t = dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00')) + dt.timedelta(minutes=minutes)
    return t.replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')


class Api:
    def __init__(self, key, sport, max_credits, reserve):
        self.key, self.sport, self.max, self.reserve = key, feeds.ODDS_SPORT[sport], max_credits, reserve
        self.spent, self.remaining, self.calls = 0, None, 0

    def allowed(self, cost=10):
        if self.spent + cost > self.max:
            return False
        return self.remaining is None or self.remaining - cost >= self.reserve

    def get(self, path, **params):
        r = requests.get(HIST.format(key=self.sport) + path, params=dict(apiKey=self.key, **params), timeout=30,
                         headers={'User-Agent': 'halftime-desk/1.0'})
        self.calls += 1
        last = r.headers.get('x-requests-last')
        if last not in (None, ''):
            self.spent += int(float(last))
        rem = r.headers.get('x-requests-remaining')
        if rem not in (None, ''):
            self.remaining = int(float(rem))
        if r.status_code != 200:
            raise RuntimeError(f'HTTP {r.status_code} {r.text[:160]}')
        return r.json()

    def events(self, at):
        return self.get('/events', date=at)

    def h2(self, event_id, at):
        return self.get(f'/events/{event_id}/odds', date=at, markets='totals_h2', bookmakers=','.join(feeds.ODDS_BOOKS), oddsFormat='american')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sport', choices=sorted(feeds.ODDS_SPORT))
    ap.add_argument('timetable')
    ap.add_argument('dst')
    ap.add_argument('--max-credits', type=int, default=9000)
    ap.add_argument('--reserve', type=int, default=1500, help='credits to leave for the live desk')
    ap.add_argument('--offset-min', type=int, default=7, help='minutes into the break for the snapshot')
    ap.add_argument('--limit', type=int, default=0, help='games to do this run (0 = as many as the credits allow)')
    a = ap.parse_args()
    key = (os.environ.get('ODDS_API_KEY') or '').strip()
    if not key:
        sys.exit('ODDS_API_KEY is not set')
    games = list(csv.DictReader(open(a.timetable)))
    done = set()
    if os.path.exists(a.dst):
        # a row with an event but no snapshot (a run that ran out of credits mid-game) is not done
        done = {r['game_id'] for r in csv.DictReader(open(a.dst)) if not r['event_id'] or int(r['tries'] or 0) > 0}
    todo = [g for g in games if g['game_id'] not in done]
    print(f'{len(games)} games in the timetable, {len(done)} already pulled, {len(todo)} to go; up to {a.max_credits} credits this run')
    api = Api(key, a.sport, a.max_credits, a.reserve)
    new = os.path.exists(a.dst) and os.path.getsize(a.dst) > 0
    out = open(a.dst, 'a', newline='')
    w = csv.DictWriter(out, fieldnames=FIELDS)
    if not new:
        w.writeheader()
    day_events = {}
    n_ok = n_empty = n_nomatch = 0
    for g in todo:
        if a.limit and n_ok + n_empty + n_nomatch >= a.limit:
            break
        if not api.allowed(12):
            print('credit budget reached, stopping here (resumable)')
            break
        day = g['date']
        if day not in day_events:
            first = min(x['kick_utc'] for x in games if x['date'] == day)
            try:
                day_events[day] = api.events(iso_plus(first, -30)).get('data') or []
            except Exception as e:
                print(f'{day}: event list failed ({e}), stopping')
                break
            time.sleep(0.25)
        ev = match_event(g, day_events[day])
        if not ev:
            n_nomatch += 1
            print(f"{g['game_id']}: no Odds API event found among {len(day_events[day])} that day")
            w.writerow(dict(game_id=g['game_id'], date=day, away=g['away'], home=g['home'], event_id='', req_utc='', snap_utc='', n_books=0,
                            line_med='', pinnacle_line='', books='{}', tries=0))
            out.flush()
            continue
        books, snap, tries, req = {}, '', 0, ''
        stopped = False
        for extra in (0, 4):
            if not api.allowed(10):
                stopped = True
                break
            req = iso_plus(g['half_utc'], a.offset_min + extra)
            try:
                res = api.h2(ev['id'], req)
            except Exception as e:
                print(f"{g['game_id']}: snapshot failed ({e})")
                break
            tries += 1
            snap = res.get('timestamp') or ''
            books = parse_h2(res.get('data'))
            time.sleep(0.25)
            if books:
                break
        if stopped and tries == 0:
            print('credit budget reached before the snapshot, stopping here (resumable)')
            break
        lines = sorted(v[0] for v in books.values())
        med = lines[len(lines) // 2] if lines else ''
        pin = books.get('pinnacle', [''])[0]
        w.writerow(dict(game_id=g['game_id'], date=day, away=g['away'], home=g['home'], event_id=ev['id'], req_utc=req, snap_utc=snap,
                        n_books=len(books), line_med=med, pinnacle_line=pin, books=json.dumps(books), tries=tries))
        out.flush()
        if books:
            n_ok += 1
        else:
            n_empty += 1
        if (n_ok + n_empty) % 25 == 0:
            print(f'  {n_ok} with a 2H line, {n_empty} without, {n_nomatch} unmatched; {api.spent} credits spent, {api.remaining} remaining')
    out.close()
    print(f'done: {n_ok} with a 2H line, {n_empty} without, {n_nomatch} unmatched; {api.calls} calls, {api.spent} credits spent, {api.remaining} remaining')


if __name__ == '__main__':
    main()
