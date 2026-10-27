"""scripts/export_desk.py against a fake PostgREST:
1. the private tables are never asked for, and the private columns and JSON keys never reach a file,
2. a slate is picked by date_et or by a 05:00 ET window, paged a thousand rows at a time,
3. a second run writes nothing when nothing changed; the quote tables are written once; --force rewrites,
4. thinning: pregame quotes keep one poll an hour per game and the close with every strike, break rows all stay;
   suggestions keep the heavy JSON on a game's first and last row of a phase and the row a push came from."""
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
        # g1 at the half, five polls; the push came from the third
        return R([dict(id=i, taken_at=f'2026-10-22T23:5{i}:00+00:00', game_id='g1', phase='half', date_et='2026-10-22', mu=50 + i, bankroll=3210.5,
                       max_risk=80.26, max_cost=240.79, held=[{'ticker': 'KXNFLTOTAL-1'}], singles=[{'kind': 'over', 'cost': 12.5}], mids=[{'pairs': i}], revs=[])
                  for i in range(5)] if first else [])
    if table == 'alerts':
        return R([dict(id=1, sent_at='2026-10-23T01:00:00+00:00', game_id='g1', slot='half', kind='play', suggestion_at='2026-10-22T23:52:00+00:00',
                       sheet={'lead': 'mid', 'held': [{'t': 1}], 'held_miss': 9, 'mid': {'pairs': 3, 'notes': [{'held': 1, 'ok': True}]}})] if first else [])
    if table == 'orders':
        # a shadow night: a tight pair that fills both legs and a wide pair that fills one, on one NBA game; read for
        # the counts only, so the ticker, the ids, the strikes and the prices below must never reach a file
        if not first or params.get('date_et') not in (None, 'eq.2026-10-22'):
            return R([])
        def o(i, side, strike, price, reason, pair, status, phase=None, secs=None, pnl=None):
            return dict(client_order_id=f'deadbeef-{i:04d}-4000-8000-000000000000', created_at='2026-10-23T00:10:00+00:00', game_id='g1', sport='nba',
                        game='BOS @ DET', date_et='2026-10-22', event_ticker='KXNBATOTAL-26OCT22BOSDET', market_ticker=f'KXNBATOTAL-26OCT22BOSDET-{strike:g}',
                        strike=strike, side=side, action='buy', kind='rest', stage='half', price_c=price, count=50, cost=50 * price / 100, reason=reason,
                        pair=pair, mode='shadow', status=status, touch_phase=phase, touch_s=secs, pnl=pnl)
        return R([o(1, 'yes', 210.5, 46, 'rest_mid', '210.5/216.5', 'touched', 'half', 40, 27.0), o(2, 'no', 216.5, 50, 'rest_mid', '210.5/216.5', 'touched', 'live', 1900, -25.0),
                  o(3, 'yes', 206.5, 40, 'rest_mid wide', '206.5/220.5', 'expired'), o(4, 'no', 220.5, 44, 'rest_mid wide', '206.5/220.5', 'touched', 'q3end', 1700, -22.0)])
    if table == 'results':
        return R([dict(id=1, settled_at='2026-10-23T02:00:00+00:00', game_id='g1', sport='nba', game='BOS @ DET', date_et='2026-10-22', fair=228.5, mkt=230.0,
                       final_total=214, model_err=14.5, mkt_err=16.0, plays_cost=0.0, plays_pnl=0.0, rest_mid_pnl=12.0, sheet={'held': [{'t': 1}], 'mu_model': 112.0, 'h1a': 50, 'h1h': 55},
                       flickers=[])] if first else [])
    if table == 'quote_snapshots':
        n = params['offset']
        rows = []
        # pregame: g1 polled every 20 minutes for three hours, 4 strikes a poll; then the half, 3 polls
        for h in range(3):
            for m in (0, 20, 40):
                rows += [dict(id=0, taken_at=f'2026-10-22T1{h}:{m:02d}:00+00:00', game_id='g1', strike=45.5 + k, phase='pre', yes_ask=50) for k in range(4)]
        for m in (0, 5, 10):
            rows += [dict(id=0, taken_at=f'2026-10-23T01:{m:02d}:00+00:00', game_id='g1', strike=45.5 + k, phase='half', yes_ask=50) for k in range(4)]
        rows += [dict(id=0, taken_at='2026-10-22T20:00:00+00:00', game_id='g2', strike=200.5 + k, phase='pre', yes_ask=50) for k in range(1000 - len(rows))]
        for i, r in enumerate(rows):
            r['id'] = n + i
        return R(rows if first else [dict(id=n + i, taken_at='2026-10-22T23:00:00+00:00', game_id='g3', strike=45.5 + i, phase='half', yes_ask=50) for i in range(7)])
    return R([])


