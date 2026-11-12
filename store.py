"""Supabase mirror. Everything the watcher logs to the CSVs and state.json also lands in Supabase when
SUPABASE_URL and SUPABASE_SECRET_KEY are set. Without them every call here is a no-op and the watcher runs
exactly as before. A failed write prints one line and never blocks the watch; the CSVs stay the source of truth.

Tables are created by supabase/schema.sql. Writes go through PostgREST (the /rest/v1 endpoint) with the secret
key in the apikey header, which bypasses row level security. The secret key must never leave the worker."""
import os, re, json, time

try:
    import requests
except ImportError:  # the engine and tests work without it
    requests = None

_missing = set()   # (table, column) pairs already reported, so the schema warning prints once per run


def missing_column(text):
    """The column PostgREST could not find, from its PGRST204 message, or None."""
    m = re.search(r"Could not find the '([^']+)' column", text or '')
    return m.group(1) if m else None


def _url():
    """Project URL with a clean https:// scheme, whatever got pasted ('ttps://x', 'x.supabase.co', trailing slash)."""
    u = (os.environ.get('SUPABASE_URL') or '').strip().strip('"\'').rstrip('/')
    if not u:
        return ''
    host = u.split('://', 1)[1] if '://' in u else u
    return 'https://' + host


def _key():
    # stripped like the URL: a key pasted with a stray quote or newline is the usual reason writes fail
    return (os.environ.get('SUPABASE_SECRET_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip().strip('"\'')


def check():
    """One small read, for the worker's boot line: (ok, detail). A bad URL or key fails here, in plain words,
    instead of as a heartbeat that quietly stops."""
    if not enabled():
        return False, 'SUPABASE_URL or SUPABASE_SECRET_KEY is not set'
    try:
        r = requests.get(f'{_url()}/rest/v1/desk_state', params={'select': 'id', 'limit': 1}, headers=_headers(), timeout=20)
        if r.status_code < 300:
            return True, f"{_url().split('//', 1)[1].split('.')[0]} answers"
        return False, f'HTTP {r.status_code} {r.text[:120]}'
    except Exception as e:
        return False, str(e)[:160]


def enabled():
    return bool(_url() and _key() and requests)


def _headers(prefer=None):
    key = _key()
    h = {'apikey': key, 'Content-Type': 'application/json'}
    if key.startswith('eyJ'):  # legacy service_role JWT wants the bearer header too
        h['Authorization'] = f'Bearer {key}'
    if prefer:
        h['Prefer'] = prefer
    return h


def clean(obj):
    """JSON-safe copy: tuples to lists, floats rounded, NaN to null. Keeps jsonb columns small and valid."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, float):
        return None if obj != obj else round(obj, 4)
    return obj


def write(table, rows, on_conflict=None, ignore_duplicates=False):
    """Insert a list of row dicts. With on_conflict (a column or comma list), upsert on those columns: merge the
    new values in by default, or skip rows that already exist when ignore_duplicates is set (right for fills,
    which never change and whose source tag you may have edited). Every row must carry the same keys."""
    if not enabled() or not rows:
        return False
    prefer = 'return=minimal'
    params = {}
    if on_conflict:
        params['on_conflict'] = on_conflict
        prefer += ',resolution=' + ('ignore-duplicates' if ignore_duplicates else 'merge-duplicates')
    rows = clean(rows)
    known = {m[1] for m in _missing if isinstance(m, tuple) and m[0] == table}
    if known:   # columns the schema has already said it lacks: leave them out up front, no wasted request
        rows = [{k: v for k, v in row.items() if k not in known} for row in rows]
    err, tries = 'unknown', 0
    while tries < 3:
        tries += 1
        try:
            r = requests.post(f'{_url()}/rest/v1/{table}', params=params, data=json.dumps(rows, default=str), headers=_headers(prefer), timeout=25)
            if r.status_code < 300:
                return True
            err = f'HTTP {r.status_code} {r.text[:240]}'
            col = missing_column(r.text) if r.status_code == 400 else None
            if col and any(col in row for row in rows):
                # The schema is behind the code (a file in supabase/ not run yet). Write without that column rather
                # than lose the row, and say so once; the app shows what it can until the migration is run.
                if (table, col) not in _missing:
                    _missing.add((table, col))
                    print(f"supabase {table}: no column '{col}' yet (run the newest file in supabase/), writing without it")
                rows = [{k: v for k, v in row.items() if k != col} for row in rows]
                tries -= 1   # a retry without the column is not a failed attempt
                continue
            if 400 <= r.status_code < 500:
                if 'games_sport_check' in r.text and 'sport_check' not in _missing:
                    _missing.add('sport_check')
                    print('supabase games: the sport check does not accept this sport yet (run the newest sport migration in supabase/, 016_cbb.sql, once); until then its games, suggestions, alerts and results rows are not mirrored, the CSVs and pushes are unaffected')
                break  # a rejected row will not get better on retry
        except Exception as e:  # network hiccup, retry
            err = str(e)
        time.sleep(1.5 * tries)
    print(f'supabase {table}: write of {len(rows)} rows failed ({err})')
    return False


def claim(table, row, on_conflict, strict=False):
    """Insert row only if no row with the same on_conflict key exists. Returns False when another process
    already holds that key (so the caller should not act), True when this call inserted it. When Supabase is
    off or unreachable it returns True: a duplicate push beats a missed one. strict turns that around for a
    caller that must not act twice or act unrecorded (a live order): True only when this call inserted the row."""
    if not enabled():
        return not strict
    try:
        r = requests.post(f'{_url()}/rest/v1/{table}', params={'on_conflict': on_conflict},
                          data=json.dumps(clean([row]), default=str),
                          headers=_headers('return=representation,resolution=ignore-duplicates'), timeout=10)
        if r.status_code < 300:
            return bool(r.json())   # [] means the row already existed
        print(f"supabase {table}: claim failed (HTTP {r.status_code} {r.text[:200]}), {'not acting' if strict else 'acting anyway'}")
    except Exception as e:
        print(f"supabase {table}: claim failed ({e}), {'not acting' if strict else 'acting anyway'}")
    return not strict


def read(table, params):
    """GET rows as a list of dicts, [] on any failure. params are PostgREST filters, e.g. {'select': 'id', 'limit': 1}."""
    if not enabled():
        return []
    try:
        r = requests.get(f'{_url()}/rest/v1/{table}', params=params, headers=_headers(), timeout=25)
        if r.status_code < 300:
            return r.json()
        print(f'supabase {table}: read failed (HTTP {r.status_code} {r.text[:240]})')
    except Exception as e:
        print(f'supabase {table}: read failed ({e})')
    return []


def fetch_all(table, params, key, page=1000):
    """Every row the filters match, paged on the table's key (PostgREST hands back at most 1,000 rows a request),
    or None when any page could not be read. For a caller that must tell 'no rows' from 'could not read': the
    pilot's money walls stop an order on an unreadable ledger, they do not wave it through on an empty one."""
    if not enabled():
        return None
    rows, last = [], None
    for _ in range(200):
        q = dict(params, order=key, limit=page)
        if last is not None:
            q[key] = f'gt.{last}'
        try:
            r = requests.get(f'{_url()}/rest/v1/{table}', params=q, headers=_headers(), timeout=25)
        except Exception as e:
            print(f'supabase {table}: read failed ({e})')
            return None
        if r.status_code >= 300:
            print(f'supabase {table}: read failed (HTTP {r.status_code} {r.text[:240]})')
            return None
        got = r.json()
        if not isinstance(got, list):
            return None
        rows.extend(got)
        if len(got) < page:
            return rows
        last = got[-1].get(key)
        if last is None:
            return None
    return None
