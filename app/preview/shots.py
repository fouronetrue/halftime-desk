"""Phone-width screenshots of every screen, against mock data, with no Supabase and no sign-in.

Starts `next dev` on a spare port with fake Supabase settings, seeds a fake session in the browser, answers every
PostgREST request from the mock tables below (filters, order, limit and the JSON-path aliases the screens use),
and saves one PNG per route to app/preview/out/. For look-and-feel sessions: run it, look at the PNGs, change
the app, run it again. Needs Playwright with Chromium (pip install playwright; playwright install chromium).

    python app/preview/shots.py            # every screen
    python app/preview/shots.py record     # one route
"""
import json, os, re, subprocess, sys, time, datetime as dt
from urllib.parse import urlparse, parse_qsl, unquote
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'out')
PORT = 3999
FAKE = 'https://mock.supabase.local'

now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
iso = lambda d: d.isoformat()
ago = lambda minutes: iso(now - dt.timedelta(minutes=minutes))
ET = dt.timezone(dt.timedelta(hours=-4))
today = now.astimezone(ET).strftime('%Y-%m-%d')
yday = (now.astimezone(ET) - dt.timedelta(days=1)).strftime('%Y-%m-%d')
sat = (now.astimezone(ET) - dt.timedelta(days=2)).strftime('%Y-%m-%d')


def single(kind, line, price_c, contracts, edge, ok=True):
    cost = round(contracts * price_c / 100 + 0.07 * contracts * price_c / 100 * (1 - price_c / 100), 2)
    return dict(kind=kind, line=line, price_c=price_c, contracts=contracts, cost=cost, edge=edge, ok=ok, eff=price_c / 100 + 0.02,
                fair_model=price_c / 100 + edge + 0.04, fair_used=price_c / 100 + edge + 0.02)


def mid(a_line, a_c, b_line, b_c, pairs, ev, ok=True, p_mid=0.22):
    c = (a_c + b_c) / 100 + 0.03
    cost = round(pairs * (a_c + b_c) / 100 + 1.4, 2)
    return dict(a=dict(line=a_line, price_c=a_c), b=dict(line=b_line, price_c=b_c), c=round(c, 4), pairs=pairs, cost=cost, ev=ev, ok=ok,
                p_mid=p_mid, p_mid_model=p_mid + 0.03, best=round(2 * pairs - cost, 2), worst=round(pairs - cost, 2))


def game(id, sport, away, home, away_name, home_name, phase, **kw):
    g = dict(id=id, sport=sport, name=f'{away_name} at {home_name}', short=f'{away} @ {home}', date_et=today, start_utc=ago(150),
             away_abbr=away, home_abbr=home, away_name=away_name, home_name=home_name, pre_source='espn', pre_at=ago(400),
             kalshi_total_event=f"KX{'NFL' if sport == 'nfl' else 'NCAAF'}TOTAL-26OCT20{away}{home}", phase=phase, status='STATUS_IN_PROGRESS',
             half_away=None, half_home=None, half_at=None, final_away=None, final_home=None, first_seen=ago(600), away_score=0, home_score=0,
             period=1, clock='15:00', detail='', last_seen=ago(0), updated_at=ago(0))
    g.update(kw)
    return g


def quotes(game_id, taken_at, fair, strikes, event):
    rows = []
    for k, (yb, y, nb, n) in strikes.items():
        p_over = max(0.03, min(0.97, 0.5 + (fair - k) * 0.07))
        rows.append(dict(taken_at=taken_at, game_id=game_id, event_ticker=event, market_ticker=f'{event}-{int(k + 0.5)}', strike=k, phase='half',
                         yes_bid=yb, yes_ask=y, no_bid=nb, no_ask=n, p_over=round(p_over, 4), p_push=0.0,
                         over_take=int(100 * p_over) - 4, over_rest=int(100 * p_over) - 7, under_take=int(100 * (1 - p_over)) - 4, under_rest=int(100 * (1 - p_over)) - 7))
    return rows