requests.get = fake_get
ex.OUT = tempfile.mkdtemp()
day = dt.date(2026, 10, 22)

written = ex.export(day)
assert sorted(p.split(os.sep)[-2] for p in written) == ['alerts', 'quote_snapshots', 'results', 'shadow', 'suggestions'], written
asked = {t for t, _ in calls}
assert asked == set(ex.TABLES) | {'orders'}, asked        # orders is read for the counts, never written out as rows
assert not (asked - {'orders'}) & set(ex.NEVER)
assert not set(os.listdir(ex.OUT)) & set(ex.NEVER), os.listdir(ex.OUT)
where = {t: p for t, p in calls if p['offset'] == 0}
assert where['games']['date_et'] == 'eq.2026-10-22' and where['results']['date_et'] == 'eq.2026-10-22'
assert where['quote_snapshots']['and'] == '(taken_at.gte.2026-10-22T09:00:00+00:00,taken_at.lt.2026-10-23T09:00:00+00:00)', where['quote_snapshots']
assert where['alerts']['and'].startswith('(sent_at.gte.2026-10-22T09:00:00+00:00')
assert [p['offset'] for t, p in calls if t == 'quote_snapshots'] == [0, 1000]
assert [t for t, p in calls if p['offset'] == 0].index('alerts') < [t for t, p in calls if p['offset'] == 0].index('suggestions')
print('export: six tables asked for by slate, the private ones never')

read = lambda t: gzip.open(os.path.join(ex.OUT, t, '2026-10-22.csv.gz'), 'rt', encoding='utf-8').read()
sug = read('suggestions')
assert sug.splitlines()[0] == 'id,taken_at,game_id,phase,date_et,mu,singles,mids,revs', sug
for word in ('bankroll', 'max_risk', 'max_cost', 'held', '3210'):
    assert word not in sug, word
al = read('alerts')
assert 'held' not in al and 'pairs"":3' in al and 'ok"":true' in al, al
import csv as _csv, io as _io
srows = list(_csv.DictReader(_io.StringIO(sug)))
assert [r['mu'] for r in srows] == ['50', '51', '52', '53', '54'], 'every row keeps its numbers'
assert [bool(r['mids']) for r in srows] == [True, False, True, False, True], [r['mids'] for r in srows]
assert srows[2]['mids'] == '[{"pairs":2}]' and srows[1]['singles'] == ''
qrows = list(_csv.DictReader(_io.StringIO(read('quote_snapshots'))))
g1pre = sorted({r['taken_at'] for r in qrows if r['game_id'] == 'g1' and r['phase'] == 'pre'})
assert g1pre == ['2026-10-22T10:00:00+00:00', '2026-10-22T11:00:00+00:00', '2026-10-22T12:00:00+00:00', '2026-10-22T12:40:00+00:00'], g1pre
assert sum(1 for r in qrows if r['game_id'] == 'g1' and r['phase'] == 'pre') == 16, 'the kept polls keep every strike'
assert sum(1 for r in qrows if r['game_id'] == 'g1' and r['phase'] == 'half') == 12 and sum(1 for r in qrows if r['game_id'] == 'g3') == 7
assert sum(1 for r in qrows if r['game_id'] == 'g2') == 1000 - 48, 'one pregame poll is its own hour and its own close'
print('export: bankroll, caps and the held block never reach a file; quotes and sheets thinned as written')

