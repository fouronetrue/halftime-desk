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
or a grade can land after the first export; the quote tables are written once and left alone."""
import sys, os, csv, io, gzip, json, argparse, datetime as dt
from zoneinfo import ZoneInfo
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import requests
import store

ET = ZoneInfo('America/New_York')
OUT = os.path.join(ROOT, 'data', 'desk')
PAGE = 1000
SLATE_HOUR = 5

# table -> (how its rows are picked for a slate, columns never exported, rewritten when changed)
TABLES = {
    'games': ('date_et', (), True),
    'suggestions': ('date_et', ('bankroll', 'max_risk', 'max_cost', 'held'), True),
    'alerts': ('sent_at', (), True),
    'results': ('date_et', (), True),
    'quote_snapshots': ('taken_at', (), False),
    'venue_quotes': ('taken_at', (), False),
}
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


def fetch(table, day):
    """Every row of the table for the slate, paged through PostgREST (1,000 a page)."""
    by, _, _ = TABLES[table]
    if by == 'date_et':
        where = {'date_et': f'eq.{day.isoformat()}'}
    else:
        lo, hi = window(day)
        where = {'and': f'({by}.gte.{lo},{by}.lt.{hi})'}
    rows, offset = [], 0
    while True:
        # not store.read: that swallows a failed read as "no rows", and a failed export should fail the run
        r = requests.get(f'{store._url()}/rest/v1/{table}', headers=store._headers(), timeout=60,
                         params=dict(select='*', order=ORDER[table], limit=PAGE, offset=offset, **where))
        if r.status_code >= 300:
            raise RuntimeError(f'{table}: HTTP {r.status_code} {r.text[:200]}')
        page = r.json()
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        offset += PAGE


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
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return f.read()
    except OSError:
        return None


def export(day, force=False):
    """Write the slate's files; returns the list of paths written."""
    written = []
    for table, (_, _, rewrite) in TABLES.items():
        path = os.path.join(OUT, table, f'{day.isoformat()}.csv.gz')
        have = existing(path)
        if have is not None and not force and not rewrite:
            continue
        rows = fetch(table, day)
        if not rows:
            continue
        text = to_csv(table, rows)
        if have == text and not force:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # mtime 0 in the gzip header so an unchanged export is byte-identical and git sees no change
        with open(path, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as f:
            f.write(text.encode('utf-8'))
        written.append(path)
        print(f'{table} {day}: {len(rows)} rows')
    return written


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
    n = 0
    for day in days:
        n += len(export(day, a.force))
    print(f'{n} file(s) written' if n else 'nothing new')
    return 0


if __name__ == '__main__':
    sys.exit(main())
