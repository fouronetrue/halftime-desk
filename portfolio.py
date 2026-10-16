"""Kalshi portfolio sync, read-only by construction.

Pulls balance, positions and fills from Kalshi's portfolio API with your API key and writes them to Supabase
(portfolio_snapshots, positions, bets). The one signer in this file signs GET requests and nothing else, so
this code cannot place, cancel or change an order. tests/readonly.py fails the build if that ever changes.

Env (GitHub secrets): KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY (the PEM text, Ed25519 or RSA),
                      SUPABASE_URL, SUPABASE_SECRET_KEY. Without the Kalshi pair this module does nothing.
Usage:
  python portfolio.py             # fills since the newest one already in Supabase, then positions and balance
  python portfolio.py --backfill  # every fill Kalshi still serves (run once, the first time)
  python portfolio.py --dry-run   # print what would be written and write nothing
"""
import os, sys, json, base64, time, datetime as dt, argparse
import feeds, store

try:
    import requests
except ImportError:
    requests = None

BASE = os.environ.get('KALSHI_API_BASE') or feeds.KALSHI          # https://api.elections.kalshi.com/trade-api/v2
TOTAL_SERIES = {v['total'] for v in feeds.SERIES.values()}        # the series the watcher prices at the half


# ---------- signing (GET only) ----------
def load_key():
    pem = os.environ.get('KALSHI_PRIVATE_KEY') or ''
    if '\\n' in pem and '\n' not in pem:   # pasted with literal backslash-n
        pem = pem.replace('\\n', '\n')
    if not pem.strip():
        return None
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(pem.strip().encode() + b'\n', password=None)


def sign(key, ts_ms, path, method='GET'):
    """Base64 signature of timestamp + method + path, per Kalshi's docs. Only GET is ever signed here."""
    if method != 'GET':
        raise ValueError('portfolio.py signs GET requests only; it never places, cancels or changes orders')
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, ed25519, rsa
    msg = f'{ts_ms}{method}{path}'.encode()
    if isinstance(key, ed25519.Ed25519PrivateKey):
        sig = key.sign(msg)
    elif isinstance(key, rsa.RSAPrivateKey):
        sig = key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size), hashes.SHA256())
    else:
        raise ValueError(f'unsupported key type {type(key).__name__}; use an Ed25519 or RSA key')
    return base64.b64encode(sig).decode()


def enabled():
    return bool(os.environ.get('KALSHI_API_KEY_ID') and os.environ.get('KALSHI_PRIVATE_KEY') and requests)


def kalshi_get(path, params=None, key=None, tries=3):
    """Signed GET against the trade API. path is relative to BASE, e.g. '/portfolio/fills'."""
    key = key or load_key()
    full = BASE.split('://', 1)[1]
    sign_path = full[full.index('/'):] + path          # '/trade-api/v2/portfolio/fills', no query string
    last = None
    for i in range(tries):
        ts = str(int(time.time() * 1000))
        headers = {'KALSHI-ACCESS-KEY': os.environ['KALSHI_API_KEY_ID'], 'KALSHI-ACCESS-TIMESTAMP': ts,
                   'KALSHI-ACCESS-SIGNATURE': sign(key, ts, sign_path), 'User-Agent': 'halftime-desk/1.0'}
        try:
            r = requests.get(BASE + path, params=params, headers=headers, timeout=20)
            if r.status_code == 200:
                return r.json()
            last = f'HTTP {r.status_code} {r.text[:200]}'
            if r.status_code in (401, 403):
                break   # a bad key will not get better on retry
        except Exception as e:
            last = str(e)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'GET {path} failed: {last}')


# ---------- field helpers (Kalshi is mid-migration from cents to dollar strings) ----------
def dollars(m, key):
    """Dollar amount from '<key>_dollars' (fixed-point string) or the legacy '<key>' in cents."""
    v = m.get(key + '_dollars')
    if v is not None:
        try:
            return round(float(v), 4)
        except Exception:
            return None
    v = m.get(key)
    return round(v / 100, 4) if isinstance(v, (int, float)) else None


