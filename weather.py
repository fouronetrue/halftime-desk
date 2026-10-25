"""Weather at the venue at the half (NFL), for the bad-weather haircut from the tail study (Oct 24, 2026).

In rain or snow at kickoff, or 16+ mph wind, outdoors, the NFL second half ran about a point under the model
on 927 games since 2000: the 80-90c overs there won 80 percent at an 85c price, in every five-year stretch. The
desk's fix is a 1-point haircut to the model's own second-half mean (config weather.nfl.pts), applied before the
blend with the sharp line (which already shades for weather, so the blended number moves about half a point).

Source: Open-Meteo's forecast API (free, no key): the current observation at the stadium's coordinates. The
venue comes from the home team's stadium (STADIUMS, by ESPN abbreviation) or, for a neutral site, the venue name
ESPN gives (NEUTRAL, by keyword). A dome or a retractable roof never gets the haircut: retractable roofs are
usually closed in bad weather and the study measured open-air stadiums only. No venue, no reading or an error
means no haircut, and the push says nothing.

Usage from the desk: weather.for_game(g, cfg) -> dict or None (see for_game). Under --fixtures the reading comes
from fixtures/weather_<game id>.json when present (the same shape Open-Meteo returns), else None.
"""
import os, datetime as dt

try:
    import requests
except ImportError:
    requests = None

API = 'https://api.open-meteo.com/v1/forecast'
FIELDS = 'temperature_2m,precipitation,rain,showers,snowfall,wind_speed_10m,wind_gusts_10m,weather_code'

# ESPN home abbreviation -> (stadium, lat, lon, roof). roof: outdoors, dome, retractable.
STADIUMS = {
    'ARI': ('State Farm Stadium', 33.5276, -112.2626, 'retractable'),
    'ATL': ('Mercedes-Benz Stadium', 33.7554, -84.4010, 'retractable'),
    'BAL': ('M&T Bank Stadium', 39.2780, -76.6227, 'outdoors'),
    'BUF': ('Highmark Stadium', 42.7738, -78.7870, 'outdoors'),
    'CAR': ('Bank of America Stadium', 35.2258, -80.8528, 'outdoors'),
    'CHI': ('Soldier Field', 41.8623, -87.6167, 'outdoors'),
    'CIN': ('Paycor Stadium', 39.0954, -84.5160, 'outdoors'),
    'CLE': ('Huntington Bank Field', 41.5061, -81.6995, 'outdoors'),
    'DAL': ('AT&T Stadium', 32.7473, -97.0945, 'retractable'),
    'DEN': ('Empower Field at Mile High', 39.7439, -105.0201, 'outdoors'),
    'DET': ('Ford Field', 42.3400, -83.0456, 'dome'),
    'GB': ('Lambeau Field', 44.5013, -88.0622, 'outdoors'),
    'HOU': ('NRG Stadium', 29.6847, -95.4107, 'retractable'),
    'IND': ('Lucas Oil Stadium', 39.7601, -86.1639, 'retractable'),
    'JAX': ('EverBank Stadium', 30.3240, -81.6373, 'outdoors'),
    'KC': ('GEHA Field at Arrowhead Stadium', 39.0489, -94.4839, 'outdoors'),
    'LV': ('Allegiant Stadium', 36.0909, -115.1833, 'dome'),
    'LAC': ('SoFi Stadium', 33.9535, -118.3392, 'dome'),
    'LAR': ('SoFi Stadium', 33.9535, -118.3392, 'dome'),
    'MIA': ('Hard Rock Stadium', 25.9580, -80.2389, 'outdoors'),
    'MIN': ('U.S. Bank Stadium', 44.9736, -93.2575, 'dome'),
    'NE': ('Gillette Stadium', 42.0909, -71.2643, 'outdoors'),
    'NO': ('Caesars Superdome', 29.9511, -90.0812, 'dome'),
    'NYG': ('MetLife Stadium', 40.8135, -74.0745, 'outdoors'),
    'NYJ': ('MetLife Stadium', 40.8135, -74.0745, 'outdoors'),
    'PHI': ('Lincoln Financial Field', 39.9008, -75.1675, 'outdoors'),
    'PIT': ('Acrisure Stadium', 40.4468, -80.0158, 'outdoors'),
    'SF': ("Levi's Stadium", 37.4033, -121.9694, 'outdoors'),
    'SEA': ('Lumen Field', 47.5952, -122.3316, 'outdoors'),
    'TB': ('Raymond James Stadium', 27.9759, -82.5033, 'outdoors'),
    'TEN': ('Nissan Stadium', 36.1665, -86.7713, 'outdoors'),
    'WSH': ('Northwest Stadium', 38.9076, -76.8645, 'outdoors'),
    'WAS': ('Northwest Stadium', 38.9076, -76.8645, 'outdoors'),
}
# neutral sites, matched on a keyword in ESPN's venue name
NEUTRAL = [
    ('tottenham', 'Tottenham Hotspur Stadium', 51.6042, -0.0662, 'outdoors'),
    ('wembley', 'Wembley Stadium', 51.5560, -0.2796, 'outdoors'),
    ('twickenham', 'Twickenham', 51.4559, -0.3415, 'outdoors'),
    ('allianz', 'Allianz Arena', 48.2188, 11.6247, 'outdoors'),
    ('deutsche bank', 'Deutsche Bank Park', 50.0686, 8.6455, 'outdoors'),
    ('bernab', 'Santiago Bernabeu', 40.4531, -3.6883, 'retractable'),
    ('azteca', 'Estadio Azteca', 19.3029, -99.1505, 'outdoors'),
    ('corinthians', 'Arena Corinthians', -23.5453, -46.4742, 'outdoors'),
    ('croke', 'Croke Park', 53.3607, -6.2512, 'outdoors'),
    ('melbourne', 'Melbourne Cricket Ground', -37.8200, 144.9834, 'outdoors'),
]
# Open-Meteo WMO weather codes that mean precipitation is falling
WET_CODES = set(range(51, 68)) | set(range(71, 78)) | set(range(80, 87)) | set(range(95, 100))
SNOW_CODES = set(range(71, 78)) | {85, 86}


