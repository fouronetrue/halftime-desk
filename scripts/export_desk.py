"""Nightly export of the desk's own rows from Supabase into the repo, one gzipped CSV per table per slate
(data/desk/TABLE/DATE.csv.gz), so the Supabase free tier can be pruned later and the study tables live
where the fitters can read them. Run by .github/workflows/export.yml at 10:40 UTC; by hand:

    python scripts/export_desk.py --days 3            # the last three slates, skipping files already written
    python scripts/export_desk.py --date 2026-10-22   # one slate
    python scripts/export_desk.py --days 30 --force   # rewrite

A slate runs from 05:00 ET one day to 05:00 ET the next (a West Coast NBA final lands after midnight ET),
and is named for the day it started. games, suggestions and results pick rows by date_et; alerts by
sent_at; quote_snapshots and venue_quotes by taken_at.

The repo is public, so this never exports what is Nick's own: bets, positions, portfolio_snapshots,
desk_state (the bankroll), control, orders (shadow today, his real orders once live). From suggestions it
drops bankroll, max_risk, max_cost and held; inside every JSON column it drops any 'held' or 'held_miss'
key (the sheet carries the YOU HOLD block). Sized plays stay: they are already in log/ and the scorecard.

Small tables (games, suggestions, alerts, results) are rewritten when a day's rows changed, since a final
or a grade can land after the first export; the quote tables are written once and left alone.

Two tables are thinned, or the repo would grow 70 MB a month: quote_snapshots keeps every row at a break
(half, early3, q3end, early4), the two labelled pregame ladders (pre60 at T-60 and pre0, the close) and, from
the plain pregame history, the first poll of each hour per game plus the last poll before tip; suggestions keeps every row's numbers but the singles, mids and revs JSON only on the first
and last row of each game's break and on the row a push came from.

Two readouts ride along (scripts/readout.py), since this job is where the Supabase keys are: the shadow
auto-order summary per slate (data/desk/shadow/DATE.csv, counts and dollars from the orders table, never an
order) and the honest scorecard (data/desk/scorecard.md, the results table plus the pre-mirror games only
log/results.csv has, one row a game window)."""
import sys, os, csv, io, gzip, json, time, argparse, traceback, datetime as dt
from zoneinfo import ZoneInfo
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import requests
import store
from scripts import readout

ET = ZoneInfo('America/New_York')
OUT = os.path.join(ROOT, 'data', 'desk')
RESULTS_CSV = os.path.join(ROOT, 'log', 'results.csv')
PAGE = 1000
SLATE_HOUR = 5

# table -> (how its rows are picked for a slate, columns never exported, rewritten when changed); alerts before
# suggestions, since the rows a push came from keep their full JSON
TABLES = {
    'games': ('date_et', (), True),
    'alerts': ('sent_at', (), True),
    'suggestions': ('date_et', ('bankroll', 'max_risk', 'max_cost', 'held'), True),
    'results': ('date_et', (), True),
    'quote_snapshots': ('taken_at', (), False),
    'venue_quotes': ('taken_at', (), False),
}
HEAVY = ('singles', 'mids', 'revs')
NEVER = ('bets', 'positions', 'portfolio_snapshots', 'desk_state', 'control', 'orders')
PRIVATE_KEYS = ('held', 'held_miss')
ORDER = {'games': 'id', 'suggestions': 'taken_at,game_id', 'alerts': 'sent_at,game_id', 'results': 'settled_at,game_id',
         'quote_snapshots': 'taken_at,game_id,strike', 'venue_quotes': 'taken_at,game_id,venue,kind,strike'}


