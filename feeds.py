"""Data feeds: ESPN scoreboards (scores, status, pregame odds) and Kalshi public market data.
No API keys needed. Every function returns plain dicts so the rest of the desk can run on fixtures."""
import re, json, time, datetime as dt
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:  # the engine and tests work without it
    requests = None

ET = ZoneInfo('America/New_York')
ESPN = {
    'nfl': 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
    'cfb': 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300',
}
KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'
SERIES = {'nfl': {'total': 'KXNFLTOTAL', 'spread': 'KXNFLSPREAD'}, 'cfb': {'total': 'KXNCAAFTOTAL', 'spread': 'KXNCAAFSPREAD'}}
MONTHS = {m: i for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'], 1)}


def get_json(url, params=None, tries=3, timeout=20):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers={'User-Agent': 'halftime-desk/1.0'})
            if r.status_code == 200:
                return r.json()
            last = f'HTTP {r.status_code}'
        except Exception as e:  # network hiccup, retry
            last = str(e)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f'GET {url} failed: {last}')


# ---------- ESPN ----------
def parse_clock(s):
    """'12:34' -> seconds; '0:00' -> 0; anything odd -> None"""
    m = re.match(r'^(\d+):(\d\d)', str(s or ''))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def parse_espn(data, sport):
    games = []
    for ev in data.get('events', []):
        comp = (ev.get('competitions') or [{}])[0]
        comps = comp.get('competitors') or []
        home = next((c for c in comps if c.get('homeAway') == 'home'), None)
        away = next((c for c in comps if c.get('homeAway') == 'away'), None)
        if not home or not away:
            continue
        st = ev.get('status') or comp.get('status') or {}
        typ = st.get('type') or {}
        def side(c):
            t = c.get('team') or {}
            ls = [x.get('value') for x in (c.get('linescores') or [])]
            return dict(abbr=t.get('abbreviation', ''), name=t.get('displayName', ''), loc=t.get('location', ''), short=t.get('shortDisplayName', ''),
                        score=int(float(c.get('score') or 0)), linescores=[int(float(v)) for v in ls if v is not None])
        odds = (comp.get('odds') or [{}])[0]
        try:
            when = dt.datetime.fromisoformat(ev['date'].replace('Z', '+00:00'))
        except Exception:
            when = None
        games.append(dict(
            id=str(ev.get('id')), sport=sport, name=ev.get('name', ''), short=ev.get('shortName', ''),
            start_utc=when.isoformat() if when else None, date_et=when.astimezone(ET).strftime('%Y-%m-%d') if when else None,
            home=side(home), away=side(away), neutral=bool(comp.get('neutralSite')),
            state=typ.get('state', ''), status=typ.get('name', ''), detail=typ.get('shortDetail', ''),
            period=int(st.get('period') or 0), clock=st.get('displayClock', ''), clock_s=parse_clock(st.get('displayClock')),
            odds_details=odds.get('details'), over_under=odds.get('overUnder'),
        ))
    return games


def espn_games(sport, date_yyyymmdd=None):
    url = ESPN[sport]
    params = {'dates': date_yyyymmdd} if date_yyyymmdd else None
    return parse_espn(get_json(url, params), sport)


def half_score(g):
    """(away_pts, home_pts) at the half, or None if not known yet."""
    if g['status'] == 'STATUS_HALFTIME' or (g['period'] == 2 and g['clock_s'] == 0 and g['state'] == 'in'):
        return g['away']['score'], g['home']['score']
    if g['period'] >= 3 and len(g['home']['linescores']) >= 2 and len(g['away']['linescores']) >= 2:
        return sum(g['away']['linescores'][:2]), sum(g['home']['linescores'][:2])
    return None


def phase(g):
    """pre | approaching (Q2 under 5:00) | half | early3 | live | post"""
    if g['state'] == 'pre':
        return 'pre'
    if g['state'] == 'post':
        return 'post'
    if g['status'] == 'STATUS_HALFTIME':
        return 'half'
    if g['period'] == 2 and g['clock_s'] is not None and g['clock_s'] <= 300:
        return 'approaching'
    if g['period'] == 3 and g['clock_s'] is not None and g['clock_s'] >= (12 * 60 if g['sport'] == 'nfl' else 13 * 60):
        return 'early3'
    return 'live'


def espn_lines(g):
    """Pregame spread (home perspective, minus = home favored) and total from ESPN's odds block, if present."""
    d, ou = g.get('odds_details'), g.get('over_under')
    spread = None
    if d:
        m = re.match(r'^\s*([A-Z]{2,5})\s*([+-]?\d+(?:\.\d+)?)', str(d))
        if m:
            team, num = m.group(1), float(m.group(2))
            if team == g['home']['abbr']:
                spread = num
            elif team == g['away']['abbr']:
                spread = -num
        elif re.match(r'^\s*(EVEN|PK|PICK)', str(d), re.I):
            spread = 0.0
    try:
        total = float(ou) if ou is not None else None
    except Exception:
        total = None
    return spread, total


def espn_odds_endpoint(sport, game_id):
    """Fallback pregame line from ESPN's odds endpoint: (home_spread, total) or (None, None)."""
    league = 'nfl' if sport == 'nfl' else 'college-football'
    try:
        data = get_json(f'https://sports.core.api.espn.com/v2/sports/football/leagues/{league}/events/{game_id}/competitions/{game_id}/odds', tries=1)
    except Exception:
        return None, None
    items = data.get('items') or []
    if not items:
        return None, None
    it = items[0]
    total = it.get('overUnder')
    spread = it.get('spread')
    try:
        spread = float(spread) if spread is not None else None
        total = float(total) if total is not None else None
    except Exception:
        return None, None
    home_fav = (it.get('homeTeamOdds') or {}).get('favorite')
    if spread is not None and home_fav is not None:
        spread = -abs(spread) if home_fav else abs(spread)
    return spread, total