def venue_for(g):
    """(name, lat, lon, roof) for a game, or None when the venue is not on file."""
    name = ((g.get('venue') or {}).get('name') or '').lower()
    if g.get('neutral') or not g.get('home', {}).get('abbr'):
        for key, nm, lat, lon, roof in NEUTRAL:
            if key in name:
                return nm, lat, lon, roof
        return None
    st = STADIUMS.get(g['home']['abbr'])
    if not st:
        return None
    nm, lat, lon, roof = st
    if (g.get('venue') or {}).get('indoor') and roof == 'outdoors':
        roof = 'dome'     # ESPN says indoor: trust it over the table
    return nm, lat, lon, roof


def fetch(lat, lon, timeout=10):
    """The current observation at a point, in F, inches and mph. None on any failure."""
    if requests is None:
        return None
    try:
        r = requests.get(API, params=dict(latitude=lat, longitude=lon, current=FIELDS, wind_speed_unit='mph', temperature_unit='fahrenheit',
                                          precipitation_unit='inch', timezone='UTC'), timeout=timeout, headers={'User-Agent': 'halftime-desk/1.0'})
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def parse(data):
    """Open-Meteo's response -> the fields the desk keeps, or None when the shape is wrong."""
    cur = (data or {}).get('current') or {}
    if not cur:
        return None
    def num(k):
        v = cur.get(k)
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None
    precip = max(num('precipitation') or 0.0, (num('rain') or 0.0) + (num('showers') or 0.0))
    snow = num('snowfall') or 0.0
    code = cur.get('weather_code')
    code = int(code) if code is not None else None
    return dict(temp_f=num('temperature_2m'), precip_in=round(precip, 3), snow_in=round(snow, 3), wind_mph=num('wind_speed_10m'),
                gust_mph=num('wind_gusts_10m'), code=code, obs_at=cur.get('time'))


def judge(obs, roof, cfg):
    """(bad, why): the study's definition. Outdoors only; rain or snow falling (any measurable precipitation, or
    a precipitation weather code) or wind at or above cfg wind_mph (16)."""
    if roof != 'outdoors':
        return False, 'dome' if roof == 'dome' else 'roof'
    wind_lim = float(cfg.get('wind_mph', 16))
    precip_lim = float(cfg.get('precip_in', 0.01))
    code = obs.get('code')
    wet = (obs.get('precip_in') or 0) >= precip_lim or (obs.get('snow_in') or 0) > 0 or (code in WET_CODES)
    snow = (obs.get('snow_in') or 0) > 0 or (code in SNOW_CODES)
    wind = obs.get('wind_mph')
    windy = wind is not None and wind >= wind_lim
    why = []
    if wet:
        why.append('snow' if snow else 'rain')
    if windy:
        why.append(f'{wind:.0f} mph wind')
    if not why:
        return False, f"dry, {wind:.0f} mph" if wind is not None else 'dry'
    return True, ', '.join(why)


def for_game(g, cfg, fixtures=None):
    """The weather reading for a game, or None when the sport has no weather block, the venue is unknown or the
    read failed. cfg is the sport's block of config['weather'] (pts, wind_mph, precip_in).
    Returns dict(at, venue, roof, temp_f, precip_in, snow_in, wind_mph, gust_mph, code, bad, why, shift)."""
    if not cfg:
        return None
    v = venue_for(g)
    if not v:
        return None
    name, lat, lon, roof = v
    if fixtures is not None:
        path = os.path.join(fixtures, f"weather_{g['id']}.json")
        if not os.path.exists(path):
            return None
        import json
        data = json.load(open(path))
    else:
        data = fetch(lat, lon)
    obs = parse(data)
    if not obs:
        return None
    bad, why = judge(obs, roof, cfg)
    pts = float(cfg.get('pts', -1.0))
    return dict(at=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), venue=name, roof=roof, **obs, bad=bad, why=why,
                shift=pts if bad else 0.0)


def text(wx):
    """The push's one line, only when the haircut applies: 'Weather: rain, 18 mph wind. Model -1.0.'"""
    if not wx or not wx.get('bad'):
        return None
    return f"Weather: {wx['why']}. Model {wx['shift']:+.1f}."