T = {}
T['games'] = [
    game('g1', 'nfl', 'BUF', 'LAR', 'Bills', 'Rams', 'half', status='STATUS_HALFTIME', half_away=13, half_home=7, half_at=ago(3), away_score=13, home_score=7,
         period=2, clock='0:00', detail='Half', pre_total=55.5, pre_home_spread=-3.5),
    game('g2', 'cfb', 'UTAH', 'COLO', 'Utah', 'Colorado', 'early3', half_away=13, half_home=0, half_at=ago(19), away_score=13, home_score=7,
         period=3, clock='13:20', detail='13:20 - 3rd', pre_total=45.5, pre_home_spread=3.0),
    game('g3', 'nfl', 'WSH', 'SF', 'Commanders', '49ers', 'pre', status='STATUS_SCHEDULED', start_utc=iso(now + dt.timedelta(hours=2)), pre_total=46.5, pre_home_spread=-7.0),
    game('g4', 'cfb', 'TULN', 'RICE', 'Tulane', 'Rice', 'live', away_score=7, home_score=3, period=1, clock='4:12', detail='4:12 - 1st', pre_total=49.5, pre_home_spread=9.5),
    game('g5', 'nfl', 'DAL', 'GB', 'Cowboys', 'Packers', 'post', status='STATUS_FINAL', half_away=0, half_home=17, half_at=ago(190), away_score=13, home_score=23,
         final_away=13, final_home=23, period=4, clock='0:00', detail='Final', pre_total=47.5, pre_home_spread=-6.5, date_et=yday),
]
for gid, (sp, aw, hm, ev, d) in {'g6': ('cfb', 'PSU', 'MICH', 'KXNCAAFTOTAL-26OCT18PSUMICH', sat), 'g7': ('cfb', 'TULN', 'RICE', 'KXNCAAFTOTAL-26OCT18TULNRICE', sat),
                                   'g8': ('nfl', 'LAC', 'KC', 'KXNFLTOTAL-26OCT19LACKC', yday), 'g9': ('cfb', 'FRES', 'SDSU', 'KXNCAAFTOTAL-26OCT18FRESSDSU', sat),
                                   'g10': ('nfl', 'BUF', 'LV', 'KXNFLTOTAL-26OCT19BUFLV', yday)}.items():
    T['games'].append(game(gid, sp, aw, hm, aw, hm, 'post', kalshi_total_event=ev, date_et=d, status='STATUS_FINAL'))

g1_sug = dict(taken_at=ago(0), game_id='g1', sport='nfl', game='BUF @ LAR', date_et=today, event_ticker='KXNFLTOTAL-26OCT20BUFLAR', phase='half', total=55.5, home_spread=-3.5,
              half_away=13, half_home=7, away_score=13, home_score=7, mu=27.4, sd=10.2, fair_line=47.5, market_line=45.5,
              best_single='over 42.5 @59', best_single_edge_c=4.6, best_mid='Y42.5@59+N48.5@45', best_mid_edge_c=3.4, n_plays=2,
              singles=[single('over', 42.5, 59, 121, 0.046), single('under', 51.5, 66, 82, 0.012, ok=False), single('over', 45.5, 47, 150, 0.004, ok=False)],
              mids=[mid(42.5, 59, 48.5, 45, 118, 0.034), mid(42.5, 59, 51.5, 34, 96, 0.021, ok=False, p_mid=0.31), mid(45.5, 47, 48.5, 45, 70, 0.011, ok=False, p_mid=0.12)],
              bankroll=3590, max_risk=89.75, max_cost=269.25)
g2_sug = dict(g1_sug, taken_at=ago(6), game_id='g2', sport='cfb', game='UTAH @ COLO', event_ticker='KXNCAAFTOTAL-26OCT20UTAHCOLO', phase='early3', total=45.5, home_spread=3.0,
              half_away=13, half_home=0, away_score=13, home_score=0, mu=22.1, sd=11.4, fair_line=35.5, market_line=38.5, best_single='under 35.5 @27', best_single_edge_c=10.7,
              n_plays=1, singles=[single('under', 35.5, 27, 88, 0.107)], mids=[mid(32.5, 60, 38.5, 42, 60, 0.012, ok=False)])
