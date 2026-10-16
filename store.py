"""Supabase mirror. Everything the watcher logs to the CSVs and state.json also lands in Supabase when
SUPABASE_URL and SUPABASE_SECRET_KEY are set. Without them every call here is a no-op and the watcher runs
exactly as before. A failed write prints one line and never blocks the watch; the CSVs stay the source of truth.

Tables are created by supabase/schema.sql. Writes go through PostgREST (the /rest/v1 endpoint) with the secret
key in the apikey header, which bypasses row level security. The secret key must never leave the worker."""
import os, json, time

try:
    import requests
except ImportError:  # the engine and tests work without it
    requests = None


def _url():
    return (os.environ.get('SUPABASE_URL') or '').rstrip('/')


def _key():
    return os.environ.get('SUPABASE_SECRET_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or ''


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
    body = json.dumps(clean(rows), default=str)
    err = 'unknown'
    for attempt in range(3):
        try:
            r = requests.post(f'{_url()}/rest/v1/{table}', params=params, data=body, headers=_headers(prefer), timeout=25)
            if r.status_code < 300:
                return True
            err = f'HTTP {r.status_code} {r.text[:240]}'
            if 400 <= r.status_code < 500:
                break  # a rejected row will not get better on retry
        except Exception as e:  # network hiccup, retry
            err = str(e)
        time.sleep(1.5 * (attempt + 1))
    print(f'supabase {table}: write of {len(rows)} rows failed ({err})')
    return False


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
