"""The CFB second-half model: the optional running-clock term in the engine, the model block, and the game table
the refit is built on (data/cfb_games.csv). Pure Python, no numpy."""
import sys, os, csv, json, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine
from engine import HalfModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mu_by_hand(block, total, home_spread, h1h, h1a):
    c = block['coef']
    home_fav_by = -home_spread
    fav_by = abs(home_fav_by)
    m1 = h1h - h1a
    favm = m1 if home_fav_by >= 0 else -m1
    mu = c[0] + c[1] * total + c[2] * (h1h + h1a) + c[3] * abs(favm) + c[4] * favm + c[5] * (fav_by if favm < 0 else 0)
    if len(c) > 6:
        mu += c[6] * max(0.0, abs(favm) - block.get('knee', 14))
    return max(8.0, mu)


# 1. a seven-term block applies the term past the knee only, and a six-term block is untouched
orig = engine.MODEL['cfb']
six = copy.deepcopy(orig)
six['coef'] = six['coef'][:6]
six.pop('knee', None)
seven = copy.deepcopy(six)
seven['coef'] = six['coef'] + [-0.25]
seven['knee'] = 14
try:
    engine.MODEL['cfb'] = six
    a = HalfModel('cfb', 55.5, -7, 24, 10).mu_model          # up 14: at the knee, no term
    b = HalfModel('cfb', 55.5, -7, 45, 10).mu_model          # up 35
    engine.MODEL['cfb'] = seven
    a7 = HalfModel('cfb', 55.5, -7, 24, 10).mu_model
    b7 = HalfModel('cfb', 55.5, -7, 45, 10).mu_model
    assert abs(a7 - a) < 1e-9, (a, a7)
    assert abs((b7 - b) - (-0.25 * 21)) < 1e-9, (b, b7)
    # the term works off the size of the lead, whoever holds it
    u = HalfModel('cfb', 55.5, -7, 10, 45).mu_model          # the dog up 35
    assert abs(u - mu_by_hand(seven, 55.5, -7, 10, 45)) < 1e-9
finally:
    engine.MODEL['cfb'] = orig

# 2. the live block, by hand against the engine, on a spread of game states
if len(orig['coef']) > 6:
    assert 'knee' in orig and 0 < orig['knee'] < 30, orig.get('knee')
    assert orig['coef'][6] < 0, 'the running-clock term takes points off'
for total, sp, h, a_ in [(55.5, -7, 24, 10), (48.5, 3, 7, 7), (71.5, -24.5, 45, 3), (60.5, -43.5, 21, 7), (52.5, -1.5, 3, 31)]:
    assert abs(HalfModel('cfb', total, sp, h, a_).mu_model - mu_by_hand(orig, total, sp, h, a_)) < 1e-9, (total, sp, h, a_)
assert len(orig['z']) == 201 and orig['z'][0] < orig['z'][100] < orig['z'][200]

# 3. the game table: every row is a finished game with a closing line, no game twice, the half never beats the final
path = os.path.join(ROOT, 'data', 'cfb_games.csv')
rows = list(csv.DictReader(open(path)))
assert len(rows) >= 10000, len(rows)
ids = [r['game_id'] for r in rows]
assert len(set(ids)) == len(ids), 'duplicate game'
seasons = set()
for r in rows:
    h1h, h1a, fh, fa = int(r['h1h']), int(r['h1a']), int(r['fh']), int(r['fa'])
    assert fh >= h1h and fa >= h1a, r
    assert 20 < float(r['total']) < 100 and abs(float(r['home_spread'])) <= 70, r      # TCU laid 60 to Jackson State in 2017
    assert r['ot'] in ('0', '1') and (r['ot'] == '1' or fh != fa), r      # a tie at the final is only possible in the overtime era's data errors
    assert r['home_div'] == 'fbs' or r['away_div'] == 'fbs', r
    seasons.add(int(r['season']))
assert min(seasons) == 2006 and max(seasons) >= 2022, seasons