g5_sug = dict(g1_sug, taken_at=ago(188), game_id='g5', sport='nfl', game='DAL @ GB', date_et=yday, event_ticker='KXNFLTOTAL-26OCT19DALGB', total=47.5, home_spread=-6.5,
              half_away=0, half_home=17, away_score=0, home_score=17, fair_line=42.5, market_line=45.0, n_plays=2, singles=[single('under', 43.5, 44, 147, 0.052)], mids=[])
T['suggestions'] = [g1_sug, g2_sug, g5_sug]
T['quote_snapshots'] = quotes('g1', g1_sug['taken_at'], 47.5, {39.5: (74, 78, 21, 25), 42.5: (56, 59, 40, 44), 45.5: (44, 47, 52, 56), 48.5: (33, 37, 61, 65),
                                                                 51.5: (24, 28, 70, 74), 54.5: (13, 17, 81, 85)}, 'KXNFLTOTAL-26OCT20BUFLAR')
T['desk_state'] = [
    dict(id='worker', state={}, last_beat=ago(0), note='5 games: half 1, early3 1, live 1, pre 1, post 1; next pass 5s', updated_at=ago(0)),
    dict(id='pregame', state={'g3': dict(line=46.5, legs=[dict(side='over', k=45.5, c=53), dict(side='under', k=47.5, c=52)], at=ago(1))}, last_beat=ago(0), note='1 games', updated_at=ago(0)),
    dict(id='held', state={'KXNFLTOTAL-26OCT20WSHSF': dict(game='WSH @ SF', game_id='g3', sport='nfl', phase='pre', at=ago(1), built=[],
        legs=[dict(ticker='KXNFLTOTAL-26OCT20WSHSF-47', side='yes', strike=46.5, shares=100, paid_c=51.0, sell=dict(bid_c=55, pnl=2.74),
                   targets=[dict(kind='under', strike=49.5, numbers=3, target_c=50, ask_c=52), dict(kind='under', strike=50.5, numbers=4, target_c=52, ask_c=48)],
                   best=dict(kind='under', strike=50.5, price_c=48, numbers=4, lo=47, hi=50, pairs=100, cost=99.9, leg_cost=48.0, win=100.1, lose=-0.94, slack_c=5.6))]),
        'KXNFLTOTAL-26OCT20BUFLAR': dict(game='BUF @ LAR', game_id='g1', sport='nfl', phase='half', at=ago(1), built=[],
        legs=[dict(ticker='KXNFLTOTAL-26OCT20BUFLAR-53', side='no', strike=52.5, shares=60, paid_c=58.0, sell=None, targets=[], best=None)])}, last_beat=ago(0), note='2 events', updated_at=ago(0)),
]
T['positions'] = [
    dict(ticker='KXNFLTOTAL-26OCT20WSHSF-47', event_ticker='KXNFLTOTAL-26OCT20WSHSF', position=100, total_traded=51.0, exposure=51.0, realized_pnl=0, fees_paid=1.7, settlement_status='unsettled', last_updated=ago(40), synced_at=ago(1)),
    dict(ticker='KXNFLTOTAL-26OCT20BUFLAR-53', event_ticker='KXNFLTOTAL-26OCT20BUFLAR', position=-60, total_traded=34.8, exposure=34.8, realized_pnl=0, fees_paid=1.0, settlement_status='unsettled', last_updated=ago(4), synced_at=ago(1)),
    dict(ticker='KXNFLSPREAD-26OCT20WSHSF-SF7', event_ticker='KXNFLSPREAD-26OCT20WSHSF', position=40, total_traded=19.2, exposure=19.2, realized_pnl=0, fees_paid=0.6, settlement_status='unsettled', last_updated=ago(90), synced_at=ago(1)),
    dict(ticker='KXNFLRECYDS-26OCT20WSHSF-DEEBO60', event_ticker='KXNFLRECYDS-26OCT20WSHSF', position=25, total_traded=11.0, exposure=11.0, realized_pnl=0, fees_paid=0.4, settlement_status='unsettled', last_updated=ago(120), synced_at=ago(1)),
    dict(ticker='KXNFLTOTAL-26OCT19DALGB-44', event_ticker='KXNFLTOTAL-26OCT19DALGB', position=0, total_traded=64.9, exposure=0, realized_pnl=82.1, fees_paid=2.3, settlement_status='settled', last_updated=ago(300), synced_at=ago(1)),
    dict(ticker='KXNCAAFTOTAL-26OCT18FRESSDSU-50', event_ticker='KXNCAAFTOTAL-26OCT18FRESSDSU', position=0, total_traded=30.0, exposure=0, realized_pnl=69.5, fees_paid=2.4, settlement_status='settled', last_updated=ago(2000), synced_at=ago(1)),
    dict(ticker='KXNCAAFTOTAL-26OCT18TULNRICE-63', event_ticker='KXNCAAFTOTAL-26OCT18TULNRICE', position=0, total_traded=90.0, exposure=0, realized_pnl=-90.0, fees_paid=0, settlement_status='settled', last_updated=ago(2000), synced_at=ago(1)),
]
T['portfolio_snapshots'] = [dict(taken_at=ago(1), balance=4100.57, portfolio_value=536.72)]