def cents(m, key):
    """Price in cents, half cents kept: '<key>_dollars' fixed-point string first, legacy integer '<key>' second."""
    v = m.get(key + '_dollars')
    if v is not None:
        try:
            return round(float(v) * 100, 2)
        except Exception:
            return None
    v = m.get(key)
    return round(float(v), 2) if isinstance(v, (int, float)) else None


def count(m, key='count'):
    v = m.get(key + '_fp')
    if v is None:
        v = m.get(key)
    try:
        return round(float(v), 2)
    except Exception:
        return None


def event_of(ticker):
    """KXNFLTOTAL-26OCT15BUFLAR-45 -> KXNFLTOTAL-26OCT15BUFLAR"""
    return ticker.rsplit('-', 1)[0] if ticker and ticker.count('-') >= 2 else ticker


def fee_of(f):
    for k in ('fee_cost', 'fee_dollars'):
        if f.get(k) not in (None, ''):
            try:
                return round(float(f[k]), 4)
            except Exception:
                pass
    v = f.get('fee')
    return round(v / 100, 4) if isinstance(v, (int, float)) else None


def when(m):
    t = m.get('created_time') or m.get('last_updated_ts')
    if isinstance(t, str):
        return t
    ts = m.get('ts')
    if isinstance(ts, (int, float)):
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).replace(microsecond=0).isoformat()
    return None


def parse_ts(s):
    try:
        t = dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


# ---------- source tagging ----------
def halftime_map():
    """event ticker -> (game id, first time the watcher priced it at the half), from Supabase and state.json."""
    out = {}
    for g in store.read('games', {'select': 'id,kalshi_total_event,half_at', 'half_at': 'not.is.null'}):
        if g.get('kalshi_total_event'):
            out[g['kalshi_total_event']] = (g['id'], g['half_at'])
    try:
        state = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state.json')))
        for gid, rec in state.get('games', {}).items():
            if rec.get('kalshi_total_event') and rec.get('half_at'):
                out.setdefault(rec['kalshi_total_event'], (gid, rec['half_at']))
    except Exception:
        pass
    return out


def tag(fill_row, halves):
    """halftime: a market the watcher priced at the half, filled after that moment. Everything else: personal.
    Sharp picks get tagged by hand (or by the email parser in week 4); the sync never overwrites a tag."""
    ev = fill_row['event_ticker'] or ''
    hit = halves.get(ev)
    filled, half_at = parse_ts(fill_row['filled_at']), parse_ts(hit[1]) if hit else None
    if hit and filled and half_at and filled >= half_at and ev.split('-')[0] in TOTAL_SERIES:
        return 'halftime', hit[0]
    return 'personal', (hit[0] if hit else None)


# ---------- pulls ----------
def fill_row(f):
    side = f.get('outcome_side') or f.get('side')
    yes_c = cents(f, 'yes_price')
    no_c = cents(f, 'no_price')
    price = yes_c if side == 'yes' else no_c
    n = count(f)
    return dict(fill_id=f.get('fill_id') or f.get('trade_id'), order_id=f.get('order_id'), ticker=f.get('ticker') or f.get('market_ticker'),
                event_ticker=event_of(f.get('ticker') or f.get('market_ticker')), outcome_side=side, book_side=f.get('book_side'),
                count=n, yes_price_c=yes_c, no_price_c=no_c, price_c=price,
                cost=round(n * price / 100, 2) if n is not None and price is not None else None,
                fee=fee_of(f), is_taker=f.get('is_taker'), filled_at=when(f))


def pull_fills(key, since_ts=None, limit=200, path='/portfolio/fills'):
    out, cursor = [], None
    for _ in range(200):
        params = {'limit': limit}
        if since_ts:
            params['min_ts'] = int(since_ts)
        if cursor:
            params['cursor'] = cursor
        data = kalshi_get(path, params, key)
        out.extend(data.get('fills') or [])
        cursor = data.get('cursor')
        if not cursor:
            break
    return out


