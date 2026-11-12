"""Manual desk: price a halftime spot from the command line (same engine the watcher uses).
Example:
  python cli.py --sport nfl --away BUF --home LAR --spread -3.5 --total 55.5 --half 13-7 --quotes "45.5y59,48.5y47,51.5n66"
Quotes are Kalshi asks in cents: <line>y<yes ask> and/or <line>n<no ask>. Lines without quotes are priced from the model only."""
import argparse, json, os
import engine

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--sport', default='nfl', choices=['nfl', 'cfb', 'nba', 'cbb'])
ap.add_argument('--away', default='Away'); ap.add_argument('--home', default='Home')
ap.add_argument('--spread', type=float, required=True, help='home line at kickoff, minus = home favored')
ap.add_argument('--total', type=float, required=True)
ap.add_argument('--half', required=True, help='away-home score at the half, e.g. 13-7')
ap.add_argument('--quotes', default='', help='e.g. 45.5y59,48.5y47,51.5n66')
ap.add_argument('--mode', default='fg', choices=['fg', '2h'])
ap.add_argument('--order', default=None, choices=['taker', 'maker'])
ap.add_argument('--center', type=float, default=None, help='the market full-game line at the half (NBA: Kalshi 50-50 line or a sharp 2H line plus the half); the model keeps center_model_pct of the center')
a = ap.parse_args()
cfg = json.load(open(os.path.join(HERE, 'config.json')))
h1a, h1h = [int(x) for x in a.half.split('-')]
cmp = (cfg.get('center_model_pct') or {}).get(a.sport)
center = None if a.center is None or cmp is None else a.center - (h1a + h1h)
# the spot lane the half sits in (config spots), applied the way the watcher applies it: a live cell's lean on the
# blended mean, its own side priced at the model's full weight inside the lane's band
sp = engine.spot_lane(a.sport, cfg.get('spots'), a.total, a.spread, h1h, h1a) if a.mode == 'fg' else None
live = sp if sp and sp['mode'] == 'live' else None
m = engine.HalfModel(a.sport, a.total, a.spread, h1h, h1a, center=center, center_w=1.0 if cmp is None else cmp / 100, lean=live['lean'] if live else 0.0)
quotes = {}
for part in [p for p in a.quotes.split(',') if p.strip()]:
    import re
    mm = re.match(r'^(\d+(?:\.\d+)?)([yn])(\d+)$', part.strip())
    if not mm:
        raise SystemExit(f'bad quote {part}')
    line, side, c = float(mm.group(1)), mm.group(2), int(mm.group(3))
    quotes.setdefault(line, {})[side] = c
fair = engine.fair_line(m, a.mode)
step = 2 if a.sport == 'nba' else 3 if a.sport == 'cbb' else 1   # Kalshi's NBA ladder runs every 2 points, its college one every 3 or so
lines = sorted(set(list(quotes) + [fair + step * k for k in range(-5, 6)]))
rows = engine.price_lines(m, lines, a.mode, cfg['margin_c'] / 100)
bank = float(cfg['bankroll'])
lo, hi = cfg.get('min_price_c', 15), cfg.get('max_price_c', 85)
ecap = cfg.get('edge_cap_c')
sug = engine.suggest(rows, quotes, a.order or cfg['order'], cfg['margin_c'] / 100, cfg['trust_pct'] / 100, bank, bank * cfg['risk_pct'] / 100, bank * cfg['cost_pct'] / 100, (lo, hi), cfg.get('mid_loss_cap'),
                     single_band=(max(lo, cfg.get('single_min_price_c') or 0), hi), lane=dict(live, band=tuple(cfg.get('lane_band_c') or (40, 60))) if live else None,
                     stake=1.0 if cfg.get('stake_scale') is None else float(cfg['stake_scale']), edge_cap=None if ecap is None else float(ecap) / 100)
sizing = dict(bankroll=bank, max_risk=bank * cfg['risk_pct'] / 100, max_cost=bank * cfg['cost_pct'] / 100, margin=cfg['margin_c'] / 100, mid_loss=cfg.get('mid_loss_cap'))
kind, head, body = engine.order_sheet(m, dict(away=a.away, home=a.home, h1a=h1a, h1h=h1h, spot_lane=sp), rows, sug, sizing, a.mode)
print(head); print(body)
print('\nfull ladder and resting limits:')
print(engine.describe(m, dict(away=a.away, home=a.home, h1a=h1a, h1h=h1h), rows, sug, a.mode, sizing=sizing))
print('\nladder (line: over% max take/rest | under% max take/rest)')
for r in rows:
    print(f"  {r['line']:5.1f}: {100*r['p_over']:4.0f}% {r['over_take']:2d}/{r['over_rest']:2d} | {100*r['p_under']:4.0f}% {r['under_take']:2d}/{r['under_rest']:2d}")