def result(gid, sport, gm, date, half, total, spread, fair, mkt, final, ft, singles, m=None, rest=None, settled_min=200):
    sh = dict(at=ago(settled_min + 120), total=total, spread=spread, h1a=int(half.split('-')[0]), h1h=int(half.split('-')[1]), mu=20.0, sd=10.0, fair=fair, mkt=mkt, singles=singles, mid=m, rest_mid=rest)
    first = singles[0] if singles else None
    win = first and (ft > first['line'] if first['kind'] == 'over' else ft < first['line'])
    pnl = (first['contracts'] - first['cost'] if win else -first['cost']) if first else 0
    mp = None
    if m:
        hit = m['a_line'] < ft < m['b_line']
        mp = round((2 * m['pairs'] - m['cost']) if hit else (m['pairs'] - m['cost']), 2)
    rp = None
    if rest:
        hit = rest['a_line'] < ft < rest['b_line']
        rp = round((2 * rest['pairs'] - rest['cost']) if hit else (rest['pairs'] - rest['cost']), 2)
    return dict(settled_at=ago(settled_min), sport=sport, game=gm, date_et=date, half=half, total=total, home_spread=spread, fair=fair, mkt=mkt, final=final, final_total=ft,
                model_err=abs(ft - fair), mkt_err=abs(ft - mkt) if mkt is not None else None, n_plays=len(singles) + (1 if m else 0),
                plays_cost=round(first['cost'], 2) if first else 0, plays_pnl=round(pnl, 2), mid_pnl=mp, plays='', rest_mid='', rest_mid_pnl=rp, game_id=gid, sheet=sh)