def scrub(obj):
    """A JSON value with every 'held' / 'held_miss' key removed, at any depth."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if k not in PRIVATE_KEYS}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def window(day):
    """UTC ISO bounds of the slate that starts on day at 05:00 ET."""
    start = dt.datetime.combine(day, dt.time(SLATE_HOUR), tzinfo=ET)
    end = start + dt.timedelta(days=1)
    return start.astimezone(dt.timezone.utc).isoformat(), end.astimezone(dt.timezone.utc).isoformat()


def query(table, where, order):
    """Every row the filter matches, paged through PostgREST (1,000 a page). A page that fails (a timeout, a 5xx
    while Supabase is busy) is asked for again twice before the slate is given up on."""
    rows, offset = [], 0
    while True:
        # not store.read: that swallows a failed read as "no rows", and a failed export should fail the run
        err = None
        for attempt in range(3):
            try:
                r = requests.get(f'{store._url()}/rest/v1/{table}', headers=store._headers(), timeout=90,
                                 params=dict(select='*', order=order, limit=PAGE, offset=offset, **where))
                if r.status_code < 300:
                    err = None
                    break
                err = f'{table} offset {offset}: HTTP {r.status_code} {r.text[:200]}'
                if r.status_code < 500:
                    break
            except Exception as e:
                err = f'{table} offset {offset}: {e}'
            time.sleep(3 * (attempt + 1))
        if err:
            raise RuntimeError(err)
        page = r.json()
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        offset += PAGE


def fetch(table, day):
    """Every row of the table for the slate."""
    by, _, _ = TABLES[table]
    if by == 'date_et':
        where = {'date_et': f'eq.{day.isoformat()}'}
    else:
        lo, hi = window(day)
        where = {'and': f'({by}.gte.{lo},{by}.lt.{hi})'}
    return query(table, where, ORDER[table])


def fetch_orders(day=None):
    """The orders table, one slate or all of it: read for the summaries only, never written out as rows."""
    where = {'date_et': f'eq.{day.isoformat()}'} if day else {}
    return query('orders', where, 'created_at,client_order_id')


def thin_quotes(rows):
    """Every row at a break and every labelled pregame ladder (pre60, pre0); from the plain pregame history, each
    game's first poll of the hour and its last poll."""
    first, last = {}, {}                       # per game and hour, the poll kept; per game, the close
    for r in rows:
        if r.get('phase') == 'pre':
            first.setdefault((r['game_id'], str(r['taken_at'])[:13]), r['taken_at'])
            last[r['game_id']] = max(last.get(r['game_id'], ''), r['taken_at'])
    out = []
    for r in rows:
        if r.get('phase') != 'pre' or r['taken_at'] in (first[(r['game_id'], str(r['taken_at'])[:13])], last[r['game_id']]):
            out.append(r)
    return out


def thin_suggestions(rows, alert_at):
    """Every row's numbers; the singles, mids and revs JSON only on the first and last row of each game's
    phase and on the rows pushes came from (alert_at: their suggestion_at values)."""
    first, last = {}, {}
    for r in rows:
        k = (r['game_id'], r.get('phase'))
        first.setdefault(k, r['taken_at'])
        last[k] = r['taken_at']
    out = []
    for r in rows:
        k = (r['game_id'], r.get('phase'))
        if r['taken_at'] in (first[k], last[k]) or r['taken_at'] in alert_at:
            out.append(r)
        else:
            out.append({c: (None if c in HEAVY else v) for c, v in r.items()})
    return out


def to_csv(table, rows):
    """The rows as CSV text: private columns out, JSON columns scrubbed and serialised, columns in a fixed order."""
    _, drop, _ = TABLES[table]
    cols = []
    for r in rows:
        for k in r:
            if k not in drop and k not in cols:
                cols.append(k)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(cols)
    for r in rows:
        out = []
        for k in cols:
            v = r.get(k)
            if isinstance(v, (dict, list)):
                v = json.dumps(scrub(v), separators=(',', ':'), sort_keys=True)
            out.append('' if v is None else v)
        w.writerow(out)
    return buf.getvalue()


def existing(path):
    try:
        if path.endswith('.gz'):
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                return f.read()
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return None


