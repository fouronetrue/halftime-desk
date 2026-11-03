"""Travel, time-zone and rest features for the college basketball game table, from the hoopR schedules.

For every ESPN game in data/cbb_games.csv: the venue (city, state, latitude, longitude, time zone), each team's
home city that season (the venue of most of its non-neutral home games), the miles each team travelled to the
venue, the hours of time-zone shift it faced (venue offset minus home offset on the game date, so a Pittsburgh
team in Los Angeles reads -3 and a Los Angeles team in Pittsburgh +3), days of rest for each team (days since
its previous game that season, capped at 10), the local tip time at the venue, and whether it is a conference
game. City coordinates come from kelvins/US-Cities-Database (GitHub); the zone from timezonefinder.

Usage: python scripts/build_cbb_travel.py SCHED_DIR CITIES.csv data/cbb_games.csv data/cbb_travel.csv
"""
import csv, glob, math, os, re, sys, collections, datetime as dt
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder

TF = TimezoneFinder()
ET = ZoneInfo('America/New_York')


def norm_city(s):
    s = str(s or '').strip().lower()
    s = re.sub(r'\bsaint\b', 'st.', s)
    s = s.replace('ft.', 'fort').replace('ft ', 'fort ')
    return re.sub(r'\s+', ' ', s)


# venues the cities table lacks (campus towns, suburbs and the neutral-site tournaments abroad)
EXTRA = {('winston-salem', 'NC'): (36.10, -80.24), ('coral gables', 'FL'): (25.72, -80.27), ('moon township', 'PA'): (40.52, -80.22),
         ('homewood', 'AL'): (33.47, -86.80), ('lawrenceville', 'NJ'): (40.30, -74.73), ('riverdale', 'NY'): (40.89, -73.90),
         ('ashwaubenon', 'WI'): (44.48, -88.07), ('highland heights', 'KY'): (39.03, -84.45), ('queens', 'NY'): (40.73, -73.79),
         ('rosemont', 'IL'): (41.99, -87.87), ('storrs', 'CT'): (41.81, -72.25), ('greenview', 'SC'): (34.85, -82.40),
         ('college park', 'GA'): (33.65, -84.45), ('sunrise', 'FL'): (26.13, -80.26), ('hot springs', 'AR'): (34.50, -93.05),
         ('nassau', 'BAHAMAS'): (25.06, -77.35), ('maui', 'HI'): (20.88, -156.68), ('lahaina', 'HI'): (20.88, -156.68),
         ('st. thomas', 'VIRGIN ISLANDS'): (18.34, -64.93), ('cancun', 'MEXICO'): (21.16, -86.85), ('san juan', 'PUERTO RICO'): (18.47, -66.11),
         ('george town', 'CAYMAN ISLANDS'): (19.29, -81.37), ('montego bay', 'JAMAICA'): (18.47, -77.92), ('freeport', 'GB'): (26.53, -78.70),
         ('bimini', 'BAHAMAS'): (25.73, -79.30), ('laval', 'PQ'): (45.57, -73.69), ('paradise island', 'BAHAMAS'): (25.08, -77.32)}


def read_cities(path):
    out = dict(EXTRA)
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            key = (norm_city(r['CITY']), r['STATE_CODE'].strip().upper())
            out.setdefault(key, (float(r['LATITUDE']), float(r['LONGITUDE'])))
    return out


def haversine(a, b):
    if not a or not b:
        return None
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = 0.5 - math.cos((la2 - la1) * p) / 2 + math.cos(la1 * p) * math.cos(la2 * p) * (1 - math.cos((lo2 - lo1) * p)) / 2
    return 2 * 3958.8 * math.asin(math.sqrt(h))


_tz_cache = {}


def zone_of(ll):
    if not ll:
        return None
    key = (round(ll[0], 2), round(ll[1], 2))
    if key not in _tz_cache:
        _tz_cache[key] = TF.timezone_at(lat=ll[0], lng=ll[1])
    return _tz_cache[key]


def offset_hours(zone, when):
    try:
        return when.astimezone(ZoneInfo(zone)).utcoffset().total_seconds() / 3600
    except Exception:
        return None


