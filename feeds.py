"""Data feeds: ESPN scoreboards (scores, status, pregame odds) and Kalshi public market data.
No API keys needed. Every function returns plain dicts so the rest of the desk can run on fixtures."""
import re, json, time, unicodedata, datetime as dt
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:  # the engine and tests work without it
    requests = None

ET = ZoneInfo('America/New_York')
ESPN = {
    'nfl': 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
    'cfb': 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300',
    'nba': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
}
ESPN_LEAGUE = {'nfl': 'football/leagues/nfl', 'cfb': 'football/leagues/college-football', 'nba': 'basketball/leagues/nba'}
KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'
SERIES = {'nfl': {'total': 'KXNFLTOTAL', 'spread': 'KXNFLSPREAD'}, 'cfb': {'total': 'KXNCAAFTOTAL', 'spread': 'KXNCAAFSPREAD'},
          'nba': {'total': 'KXNBATOTAL', 'spread': 'KXNBASPREAD'}}
# Kalshi's team codes where they differ from ESPN's abbreviation (ticker KXNBATOTAL-26OCT20PHINYK is PHI at NYK; ESPN says NY).
KALSHI_CODES = {'nba': {'GS': 'GSW', 'NY': 'NYK', 'SA': 'SAS', 'NO': 'NOP', 'UTAH': 'UTA', 'WSH': 'WAS'}}
# Seconds left in Q3 above which the game still counts as 'early3' (the Q3 push slot): the first minute of football,
# the first 30 seconds of an NBA quarter (a basket comes in seconds, and the score-moved check then stops pricing).
EARLY3_SECONDS = {'nfl': 12 * 60, 'cfb': 13 * 60, 'nba': 11 * 60 + 30}
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
    """'12:34' -> seconds; '0:00' -> 0; the NBA's last-minute forms '45.3', ':45.3' and '0.0' -> whole seconds;
    anything odd -> None"""
    s = str(s or '').strip()
    m = re.match(r'^(\d+):(\d\d)(?:\.\d+)?$', s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r'^:?(\d+(?:\.\d+)?)$', s)
    if m:
        return int(float(m.group(1)))
    return None


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


def third_score(g):
    """(away_pts, home_pts) at the end of the third quarter, or None if not known yet."""
    if g['period'] == 3 and (g['status'] == 'STATUS_END_PERIOD' or (g['clock_s'] == 0 and g['state'] == 'in')):
        return g['away']['score'], g['home']['score']
    if g['period'] >= 4 and len(g['home']['linescores']) >= 3 and len(g['away']['linescores']) >= 3:
        return sum(g['away']['linescores'][:3]), sum(g['home']['linescores'][:3])
    return None


def phase(g):
    """pre | approaching (Q2 under 5:00) | half | early3 | live | post
    NBA only, the second window: approaching3 (Q3 under 5:00) | q3end (the break before the 4th) | early4 (the first
    30 seconds of the 4th, while the score is still the end-of-third score). The NBA has no early3: a basket comes
    in seconds, so its second push slot is the end of the third instead of the start."""
    if g['state'] == 'pre':
        return 'pre'
    if g['state'] == 'post':
        return 'post'
    if g['status'] == 'STATUS_HALFTIME':
        return 'half'
    if g['period'] == 2 and g['clock_s'] is not None and g['clock_s'] <= 300:
        return 'approaching'
    if g['sport'] == 'nba':
        if g['period'] == 3 and (g['status'] == 'STATUS_END_PERIOD' or g['clock_s'] == 0):
            return 'q3end'
        if g['period'] == 4 and g['clock_s'] is not None and g['clock_s'] >= 11 * 60 + 30:
            return 'early4'
        if g['period'] == 3 and g['clock_s'] is not None and g['clock_s'] <= 300:
            return 'approaching3'
        return 'live'
    if g['period'] == 3 and g['clock_s'] is not None and g['clock_s'] >= EARLY3_SECONDS.get(g['sport'], 13 * 60):
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
    league = ESPN_LEAGUE.get(sport, 'football/leagues/college-football')
    try:
        data = get_json(f'https://sports.core.api.espn.com/v2/sports/{league}/events/{game_id}/competitions/{game_id}/odds', tries=1)
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


# ---------- The Odds API (pregame closing lines; needs ODDS_API_KEY) ----------
ODDS_API = 'https://api.the-odds-api.com/v4/sports/{key}/odds'
ODDS_SPORT = {'nfl': 'americanfootball_nfl', 'cfb': 'americanfootball_ncaaf', 'nba': 'basketball_nba'}
# Up to ten bookmakers count as one region, so this list with two markets costs 2 credits a call (500 free a month).
# Pinnacle first (the sharp line, from its public site), then the US books for a median when Pinnacle is quiet.
ODDS_BOOKS = ['pinnacle', 'draftkings', 'fanduel', 'betmgm', 'betonlineag', 'lowvig', 'bovada', 'betrivers']