def put_text(path, text, force=False):
    """A plain text file (the summaries), written only when its content changed. True when written."""
    if existing(path) == text and not force:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return True


def export(day, force=False):
    """Write the slate's files; returns the list of paths written."""
    written, alert_at = [], set()
    for table, (_, _, rewrite) in TABLES.items():
        path = os.path.join(OUT, table, f'{day.isoformat()}.csv.gz')
        have = existing(path)
        if have is not None and not force and not rewrite:
            continue
        rows = fetch(table, day)
        if table == 'alerts':
            alert_at = {r.get('suggestion_at') for r in rows}
        if not rows:
            continue
        if table == 'quote_snapshots':
            rows = thin_quotes(rows)
        elif table == 'suggestions':
            rows = thin_suggestions(rows, alert_at)
        text = to_csv(table, rows)
        if have == text and not force:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # mtime 0 in the gzip header so an unchanged export is byte-identical and git sees no change
        with open(path, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as f:
            f.write(text.encode('utf-8'))
        written.append(path)
        print(f'{table} {day}: {len(rows)} rows')
    # the shadow summary: what the auto orders would have done this slate, as counts and dollars (never an order);
    # rewritten as touches and grades land, like the small tables
    summary = readout.shadow_rows(fetch_orders(day))
    if summary:
        path = os.path.join(OUT, 'shadow', f'{day.isoformat()}.csv')
        if put_text(path, readout.shadow_csv(summary), force):
            written.append(path)
            print(f"shadow {day}: " + ', '.join(f"{r['sport']} {r['mode']} {r['rest_orders']} resting orders on {r['games']} games, {r['rest_touched']} would fill, ${r['pnl']:+.0f}" for r in summary))
    return written


def csv_results(path=None):
    try:
        with open(path or RESULTS_CSV, newline='', encoding='utf-8') as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def scorecard(force=False):
    """The honest scorecard from everything graded (the whole results table, the CSV's pre-mirror games, every
    auto order), written to data/desk/scorecard.md when it changed; the text is returned and printed either way."""
    db_rows = query('results', {}, ORDER['results'])
    text = readout.scorecard_md(db_rows, csv_results(), fetch_orders())
    path = os.path.join(OUT, 'scorecard.md')
    wrote = put_text(path, text, force)
    print(text)
    return path if wrote else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=3, help='slates to check, ending with the one that closed last (default 3)')
    ap.add_argument('--date', help='one slate, YYYY-MM-DD')
    ap.add_argument('--force', action='store_true', help='rewrite files that already exist')
    a = ap.parse_args()
    if not store.enabled():
        print('SUPABASE_URL and SUPABASE_SECRET_KEY are not set; nothing exported')
        return 1
    for t in NEVER:
        assert t not in TABLES, t
    if a.date:
        days = [dt.date.fromisoformat(a.date)]
    else:
        # the last slate that has closed: today's started at 05:00 ET and is still open until tomorrow
        now = dt.datetime.now(ET)
        last = now.date() - dt.timedelta(days=1 if now.hour >= SLATE_HOUR else 2)
        days = [last - dt.timedelta(days=i) for i in range(a.days)][::-1]
    n, errors = 0, []
    for day in days:
        try:
            n += len(export(day, a.force))
        except Exception as e:   # one bad slate does not cost the others their export
            errors.append(f'{day}: {e}')
            traceback.print_exc()
    try:
        if scorecard(a.force):
            n += 1
    except Exception as e:
        errors.append(f'scorecard: {e}')
        traceback.print_exc()
    # what went wrong, in the repo, since the Actions log is not always readable from where the fix gets written
    log = os.path.join(OUT, 'export_errors.txt')
    if errors:
        put_text(log, f"export at {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC failed on:\n" + '\n'.join(errors) + '\n', force=True)
        print('\n'.join(errors))
    elif os.path.exists(log):
        os.remove(log)
    print(f'{n} file(s) written' if n else 'nothing new')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