# 3b. the home spread's sign (minus = home favored), checked against the results season by season. Until Nov 12,
# 2026 the table carried the wrong sign on 5,644 of 13,127 games (every game whose lines-file label was not ESPN's
# abbreviation fell back to the play by play's spread, signed the other way): the correlation between the final
# home margin and the home team being favored read -0.5 in 2021-25. A right table reads +0.65 to +0.76.
def corr(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx, syy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
    return sxy / (sxx * syy) ** 0.5
by_season = {}
for r in rows:
    by_season.setdefault(int(r['season']), []).append((int(r['fh']) - int(r['fa']), -float(r['home_spread'])))
for season, pairs in sorted(by_season.items()):
    c = corr([p[0] for p in pairs], [p[1] for p in pairs])
    assert c > 0.55, f'cfb_games.csv {season}: final home margin against the home spread correlates {c:+.2f}; the spread is signed the wrong way'
    fav = sum(1 for p in pairs if p[1] > 0) / len(pairs)
    assert 0.55 < fav < 0.72, f'cfb_games.csv {season}: home team favored in {100 * fav:.0f}% of games'
by_id = {r['game_id']: r for r in rows}
for gid, away, home, sp in [('401752677', 'Texas', 'Ohio State', -2.0), ('292460254', 'Utah State', 'Utah', -20.5), ('292460189', 'Troy', 'Bowling Green', 7.5)]:
    g = by_id[gid]
    assert (g['away'], g['home']) == (away, home) and float(g['home_spread']) == sp, g      # Ohio State laid 2 to Texas; Troy laid 7.5 at Bowling Green
# the timetable the trust study reads carries the same spreads
ht = list(csv.DictReader(open(os.path.join(ROOT, 'data', 'half_times_cfb.csv'))))
assert len(ht) > 2000 and all(abs(float(r['home_spread']) - float(by_id[r['game_id']]['home_spread'])) < 1e-9 for r in ht if r['game_id'] in by_id)
assert corr([int(r['fh']) - int(r['fa']) for r in ht], [-float(r['home_spread']) for r in ht]) > 0.6
# with the favorite named right, the block carries the trailing-favorite terms: a favorite behind at the half
# scores more in the second half than the same score with the dog behind
assert orig['coef'][4] < 0 and orig['coef'][5] > 0, orig['coef']
assert HalfModel('cfb', 55.5, -10, 10, 17).mu_model > HalfModel('cfb', 55.5, 10, 10, 17).mu_model + 0.5
print('cfb ok:', len(rows), 'games', min(seasons), '-', max(seasons), '; engine coef terms', len(orig['coef']), '; home spread sign checked on', len(by_season), 'seasons')

# 4. the NFL block by hand against the engine, and the NFL table (nflverse: home_spread is minus spread_line)
nfl = engine.MODEL['nfl']
for total, sp, h, a_ in [(47.5, -3, 17, 14), (41.5, 3, 7, 3), (47.5, -7, 3, 17), (52.5, -13.5, 31, 7)]:
    assert abs(HalfModel('nfl', total, sp, h, a_).mu_model - mu_by_hand(nfl, total, sp, h, a_)) < 1e-9, (total, sp, h, a_)
rows = list(csv.DictReader(open(os.path.join(ROOT, 'data', 'nfl_games.csv'))))
assert len(rows) >= 6900, len(rows)
ids = [r['game_id'] for r in rows]
assert len(set(ids)) == len(ids), 'duplicate game'
seasons = set()
for r in rows:
    h1h, h1a, fh, fa = int(r['h1h']), int(r['h1a']), int(r['fh']), int(r['fa'])
    assert fh >= h1h and fa >= h1a, r
    assert 25 < float(r['total']) < 70 and abs(float(r['home_spread'])) < 30, r
    assert r['ot'] in ('0', '1') and (r['ot'] == '1' or fh != fa), r      # a regulation tie needs overtime first
    seasons.add(int(r['season']))
assert min(seasons) == 2000 and max(seasons) >= 2025, seasons
g = next(r for r in rows if r['game_id'] == '2023_01_ARI_WAS')
assert (g['h1a'], g['h1h'], g['fa'], g['fh'], g['total'], g['home_spread']) == ('13', '10', '16', '20', '38.0', '-7.0'), g   # WAS laid 7 and won 20-16
print('nfl ok:', len(rows), 'games', min(seasons), '-', max(seasons), '; engine coef terms', len(nfl['coef']))