def pull_all_fills(key, since_ts=None, backfill=False):
    """Recent fills, plus the archived ones from /historical/fills when backfilling. Same schema, same paging."""
    fills = pull_fills(key, since_ts)
    if backfill:
        try:
            fills += pull_fills(key, None, path='/historical/fills')
        except Exception as e:   # endpoint missing or empty for this account: the recent pull still stands
            print(f'historical fills skipped: {e}')
    seen, out = set(), []
    for f in fills:
        fid = f.get('fill_id') or f.get('trade_id')
        if fid and fid not in seen:
            seen.add(fid)
            out.append(f)
    return out


def pull_positions(key):
    rows = []
    for status in ('unsettled', 'settled'):
        cursor = None
        for _ in range(50):
            params = {'settlement_status': status, 'limit': 1000}
            if cursor:
                params['cursor'] = cursor
            data = kalshi_get('/portfolio/positions', params, key)
            for p in data.get('market_positions') or []:
                rows.append(dict(ticker=p['ticker'], event_ticker=event_of(p['ticker']), position=count(p, 'position'),
                                 total_traded=dollars(p, 'total_traded'), exposure=dollars(p, 'market_exposure'),
                                 realized_pnl=dollars(p, 'realized_pnl'), fees_paid=dollars(p, 'fees_paid'),
                                 settlement_status=status, last_updated=when(p), synced_at=now_iso()))
            cursor = data.get('cursor')
            if not cursor:
                break
    return rows


def pull_balance(key):
    b = kalshi_get('/portfolio/balance', None, key)
    return dict(taken_at=now_iso(), balance=dollars(b, 'balance'), portfolio_value=dollars(b, 'portfolio_value'))


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def newest_fill_ts():
    rows = store.read('bets', {'select': 'filled_at', 'order': 'filled_at.desc', 'limit': 1})
    if rows and rows[0].get('filled_at'):
        t = dt.datetime.fromisoformat(rows[0]['filled_at'].replace('Z', '+00:00'))
        return t.timestamp()
    return None


def sync(backfill=False, dry_run=False):
    if not enabled():
        print('portfolio sync: no Kalshi key in the environment, skipping')
        return None
    if not store.enabled() and not dry_run:
        print('portfolio sync: no Supabase key in the environment, skipping')
        return None
    key = load_key()
    since = None if backfill else newest_fill_ts()
    if since:
        since -= 86400   # a day of overlap; duplicates are ignored on insert
    fills = pull_all_fills(key, since, backfill)
    halves = halftime_map()
    rows = []
    for f in fills:
        r = fill_row(f)
        if not r['fill_id']:
            continue
        r['source'], r['game_id'] = tag(r, halves)
        r['source_auto'] = True
        r['ledger_id'] = None
        r['note'] = None
        r['synced_at'] = now_iso()
        rows.append(r)
    positions = pull_positions(key)
    balance = pull_balance(key)
    summary = dict(fills=len(rows), halftime=sum(1 for r in rows if r['source'] == 'halftime'), positions=len(positions),
                   balance=balance['balance'], portfolio_value=balance['portfolio_value'])
    if dry_run:
        print(json.dumps(dict(summary, sample_fills=rows[:3], sample_positions=positions[:3]), indent=1, default=str))
        return summary
    if rows:
        store.write('bets', rows, on_conflict='fill_id', ignore_duplicates=True)
    if positions:
        store.write('positions', positions, on_conflict='ticker')
    store.write('portfolio_snapshots', [balance], on_conflict='taken_at')
    print(f"portfolio sync: {summary['fills']} fills seen ({summary['halftime']} tagged halftime), {summary['positions']} positions, "
          f"balance ${summary['balance']}, portfolio ${summary['portfolio_value']}")
    return summary


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', action='store_true', help='pull every fill, not just the new ones')
    ap.add_argument('--dry-run', action='store_true', help='print, write nothing')
    a = ap.parse_args()
    sync(backfill=a.backfill, dry_run=a.dry_run)