def main():
    sched_dir, cities_path, games_path, out_path = sys.argv[1:5]
    cities = read_cities(cities_path)
    want = {r['game_id'] for r in csv.DictReader(open(games_path)) if r.get('game_id')}
    rows_by_id = {}
    missing_city = collections.Counter()
    # per season: every game of every team (for rest days and the home venue), then the features for the wanted games
    for path in sorted(glob.glob(os.path.join(sched_dir, 'mbb_schedule_*.csv'))):
        games = []
        with open(path, newline='') as f:
            for r in csv.DictReader(f):
                if r.get('status_type_name') != 'STATUS_FINAL':
                    continue
                try:
                    when = dt.datetime.fromisoformat(r['start_date'].replace('Z', '+00:00'))
                except Exception:
                    continue
                city, st = norm_city(r.get('venue_address_city')), (r.get('venue_address_state') or '').strip().upper()
                ll = cities.get((city, st))
                if city and st and not ll:
                    missing_city[(city, st)] += 1
                games.append(dict(game_id=r['game_id'], when=when, date=r.get('game_date') or when.astimezone(ET).strftime('%Y-%m-%d'),
                                  home_id=r['home_id'], away_id=r['away_id'], neutral=str(r.get('neutral_site')).lower() == 'true',
                                  conf=str(r.get('conference_competition')).lower() == 'true', venue=r.get('venue_full_name') or '',
                                  city=city, state=st, ll=ll, season=r.get('season')))
        # each team's home city: the venue of most of its non-neutral home games this season
        home_venue = collections.defaultdict(collections.Counter)
        for g in games:
            if not g['neutral'] and g['ll']:
                home_venue[g['home_id']][(g['city'], g['state'], g['ll'])] += 1
        home_of = {tid: c.most_common(1)[0][0] for tid, c in home_venue.items()}
        # rest days: days since the team's previous game
        by_team = collections.defaultdict(list)
        for g in games:
            by_team[g['home_id']].append((g['when'], g['game_id']))
            by_team[g['away_id']].append((g['when'], g['game_id']))
        prev = {}
        for tid, lst in by_team.items():
            lst.sort()
            for i, (when, gid) in enumerate(lst):
                prev[(tid, gid)] = (when - lst[i - 1][0]).total_seconds() / 86400 if i else None
        n = 0
        for g in games:
            if g['game_id'] not in want:
                continue
            venue_ll = g['ll']
            vz = zone_of(venue_ll)
            row = dict(game_id=g['game_id'], venue=g['venue'], venue_city=g['city'], venue_state=g['state'],
                       venue_lat=venue_ll[0] if venue_ll else '', venue_lon=venue_ll[1] if venue_ll else '', venue_tz=vz or '',
                       tip_local_hour='', conf=1 if g['conf'] else 0, neutral=1 if g['neutral'] else 0)
            if vz:
                row['tip_local_hour'] = round(g['when'].astimezone(ZoneInfo(vz)).hour + g['when'].astimezone(ZoneInfo(vz)).minute / 60, 2)
            for side in ('away', 'home'):
                tid = g[side + '_id']
                hv = home_of.get(tid)
                hz = zone_of(hv[2]) if hv else None
                miles = haversine(hv[2], venue_ll) if hv and venue_ll else None
                shift = None
                if hz and vz:
                    o_v, o_h = offset_hours(vz, g['when']), offset_hours(hz, g['when'])
                    shift = None if o_v is None or o_h is None else round(o_v - o_h, 1)
                rest = prev.get((tid, g['game_id']))
                row.update({f'{side}_home_city': hv[0] if hv else '', f'{side}_home_state': hv[1] if hv else '', f'{side}_home_tz': hz or '',
                            f'{side}_miles': round(miles) if miles is not None else '', f'{side}_tz_shift': '' if shift is None else shift,
                            f'{side}_rest_days': '' if rest is None else round(min(rest, 10), 1)})
            rows_by_id[g['game_id']] = row
            n += 1
        print(f'{os.path.basename(path)}: {n} games featured', flush=True)
    cols = ['game_id', 'venue', 'venue_city', 'venue_state', 'venue_lat', 'venue_lon', 'venue_tz', 'tip_local_hour', 'conf', 'neutral',
            'away_home_city', 'away_home_state', 'away_home_tz', 'away_miles', 'away_tz_shift', 'away_rest_days',
            'home_home_city', 'home_home_state', 'home_home_tz', 'home_miles', 'home_tz_shift', 'home_rest_days']
    with open(out_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for gid in sorted(rows_by_id, key=lambda x: int(x)):
            w.writerow(rows_by_id[gid])
    print(f'{len(rows_by_id)} rows written to {out_path}; venue cities not in the table (top 25): {missing_city.most_common(25)}')


if __name__ == '__main__':
    main()