def parse_odds_api(events):
    """Odds API events -> one row per game: home, away, start_utc, books {key: (home_spread, total)}, and the line
    the desk should use: Pinnacle's when it has both numbers, else the median across the books that do.
    home_spread is minus when the home team is favored, as everywhere in the desk."""
    rows = []
    for ev in events or []:
        home, away = ev.get('home_team') or '', ev.get('away_team') or ''
        books = {}
        for bk in ev.get('bookmakers') or []:
            spread = total = None
            for mk in bk.get('markets') or []:
                outs = mk.get('outcomes') or []
                if mk.get('key') == 'spreads':
                    for o in outs:
                        if o.get('name') == home and o.get('point') is not None:
                            spread = float(o['point'])
                elif mk.get('key') == 'totals':
                    for o in outs:
                        if str(o.get('name', '')).lower() == 'over' and o.get('point') is not None:
                            total = float(o['point'])
            if spread is not None or total is not None:
                books[bk.get('key')] = (spread, total)
        if not books:
            continue
        p = books.get('pinnacle')
        if p and p[0] is not None and p[1] is not None:
            spread, total, source = p[0], p[1], 'pinnacle'
        else:
            spreads = sorted(v[0] for v in books.values() if v[0] is not None)
            totals = sorted(v[1] for v in books.values() if v[1] is not None)
            if not spreads or not totals:
                continue
            spread, total = spreads[len(spreads) // 2], totals[len(totals) // 2]
            source = f'median{len(totals)}'
        rows.append(dict(id=ev.get('id'), home=home, away=away, start_utc=ev.get('commence_time'), books=books,
                         home_spread=spread, total=total, source=source))
    return rows


def odds_api_lines(sport, key, timeout=20):
    """One call: every upcoming game of the sport with its closing-side lines, plus the quota from the response
    headers (remaining, used, last). Raises on a failed call so the caller can back off."""
    if sport not in ODDS_SPORT or not key:
        return [], {}
    r = requests.get(ODDS_API.format(key=ODDS_SPORT[sport]), timeout=timeout, headers={'User-Agent': 'halftime-desk/1.0'},
                     params=dict(apiKey=key, bookmakers=','.join(ODDS_BOOKS), markets='spreads,totals', oddsFormat='american', dateFormat='iso'))
    usage = {k: int(v) for k, v in [('remaining', r.headers.get('x-requests-remaining')), ('used', r.headers.get('x-requests-used')),
                                     ('last', r.headers.get('x-requests-last'))] if v not in (None, '')}
    if r.status_code != 200:
        raise RuntimeError(f'odds api {sport}: HTTP {r.status_code} {r.text[:120]}')
    return parse_odds_api(r.json()), usage


def parse_h2(data):
    """An Odds API event (live or a historical snapshot) -> {book: [line, over_price, under_price]} for the
    second-half total (market totals_h2)."""
    books = {}
    for bk in (data or {}).get('bookmakers') or []:
        for mk in bk.get('markets') or []:
            if mk.get('key') != 'totals_h2':
                continue
            line = over = under = None
            for o in mk.get('outcomes') or []:
                nm = str(o.get('name', '')).lower()
                if o.get('point') is None:
                    continue
                if nm == 'over':
                    line, over = float(o['point']), o.get('price')
                elif nm == 'under':
                    under = o.get('price')
                    line = float(o['point']) if line is None else line
            if line is not None:
                books[bk.get('key')] = [line, over, under]
    return books


def sharp_h2(books):
    """The second-half line to center on: Pinnacle's when it has one, else the median across the books.
    (line, source, n_books), or (None, None, 0)."""
    if not books:
        return None, None, 0
    if 'pinnacle' in books:
        return books['pinnacle'][0], 'pinnacle', len(books)
    lines = sorted(v[0] for v in books.values())
    return lines[len(lines) // 2], f'median{len(lines)}', len(lines)


def odds_api_h2(sport, event_id, key, timeout=15):
    """The live second-half total on one game, one credit: {book: [line, over, under]} and the quota headers."""
    if sport not in ODDS_SPORT or not key or not event_id:
        return {}, {}
    r = requests.get(f'https://api.the-odds-api.com/v4/sports/{ODDS_SPORT[sport]}/events/{event_id}/odds', timeout=timeout,
                     headers={'User-Agent': 'halftime-desk/1.0'},
                     params=dict(apiKey=key, bookmakers=','.join(ODDS_BOOKS), markets='totals_h2', oddsFormat='american', dateFormat='iso'))
    usage = {k: int(v) for k, v in [('remaining', r.headers.get('x-requests-remaining')), ('used', r.headers.get('x-requests-used')),
                                     ('last', r.headers.get('x-requests-last'))] if v not in (None, '')}
    if r.status_code != 200:
        raise RuntimeError(f'odds api h2 {sport} {event_id}: HTTP {r.status_code} {r.text[:120]}')
    return parse_h2(r.json()), usage


def match_odds(game, rows, window_s=5400):
    """The Odds API row for an ESPN game: start within 90 minutes and both team names agree (ESPN's display name
    is 'Pittsburgh Steelers', 'Ohio State Buckeyes'; the Odds API uses the same form). None when nothing fits."""
    try:
        start = dt.datetime.fromisoformat(str(game.get('start_utc')).replace('Z', '+00:00')).timestamp()
    except Exception:
        return None
    best, best_s = None, 0.0
    for row in rows:
        try:
            t = dt.datetime.fromisoformat(str(row.get('start_utc')).replace('Z', '+00:00')).timestamp()
        except Exception:
            continue
        if abs(t - start) > window_s:
            continue
        s = min(sim(game['home']['name'], row['home']), sim(game['away']['name'], row['away']))
        if s >= 2.0 and s > best_s:
            best, best_s = row, s
    return best


def parse_box_stats(data, sport='nba'):
    """Per-team box score from ESPN's summary endpoint (cumulative at the moment it is read, so at the half it is
    the first-half box): field goal and free throw attempts, offensive rebounds, turnovers, fouls, and the
    possession estimate FGA - OREB + TOV + 0.44 x FTA. {'home': {...}, 'away': {...}, 'poss': mean of the two}
    or None when the box is not there yet."""
    teams = ((data or {}).get('boxscore') or {}).get('teams') or []
    out = {}
    for t in teams:
        side = t.get('homeAway')
        st = {x.get('name'): x.get('displayValue') for x in (t.get('statistics') or [])}
        def pair(key):
            v = st.get(key) or ''
            m = re.match(r'^\s*(\d+)\s*-\s*(\d+)', str(v))
            return (int(m.group(1)), int(m.group(2))) if m else (None, None)
        def num(key):
            try:
                return int(float(st.get(key)))
            except Exception:
                return None
        fgm, fga = pair('fieldGoalsMade-fieldGoalsAttempted')
        ftm, fta = pair('freeThrowsMade-freeThrowsAttempted')
        tpm, tpa = pair('threePointFieldGoalsMade-threePointFieldGoalsAttempted')
        oreb, fouls = num('offensiveRebounds'), num('fouls')
        tov = num('totalTurnovers') if num('totalTurnovers') is not None else num('turnovers')
        if side not in ('home', 'away') or None in (fga, fta, oreb, tov):
            continue
        out[side] = dict(fga=fga, fgm=fgm, fta=fta, ftm=ftm, tpa=tpa, oreb=oreb, tov=tov, fouls=fouls,
                         poss=round(fga - oreb + tov + 0.44 * fta, 2))
    if 'home' not in out or 'away' not in out:
        return None
    out['poss'] = round((out['home']['poss'] + out['away']['poss']) / 2, 2)
    return out


def espn_box_stats(sport, game_id):
    """The live box score for a game (one request), or None."""
    league = ESPN_LEAGUE.get(sport)
    if not league:
        return None
    try:
        data = get_json(f'https://site.api.espn.com/apis/site/v2/sports/{league.replace("/leagues/", "/")}/summary', {'event': game_id}, tries=1)
    except Exception:
        return None
    return parse_box_stats(data, sport)


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


# Team name forms that differ between the play-by-play, ESPN and the books, applied before matching.
TEAM_ALIASES = {'massachusetts': 'umass', 'app state': 'appalachian state', 'se louisiana': 'southeastern louisiana',
                'long island university': 'liu', 'hawaii rainbow warriors': 'hawaii', 'ole miss': 'mississippi', 'pitt': 'pittsburgh',
                'miami oh': 'miami ohio', 'miami (oh)': 'miami ohio', 'uconn': 'connecticut', 'utep': 'utep', 'la clippers': 'los angeles clippers'}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()   # Jose for Jose, Hawai'i for Hawaii
    s = re.sub(r"[^a-z0-9 ()]", '', s)
    s = TEAM_ALIASES.get(s.strip(), s)
    s = re.sub(r"[()]", '', s)
    s = re.sub(r"\bmiami oh\b", 'miami ohio', s)
    s = s.replace(' state', ' st').replace('saint ', 'st ')
    return ' '.join(s.split())


# a school name followed by one of these is a different school (Texas and Texas State, Miami and Miami Ohio)
SCHOOL_MODIFIERS = {'st', 'tech', 'am', 'southern', 'northern', 'eastern', 'western', 'central', 'atlantic', 'international',
                    'christian', 'ohio', 'pacific', 'wesleyan', 'baptist', 'commonwealth', 'city'}


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 3.0
    for short, long in ((a, b), (b, a)):
        m = re.search(r'(?:^|\s)' + re.escape(short) + r'(?:\s|$)', long)
        if m:
            rest = long[m.end():].split()
            return 1.0 if rest and rest[0] in SCHOOL_MODIFIERS else 2.0
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
        alias = KALSHI_CODES.get(game.get('sport'), {})
        ab, hb = game['away']['abbr'], game['home']['abbr']
        ab, hb = alias.get(ab, ab), alias.get(hb, hb)
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
