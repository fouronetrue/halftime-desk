"""Polymarket's totals ladder for the same game, no network: the slug for an ESPN game and the parse of a Gamma
event into the desk's quote shape (Over bid and ask in cents, the Under side as the mirror), full game and first
half apart, closed markets and markets without a quote left out."""
import sys, os, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import feeds

g = dict(sport='nba', date_et='2026-10-20', away=dict(abbr='BOS'), home=dict(abbr='DET'))
assert feeds.polymarket_slug(g) == 'nba-bos-det-2026-10-20'
assert feeds.polymarket_slug(dict(g, away=dict(abbr='NO'), home=dict(abbr='WSH'))) == 'nba-nop-was-2026-10-20', 'ESPN codes that Kalshi and Polymarket spell differently'
assert feeds.polymarket_slug(dict(g, sport='cfb')) is None, 'no slug scheme for college yet'

# the shape Gamma returns for a game event (fields as the API names them; prices in dollars; outcomes as JSON strings)
ev = {'slug': 'nba-bos-det-2026-10-20', 'title': 'Celtics vs. Pistons', 'markets': [
    {'question': 'Celtics vs. Pistons', 'sportsMarketType': 'moneyline', 'outcomes': '["Celtics", "Pistons"]', 'bestBid': 0.4, 'bestAsk': 0.51},
    {'question': 'Celtics vs. Pistons: O/U 222.5', 'sportsMarketType': 'totals', 'line': 222.5, 'outcomes': '["Over", "Under"]', 'outcomePrices': '["0.52", "0.48"]', 'bestBid': 0.49, 'bestAsk': 0.55, 'slug': 'celtics-pistons-ou-222-5'},
    {'question': 'Celtics vs. Pistons: O/U 218.5', 'sportsMarketType': 'totals', 'outcomes': '["Over", "Under"]', 'bestBid': 0.6, 'bestAsk': 0.66, 'conditionId': '0xabc'},
    {'question': 'Celtics vs. Pistons: O/U 224.5', 'sportsMarketType': 'totals', 'line': 224.5, 'outcomes': '["Over", "Under"]', 'bestBid': 0.999, 'bestAsk': 1, 'closed': True},
    {'question': 'Celtics vs. Pistons: O/U 226.5', 'sportsMarketType': 'totals', 'line': 226.5, 'outcomes': '["Over", "Under"]', 'bestAsk': 0.4},
    {'question': 'Celtics vs. Pistons: 1H O/U 114.5', 'sportsMarketType': 'first_half_totals', 'line': 114.5, 'outcomes': '["Over", "Under"]', 'bestBid': 0.45, 'bestAsk': 0.53},
    {'question': 'Spread: Pistons (-1.5)', 'sportsMarketType': 'spreads', 'line': -1.5, 'outcomes': '["Pistons", "Celtics"]', 'bestBid': 0.5, 'bestAsk': 0.54},
]}
fg = feeds.polymarket_totals(ev, 'fg')
assert fg == {222.5: dict(y=55, yb=49, n=51, nb=45, ticker='celtics-pistons-ou-222-5'),
              218.5: dict(y=66, yb=60, n=40, nb=34, ticker='0xabc')}, fg
h1 = feeds.polymarket_totals(ev, '1h')
assert h1 == {114.5: dict(y=53, yb=45, n=55, nb=47, ticker=None)}, h1
assert feeds.polymarket_totals({'markets': []}) == {} and feeds.polymarket_totals(None) == {}
print('venues: slug, full-game and first-half totals parsed, the closed and unquoted markets left out')
print('venues: ok')
