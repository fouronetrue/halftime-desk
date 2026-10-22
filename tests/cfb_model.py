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
print('cfb_model ok:', len(rows), 'games', min(seasons), '-', max(seasons), '; engine coef terms', len(orig['coef']))