S = lambda kind, line, c, n: dict(kind=kind, line=line, price_c=c, contracts=n, cost=round(n * c / 100 + 0.07 * n * c / 100 * (1 - c / 100), 2))
T['results'] = [
    result('g5', 'nfl', 'DAL @ GB', yday, '0-17', 47.5, -6.5, 42.5, 45.0, 'DAL 13, GB 23', 36, [S('under', 43.5, 44, 147), S('under', 40.5, 33, 110)],
           rest=dict(a_line=40.5, a_price=52, b_line=43.5, b_price=52, pairs=129, cost=134.16), settled_min=180),
    result('g8', 'nfl', 'LAC @ KC', yday, '3-19', 41.5, -5.5, 41.5, 41.5, 'LAC 6, KC 22', 28, [], rest=dict(a_line=40.5, a_price=49, b_line=43.5, b_price=57, pairs=125, cost=132.5), settled_min=420),
    result('g10', 'nfl', 'BUF @ LV', yday, '13-13', 50.5, -5.0, 52.5, 53.0, 'BUF 33, LV 30', 63, [], rest=dict(a_line=50.5, a_price=53, b_line=53.5, b_price=51, pairs=129, cost=134.16), settled_min=600),
    result('g6', 'cfb', 'PSU @ MICH', sat, '3-7', 44.5, -3.5, 27.5, 25.5, 'PSU 20, MICH 24', 44, [S('over', 24.5, 55, 230)], settled_min=1900),
    result('g9', 'cfb', 'FRES @ SDSU', sat, '10-14', 51.5, 2.5, 48.5, 49.5, 'FRES 24, SDSU 24', 48,
           [], m=dict(a_line=45.5, a_price=55, b_line=50.5, b_price=52, pairs=120, cost=129.9), settled_min=1950),
    result('g7', 'cfb', 'TULN @ RICE', sat, '21-17', 63.5, 6.5, 66.5, 60.5, 'TULN 28, RICE 24', 52, [S('over', 62.5, 48, 187)], settled_min=2100),
]
T['alerts'] = [
    dict(id=5, sent_at=ago(3), game_id='g1', sport='nfl', slot='half', kind='play', priority='high', title='PLAY: Bills 13, Rams 7 (half, NFL)',
         body='Bills 13, Rams 7 at the half. Pregame o/u 55.5, Rams -3.5. Fair 47.5, Kalshi 45.5.\n\nBuy OVER 42.5 for $73 at 59c (-144), 121 shares. Best.\n\nMIDDLE: Buy OVER 42.5 at 59c (118 shares for $70) + UNDER 48.5 at 45c (118 shares for $53). Final 43 to 48 wins both, +$113; any other final, -$5.\n\nKXNFLTOTAL-26OCT20BUFLAR', event_ticker='KXNFLTOTAL-26OCT20BUFLAR', channels='ntfy', suggestion_at=ago(3)),
    dict(id=4, sent_at=ago(19), game_id='g2', sport='cfb', slot='half', kind='update', priority='default', title='UPDATE: Utah 13, Colorado 0 (half, CFB)',
         body='POSSIBLE MIDDLE (post as limit orders): OVER 32.5 at 58c (60 shares for $35) + UNDER 38.5 at 40c (60 shares for $24).\n\nKXNCAAFTOTAL-26OCT20UTAHCOLO', event_ticker='KXNCAAFTOTAL-26OCT20UTAHCOLO', channels='ntfy', suggestion_at=ago(19)),
    dict(id=3, sent_at=ago(300), game_id='g5', sport='nfl', slot='half', kind='play', priority='high', title='PLAY: Cowboys 0, Packers 17 (half, NFL)',
         body='Buy UNDER 43.5 for $65 at 44c (+127), 147 shares.\n\nKXNFLTOTAL-26OCT19DALGB', event_ticker='KXNFLTOTAL-26OCT19DALGB', channels='ntfy', suggestion_at=ago(300)),
    dict(id=2, sent_at=ago(2010), game_id='g9', sport='cfb', slot='q3', kind='play', priority='high', title='PLAY: FRES 10, SDSU 14 (Q3, CFB)',
         body='MIDDLE: Buy OVER 45.5 at 55c + UNDER 50.5 at 52c, 120 shares each.\n\nKXNCAAFTOTAL-26OCT18FRESSDSU', event_ticker='KXNCAAFTOTAL-26OCT18FRESSDSU', channels='ntfy', suggestion_at=ago(2010)),
    dict(id=1, sent_at=ago(2200), game_id='g7', sport='cfb', slot='half', kind='play', priority='high', title='PLAY: TULN 21, RICE 17 (half, CFB)',
         body='Buy OVER 62.5 for $90 at 48c, 187 shares.\n\nKXNCAAFTOTAL-26OCT18TULNRICE', event_ticker='KXNCAAFTOTAL-26OCT18TULNRICE', channels='ntfy', suggestion_at=ago(2200)),
]


# ---------- a PostgREST just big enough for the screens ----------
def pick(row, select):
    if not select or select == '*':
        return row
    out = {}
    for part in select.split(','):
        part = part.strip()
        if ':' in part:
            alias, expr = part.split(':', 1)
        else:
            alias, expr = part, part
        if '->' in expr:
            col, idx = expr.split('->', 1)
            v = row.get(col)
            out[alias] = v[int(idx)] if isinstance(v, list) and len(v) > int(idx) else None
        else:
            out[alias] = row.get(expr)
    return out


def matches(row, col, cond):
    op, _, val = cond.partition('.')
    v = row.get(col)
    if op == 'eq':
        return str(v) == val
    if op == 'neq':
        return str(v) != val
    if op == 'gte':
        return v is not None and str(v) >= val
    if op == 'in':
        return str(v) in [x.strip().strip('"') for x in val.strip('()').split(',')]
    if op == 'is':
        return (v is None) == (val == 'null')
    if op == 'not':
        return not matches(row, col, val)
    return True