# ---------- Kalshi ----------
def cents(m, key):
    """Price in cents from either the dollars-string fields or legacy integer-cents fields."""
    v = m.get(key + '_dollars')
    if v is not None:
        try:
            return int(round(float(v) * 100))
        except Exception:
            return None
    v = m.get(key)
    return int(v) if isinstance(v, (int, float)) else None


def kalshi_events(series, status='open'):
    out, cursor = [], None
    for _ in range(20):
        params = {'series_ticker': series, 'status': status, 'with_nested_markets': 'true', 'limit': 200}
        if cursor:
            params['cursor'] = cursor
        data = get_json(f'{KALSHI}/events', params)
        out.extend(data.get('events') or [])
        cursor = data.get('cursor')
        if not cursor:
            break
    return out


def ticker_date(event_ticker):
    """KXNFLTOTAL-26OCT15SEADEN -> ('2026-10-15', 'SEADEN')"""
    m = re.match(r'^[A-Z0-9]+-(\d\d)([A-Z]{3})(\d\d)([A-Z0-9]+)$', event_ticker or '')
    if not m:
        return None, None
    y, mon, d, teams = m.groups()
    return f'20{y}-{MONTHS[mon]:02d}-{int(d):02d}', teams


def norm(s):
    s = re.sub(r"[^a-z0-9 ]", '', str(s or '').lower())
    s = s.replace(' state', ' st').replace('saint ', 'st ')
    return ' '.join(s.split())


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 3.0
    if a in b or b in a:
        return 2.0
    ta, tb = set(a.split()), set(b.split())
    common = (ta & tb) - {'st', 'the', 'of', 'university'}
    return 1.0 + len(common) / max(1, min(len(ta), len(tb))) if common else 0.0


def match_event(game, events):
    """Pick the Kalshi event for an ESPN game: same date, both teams found in the ticker codes or the title."""
    best, best_s = None, 0.0
    for ev in events:
        d, codes = ticker_date(ev.get('event_ticker'))
        if d != game['date_et']:
            continue
        s = 0.0
        ab, hb = game['away']['abbr'], game['home']['abbr']
        if codes and ab and hb and (codes == ab + hb or codes == hb + ab):
            s += 10
        title = re.sub(r':.*$', '', ev.get('title') or '')
        parts = [p.strip() for p in re.split(r'\s+(?:vs\.?|at|@)\s+', title) if p.strip()]
        if len(parts) == 2:
            names_a = [game['away'][k] for k in ('name', 'loc', 'short')]
            names_h = [game['home'][k] for k in ('name', 'loc', 'short')]
            s1 = max(sim(parts[0], n) for n in names_a) + max(sim(parts[1], n) for n in names_h)
            s2 = max(sim(parts[1], n) for n in names_a) + max(sim(parts[0], n) for n in names_h)
            s += max(s1, s2)
        if s > best_s:
            best, best_s = ev, s
    return best if best_s >= 3.0 else None


def total_quotes(ev):
    """{strike: {'y': yes_ask, 'n': no_ask, 'yb': yes_bid, 'nb': no_bid, 'ticker': ...}} for a totals event."""
    out = {}
    for m in ev.get('markets') or []:
        k = m.get('floor_strike')
        if k is None:
            mm = re.search(r'over (\d+(?:\.\d+)?)', m.get('title') or '', re.I)
            k = float(mm.group(1)) if mm else None
        if k is None or m.get('status') not in (None, 'open', 'active'):
            continue
        out[float(k)] = dict(y=cents(m, 'yes_ask'), n=cents(m, 'no_ask'), yb=cents(m, 'yes_bid'), nb=cents(m, 'no_bid'), ticker=m.get('ticker'))
    return out


def implied_line(points):
    """points: list of (strike, p_yes) where p_yes = P(value > strike). Returns the value where p crosses 0.5."""
    pts = sorted((k, p) for k, p in points if p is not None)
    if len(pts) < 2:
        return None
    for (k1, p1), (k2, p2) in zip(pts, pts[1:]):
        if p1 >= 0.5 >= p2 and p1 != p2:
            return round((k1 + (p1 - 0.5) / (p1 - p2) * (k2 - k1)) * 2) / 2
    return None


def kalshi_total_line(ev):
    pts = []
    for k, q in total_quotes(ev).items():
        if q['yb'] is not None and q['y'] is not None and 0 < q['yb'] <= q['y'] < 100:
            pts.append((k, (q['yb'] + q['y']) / 200))
    return implied_line(pts)


def kalshi_spread_line(ev, game):
    """Home spread (minus = home favored) implied by a spread event's 'X wins by over k' markets."""
    by_team = {}
    for m in ev.get('markets') or []:
        k = m.get('floor_strike')
        title = m.get('yes_sub_title') or m.get('title') or ''
        mm = re.match(r'^(.*?) wins by over (\d+(?:\.\d+)?)', title, re.I)
        if k is None and mm:
            k = float(mm.group(2))
        team = mm.group(1).strip() if mm else None
        yb, ya = cents(m, 'yes_bid'), cents(m, 'yes_ask')
        if team is None or k is None or yb is None or ya is None or not (0 < yb <= ya < 100):
            continue
        by_team.setdefault(team, []).append((float(k), (yb + ya) / 200))
    best = None
    for team, pts in by_team.items():
        line = implied_line(pts)
        if line is None:
            continue   # this team is the dog: its 'wins by' curve never reaches 50%
        is_home = max(sim(team, game['home'][k]) for k in ('name', 'loc', 'short')) >= max(sim(team, game['away'][k]) for k in ('name', 'loc', 'short'))
        best = -line if is_home else line
    return best
