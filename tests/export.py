"""scripts/export_desk.py against a fake PostgREST:
1. the private tables are never asked for, and the private columns and JSON keys never reach a file,
2. a slate is picked by date_et or by a 05:00 ET window, paged a thousand rows at a time,
3. a second run writes nothing when nothing changed; the quote tables are written once; --force rewrites."""
import sys, os, gzip, datetime as dt, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ['SUPABASE_URL'] = 'https://example.supabase.co'
os.environ['SUPABASE_SECRET_KEY'] = 'test'
import requests
from scripts import export_desk as ex

calls = []


class R:
    def __init__(self, data):
        self.status_code, self._d, self.text = 200, data, ''

    def json(self):
        return self._d


def fake_get(url, headers=None, timeout=None, params=None):
    table = url.rsplit('/', 1)[1]
    calls.append((table, dict(params)))
    first = params['offset'] == 0
    if table == 'suggestions':
        return R([dict(id=1, taken_at='2026-10-22T23:50:00+00:00', game_id='g1', date_et='2026-10-22', bankroll=3210.5, max_risk=80.26,
                       max_cost=240.79, held=[{'ticker': 'KXNFLTOTAL-1'}], singles=[{'kind': 'over', 'cost': 12.5}], mids=None)] if first else [])
    if table == 'alerts':
        return R([dict(id=1, sent_at='2026-10-23T01:00:00+00:00', game_id='g1', slot='half', kind='play',
                       sheet={'lead': 'mid', 'held': [{'t': 1}], 'held_miss': 9, 'mid': {'pairs': 3, 'notes': [{'held': 1, 'ok': True}]}})] if first else [])
    if table == 'quote_snapshots':
        n = params['offset']
        return R([dict(id=n + i, taken_at='2026-10-22T23:00:00+00:00', game_id='g1', strike=45.5 + i, yes_ask=50) for i in range(1000 if first else 7)])
    return R([])


requests.get = fake_get
ex.OUT = tempfile.mkdtemp()
day = dt.date(2026, 10, 22)

written = ex.export(day)
assert sorted(p.split(os.sep)[-2] for p in written) == ['alerts', 'quote_snapshots', 'suggestions'], written
asked = {t for t, _ in calls}
assert asked == set(ex.TABLES), asked
assert not asked & set(ex.NEVER)
where = {t: p for t, p in calls if p['offset'] == 0}
assert where['games']['date_et'] == 'eq.2026-10-22' and where['results']['date_et'] == 'eq.2026-10-22'
assert where['quote_snapshots']['and'] == '(taken_at.gte.2026-10-22T09:00:00+00:00,taken_at.lt.2026-10-23T09:00:00+00:00)', where['quote_snapshots']
assert where['alerts']['and'].startswith('(sent_at.gte.2026-10-22T09:00:00+00:00')
assert [p['offset'] for t, p in calls if t == 'quote_snapshots'] == [0, 1000]
print('export: six tables asked for by slate, the private ones never')

read = lambda t: gzip.open(os.path.join(ex.OUT, t, '2026-10-22.csv.gz'), 'rt', encoding='utf-8').read()
sug = read('suggestions')
assert sug.splitlines()[0] == 'id,taken_at,game_id,date_et,singles,mids', sug
for word in ('bankroll', 'max_risk', 'max_cost', 'held', '3210'):
    assert word not in sug, word
al = read('alerts')
assert 'held' not in al and 'pairs"":3' in al and 'ok"":true' in al, al
assert len(read('quote_snapshots').splitlines()) == 1008
print('export: bankroll, caps and the held block never reach a file')

assert ex.export(day) == []
assert len(ex.export(day, force=True)) == 3
# a changed small table is rewritten, a quote table is not
real = fake_get
def grown(url, **kw):
    r = real(url, **kw)
    t = url.rsplit('/', 1)[1]
    if t == 'suggestions' and kw['params']['offset'] == 0:
        r._d[0]['n_plays'] = 2
    if t == 'quote_snapshots' and kw['params']['offset'] == 1000:
        r._d.append(dict(id=9999, taken_at='2026-10-23T02:00:00+00:00', game_id='g2', strike=200.5, yes_ask=40))
    return r
requests.get = grown
w = ex.export(day)
assert [p.split(os.sep)[-2] for p in w] == ['suggestions'], w
assert 'n_plays' in read('suggestions') and len(read('quote_snapshots').splitlines()) == 1008
print('export: a changed small table is rewritten, the quote file stands')

# the gzip is deterministic, so an unchanged export is a no-op for git
a = open(os.path.join(ex.OUT, 'alerts', '2026-10-22.csv.gz'), 'rb').read()
ex.export(day, force=True)
assert a == open(os.path.join(ex.OUT, 'alerts', '2026-10-22.csv.gz'), 'rb').read()
print('export: ok')