def query(table, qs):
    rows = list(T.get(table, []))
    params = parse_qsl(qs, keep_blank_values=True)
    select, order, limit = '*', None, None
    for k, v in params:
        if k == 'select':
            select = v
        elif k == 'order':
            order = v
        elif k == 'limit':
            limit = int(v)
        elif k == 'offset':
            pass
        else:
            rows = [r for r in rows if matches(r, k, v)]
    if order:
        col, _, direction = order.partition('.')
        rows.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=direction == 'desc')
    if limit is not None:
        rows = rows[:limit]
    return [pick(r, select) for r in rows]


def handle(route, request):
    u = urlparse(request.url)
    if '/rest/v1/' in u.path:
        table = u.path.split('/rest/v1/')[1].strip('/')
        rows = query(table, u.query)
        accept = request.headers.get('accept', '')
        if 'vnd.pgrst.object' in accept:
            body = json.dumps(rows[0]) if rows else json.dumps({'code': 'PGRST116', 'details': 'The result contains 0 rows', 'message': 'JSON object requested, multiple (or no) rows returned'})
            return route.fulfill(status=200 if rows else 406, content_type='application/json', body=body)
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(rows))
    if '/auth/v1/' in u.path:
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(session()))
    return route.fulfill(status=404, body='')


def session():
    return dict(access_token='mock', refresh_token='mock', token_type='bearer', expires_in=86400, expires_at=int(time.time()) + 86400,
                user=dict(id='u1', aud='authenticated', role='authenticated', email='nick@example.com', app_metadata={}, user_metadata={}, created_at=ago(0)))


ROUTES = {'today': '/', 'bets': '/bets/', 'alerts': '/alerts/', 'calc': '/calc/', 'record': '/record/', 'desk': '/desk/?g=g1', 'desk-stale': '/desk/?g=g2', 'ledger': '/ledger/'}


def main(only=None):
    os.makedirs(OUT, exist_ok=True)
    env = dict(os.environ, NEXT_PUBLIC_SUPABASE_URL=FAKE, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='sb_publishable_mock', NEXT_TELEMETRY_DISABLED='1', PORT=str(PORT))
    dev = subprocess.Popen(['npx', 'next', 'dev', '-p', str(PORT)], cwd=APP, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(600):
            line = dev.stdout.readline()
            if 'Ready' in line or 'ready' in line:
                break
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
            ctx.route(f'{FAKE}/**', handle)
            ctx.add_init_script(f"try {{ localStorage.setItem('halftime-desk-auth', {json.dumps(json.dumps(session()))}); }} catch (e) {{}}")
            page = ctx.new_page()
            page.on('console', lambda m: print('console', m.type, m.text) if m.type in ('error', 'warning') and 'Download the React DevTools' not in m.text else None)
            for name, path in ROUTES.items():
                if only and name != only:
                    continue
                page.set_default_navigation_timeout(180000)
                page.goto(f'http://localhost:{PORT}{path}', wait_until='domcontentloaded')
                page.wait_for_timeout(2500)
                shot = os.path.join(OUT, f'{name}.png')
                page.screenshot(path=shot)                        # the phone's viewport: the screen scrolls inside the shell
                page.set_viewport_size({'width': 390, 'height': 2400})
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(OUT, f'{name}-tall.png'))   # the whole screen, for review
                page.set_viewport_size({'width': 390, 'height': 844})
                print(f'{name}: {shot}')
            if only in (None, 'record'):   # the Record screen with a row open and with every half shown
                page.goto(f'http://localhost:{PORT}/record/', wait_until='load')
                page.wait_for_timeout(2500)
                page.get_by_role('button', name=re.compile('DAL @ GB')).click()
                page.wait_for_timeout(300)
                page.set_viewport_size({'width': 390, 'height': 2400}); page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(OUT, 'record-open.png'))
                page.get_by_role('tab', name='Every half').click()
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(OUT, 'record-all.png'))
                print('record-open, record-all')
            browser.close()
    finally:
        dev.terminate()
        try:
            dev.wait(timeout=10)
        except Exception:
            dev.kill()


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
