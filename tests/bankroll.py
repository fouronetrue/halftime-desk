"""The bankroll from the live balance (watch.Desk.sync_bankroll), no network: store reads and writes are stood in.
1. No stored bankroll: the newest portfolio snapshot (cash plus positions at market) becomes the bankroll, the
   caps follow it, the trader's bank follows it, and the row is written.
2. A stored bankroll is used on load; it is not re-set until Tuesday, and on Tuesday only once.
3. A snapshot older than 36 hours or a number under $500 changes nothing. bankroll_auto false turns it off.
4. notify.push carries the market link as the tap target and an action button; feeds.kalshi_url builds it."""
import sys, os, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import watch, store, feeds, notify, trade

written, table = [], {}
def fake_read(t, params):
    if t == 'desk_state':
        return [dict(state=table['bankroll'], updated_at='x')] if 'bankroll' in table else []
    if t == 'portfolio_snapshots':
        return [table['snap']] if 'snap' in table else []
    return []
def fake_write(t, rows, on_conflict=None, ignore_duplicates=False):
    written.append((t, rows))
    if t == 'desk_state':
        table['bankroll'] = rows[0]['state']
    return True
store.enabled = lambda: True
store.read, store.write = fake_read, fake_write
now = dt.datetime.now(dt.timezone.utc)
# the first sync stamps set_on with today's date; the Tuesday reset below is faked as Oct 27, 2026, so on a real
# Oct 27 the test would see "already set today". Run the first sync on a faked Monday Oct 26 instead.
mon = dt.datetime(2026, 10, 26, 9, 0, tzinfo=dt.timezone.utc)
class MonDT(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return mon.astimezone(tz) if tz else mon.replace(tzinfo=None)
real_dt0 = watch.dt.datetime
watch.dt.datetime = MonDT

cfg = dict(watch.load_json(watch.CONFIG_PATH, {}), bankroll=3590)
d = watch.Desk(cfg, {})
d.trader = trade.Trader(cfg, 3590)
# 1. first run, fresh snapshot: cash 4100 plus positions 537 -> 4637
table['snap'] = dict(taken_at=(now - dt.timedelta(hours=2)).isoformat(), balance=4100.25, portfolio_value=536.9)
d.sync_bankroll()
assert d.cfg['bankroll'] == 4637 and d.trader.bank == 4637 and table['bankroll']['bankroll'] == 4637 and table['bankroll']['prev'] == 3590, (d.cfg['bankroll'], table.get('bankroll'))
assert abs(d.trader.cap_game() - 4637 * 0.005) < 1e-9, 'the auto cap follows the bankroll'
print('bankroll: set from the Kalshi balance on the first run, caps and the trader follow')

# 2. a new process loads the stored number and does not re-set it the same day (or any day but Tuesday)
d2 = watch.Desk(dict(cfg, bankroll=3590), {})
table['snap'] = dict(taken_at=(now - dt.timedelta(hours=1)).isoformat(), balance=9000, portfolio_value=0)
d2.sync_bankroll()
assert d2.cfg['bankroll'] == 4637, d2.cfg['bankroll']
# pretend it is Tuesday and the stored row was set on another day: it re-sets, once
tue = dt.datetime(2026, 10, 27, 9, 0, tzinfo=feeds.ET)
class FakeDT(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return tue.astimezone(tz) if tz else tue.astimezone(dt.timezone.utc).replace(tzinfo=None)
watch.dt.datetime = real_dt0
real_dt = watch.dt.datetime
watch.dt.datetime = FakeDT
table['snap'] = dict(taken_at=(tue - dt.timedelta(hours=1)).astimezone(dt.timezone.utc).isoformat(), balance=5000, portfolio_value=100)
d2._bank_checked = 0
d2.sync_bankroll()
assert d2.cfg['bankroll'] == 5100 and table['bankroll']['set_on'] == '2026-10-27', (d2.cfg['bankroll'], table['bankroll'])
table['snap'] = dict(taken_at=(tue - dt.timedelta(hours=1)).astimezone(dt.timezone.utc).isoformat(), balance=7000, portfolio_value=0)
d2._bank_checked = 0
d2.sync_bankroll()
assert d2.cfg['bankroll'] == 5100, 'Tuesday sets it once'
watch.dt.datetime = real_dt
print('bankroll: stored number used on load, re-set on Tuesday once')

# 3. stale or tiny snapshots change nothing; bankroll_auto false turns the whole thing off
del table['bankroll']
d3 = watch.Desk(dict(cfg, bankroll=3590), {})
table['snap'] = dict(taken_at=(now - dt.timedelta(hours=48)).isoformat(), balance=4100, portfolio_value=500)
d3.sync_bankroll()
assert d3.cfg['bankroll'] == 3590 and 'bankroll' not in table
table['snap'] = dict(taken_at=(now - dt.timedelta(hours=1)).isoformat(), balance=120, portfolio_value=0)
d3._bank_checked = 0
d3.sync_bankroll()
assert d3.cfg['bankroll'] == 3590 and 'bankroll' not in table
d4 = watch.Desk(dict(cfg, bankroll=3590, bankroll_auto=False), {})
table['snap'] = dict(taken_at=(now - dt.timedelta(hours=1)).isoformat(), balance=4100, portfolio_value=500)
d4.sync_bankroll()
assert d4.cfg['bankroll'] == 3590 and 'bankroll' not in table
print('bankroll: stale and tiny snapshots ignored, bankroll_auto false is off')

# 4. the market link on the push
assert feeds.kalshi_url('KXNBATOTAL-26OCT13NYKTOR') == 'https://kalshi.com/markets/kxnbatotal/event/kxnbatotal-26oct13nyktor'
assert feeds.kalshi_url(None) is None
calls = []
class R:
    status_code = 200
notify.requests = type('rq', (), {'post': staticmethod(lambda url, data=None, headers=None, timeout=0: (calls.append((url, data, headers)) or R()))})()
os.environ['NTFY_TOPIC'] = 'test-topic'
os.environ.pop('PUSHOVER_TOKEN', None)
notify.push('PLAY: x', 'body', priority='high', tags='moneybag', url='https://kalshi.com/markets/kxnbatotal/event/kxnbatotal-26oct13nyktor')
h = calls[-1][2]
assert h['Click'] == 'https://kalshi.com/markets/kxnbatotal/event/kxnbatotal-26oct13nyktor' and h['Actions'].startswith('view, Open market, https://kalshi.com/') and h['Priority'] == 'high', h
notify.push('UPDATE: y', 'body')
assert 'Click' not in calls[-1][2] and 'Actions' not in calls[-1][2]
print('push: the market link is the tap target and an action button; none without a url')
print('bankroll: ok')