# the shadow summary: counts and dollars from the orders table, never an order
shadow = open(os.path.join(ex.OUT, 'shadow', '2026-10-22.csv'), encoding='utf-8').read()
from scripts import readout as ro
srows = list(_csv.DictReader(_io.StringIO(shadow)))
assert list(srows[0].keys()) == ro.SHADOW_COLS and len(srows) == 1, shadow
s = srows[0]
assert (s['sport'], s['mode'], s['games'], s['rest_orders'], s['rest_touched'], s['touched_break'], s['touched_play']) == ('nba', 'shadow', '1', '4', '3', '1', '2'), s
assert (s['middles'], s['middles_both'], s['middles_one'], s['pnl'], s['pnl_both'], s['pnl_lone']) == ('2', '1', '1', '-20.0', '2.0', '-22.0'), s
for word in ('KXNBA', 'deadbeef', 'BOS @ DET', '210.5', '216.5', '206.5', '220.5', 'client', 'ticker', 'strike', 'price'):
    assert word not in shadow, word
# the honest scorecard: the results table plus the CSV's own games, the held block never printed
ex.RESULTS_CSV = os.path.join(ex.OUT, 'results.csv')
with open(ex.RESULTS_CSV, 'w', newline='') as f:
    _csv.writer(f).writerows([['settled_utc', 'sport', 'game', 'date', 'fair', 'mkt', 'final_total', 'model_err', 'mkt_err', 'plays_cost', 'plays_pnl', 'rest_mid_pnl'],
                              ['2026-10-18T03:00:00+00:00', 'nfl', 'ARI @ LAR', '2026-10-18', '45.5', '44.5', '40', '5.5', '4.5', '64.93', '77.07', ''],
                              ['2026-10-23T02:00:00+00:00', 'nba', 'BOS @ DET', '2026-10-22', '228.5', '230.0', '214', '14.5', '16.0', '0.0', '0.0', '12.0']])
path = ex.scorecard()
assert path == os.path.join(ex.OUT, 'scorecard.md'), path
card = open(path, encoding='utf-8').read()
assert 'from the Supabase results table (1 games' in card and 'plus the 1 games only log/results.csv has' in card and '2 windows on 2 games' in card, card
assert '| Oct 18 to Oct 18 | NFL | 1 | 1 | $65 | $+77 |' in card and '| NBA | shadow | 1 | 1 | 4 | 3 | 1 | 1 of 2 | 0 | 1 | $-20 | $+27 | $-47 | $+2 | $-22 |' in card, card
assert '- NBA: finals vs the model -3.0 on 1 game' in card, card
for word in ('held', 'KXNBA', 'deadbeef', '210.5'):
    assert word not in card, word
assert ex.scorecard() is None, 'an unchanged scorecard is not rewritten'
print('export: the shadow summary and the scorecard carry counts and dollars only')

assert ex.export(day) == []
assert len(ex.export(day, force=True)) == 5
# a changed small table is rewritten, a quote table is not
real = fake_get
def grown(url, **kw):
    r = real(url, **kw)
    t = url.rsplit('/', 1)[1]
    if t == 'suggestions' and kw['params']['offset'] == 0:
        r._d[0]['n_plays'] = 2
    if t == 'quote_snapshots' and kw['params']['offset'] == 1000:
        r._d.append(dict(id=9999, taken_at='2026-10-23T02:00:00+00:00', game_id='g2', strike=200.5, phase='half', yes_ask=40))
    return r
requests.get = grown
before = read('quote_snapshots')
w = ex.export(day)
assert [p.split(os.sep)[-2] for p in w] == ['suggestions'], w
assert 'n_plays' in read('suggestions') and read('quote_snapshots') == before
print('export: a changed small table is rewritten, the quote file stands')

# the gzip is deterministic, so an unchanged export is a no-op for git
a = open(os.path.join(ex.OUT, 'alerts', '2026-10-22.csv.gz'), 'rb').read()
ex.export(day, force=True)
assert a == open(os.path.join(ex.OUT, 'alerts', '2026-10-22.csv.gz'), 'rb').read()
print('export: ok')
