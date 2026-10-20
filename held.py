"""Held-position watch: a middle on a total you already own, before kickoff.

You bought a side of a full-game total (a Sharp pick, a tip, your own call) and the line moved. The other side
on a strike a few points away may now be cheap enough that owning both wins big on a final inside the window
and loses only a little anywhere else. This module looks at every open total position each minute pregame,
prices the other side from the same Kalshi events list the watcher already pulls, and pushes once when a
middle clears the project breakeven (pair cost under 0.97 + 3.5c per winning number NFL, 2.4c CFB, 2.9c NBA, fees in),
sized so a miss never costs more than MAX_LOSS. It pushes again only when the middle gets 2c a pair better.

Positions and the price you paid come from Supabase (positions, bets), kept fresh by the worker's portfolio
sync. Read-only: nothing here places, cancels or changes an order. Games at the half are left to the engine.
"""
import re, time
import engine, feeds, store, notify

MAX_LOSS = 15.0                                        # dollars a miss may cost on the paired shares
BREAKEVEN_BASE = 0.97
PER_NUMBER = {'nfl': 0.035, 'cfb': 0.024, 'nba': 0.029}  # project rule, same numbers as app/lib/desk.js (NBA: 2.9c, a number at fair lands 2.9% of the time)
BAND = (15, 85)                                        # cents; outside it the book is too thin to trust
IMPROVE_C = 2.0                                        # cents a pair better before a repeat push
MIN_ROOM_C = 1.0                                       # a pair must sit at least this far under the breakeven
SPORT_OF = {'KXNFLTOTAL': 'nfl', 'KXNCAAFTOTAL': 'cfb', 'KXNBATOTAL': 'nba'}


def holdings():
    """Open full-game total positions with the average price paid, from Supabase.
    positions says what you hold; bets (the fills) say what you paid for it."""
    out = []
    for p in store.read('positions', {'select': 'ticker,event_ticker,position,total_traded',
                                      'settlement_status': 'eq.unsettled', 'position': 'neq.0'}):
        series = (p.get('event_ticker') or '').split('-')[0]
        if series not in SPORT_OF:
            continue
        n = float(p.get('position') or 0)
        if not n:
            continue
        side = 'yes' if n > 0 else 'no'
        fills = store.read('bets', {'select': 'count,cost', 'ticker': f"eq.{p['ticker']}", 'outcome_side': f'eq.{side}'})
        cnt = sum(float(f.get('count') or 0) for f in fills)
        cost = sum(float(f.get('cost') or 0) for f in fills)
        if cnt > 0:
            paid = 100 * cost / cnt
        elif p.get('total_traded'):
            paid = 100 * float(p['total_traded']) / abs(n)
        else:
            continue
        out.append(dict(ticker=p['ticker'], event_ticker=p['event_ticker'], sport=SPORT_OF[series], side=side,
                        shares=int(abs(n)), paid_c=round(paid, 1)))
    return out


def best_middle(h, mine, quotes, max_loss=MAX_LOSS):
    """The other side that pairs best with what you hold: most room under the breakeven. None when nothing clears.
    h: a holdings() row. mine: the strike you own. quotes: feeds.total_quotes() for the event."""
    pa = h['paid_c'] / 100
    per = PER_NUMBER[h['sport']]
    best = None
    for k, v in quotes.items():
        if h['side'] == 'yes':                         # you own the over at `mine`: buy No on a higher strike
            if not k > mine or v.get('n') is None:
                continue
            price, numbers, leg, lo, hi = v['n'], round(k - mine), ('under', k), mine + 0.5, k - 0.5
        else:                                          # you own the under at `mine`: buy Yes on a lower strike
            if not k < mine or v.get('y') is None:
                continue
            price, numbers, leg, lo, hi = v['y'], round(mine - k), ('over', k), k + 0.5, mine - 0.5
        if numbers < 1 or numbers > 10 or not (BAND[0] <= price <= BAND[1]):
            continue
        pb = price / 100
        c = pa + engine.fee_per(pa) + pb + engine.fee_per(pb)
        breakeven = BREAKEVEN_BASE + per * numbers
        slack = breakeven - c
        if 100 * slack < MIN_ROOM_C:
            continue
        loss = c - 1
        pairs = h['shares'] if loss <= 0 else min(h['shares'], int(max_loss / loss + 1e-9))
        if pairs < 1:
            continue
        cost = round(pairs * (pa + pb) + engine.order_fee(pairs, pa) + engine.order_fee(pairs, pb), 2)
        cand = dict(kind=leg[0], strike=leg[1], price_c=price, numbers=numbers, lo=lo, hi=hi, c=c, breakeven=breakeven,
                    slack_c=round(100 * slack, 1), pairs=pairs, cost=cost, leg_cost=round(pairs * pb, 2),
                    win=round(2 * pairs - cost, 2), lose=round(pairs - cost, 2))
        if best is None or cand['slack_c'] > best['slack_c']:
            best = cand
    return best


def target_c(h, numbers, want='under'):
    """The most to pay, in cents, for the other side so the pair still sits MIN_ROOM_C under the breakeven, fees in."""
    pa = h['paid_c'] / 100
    breakeven = BREAKEVEN_BASE + PER_NUMBER[h['sport']] * numbers - MIN_ROOM_C / 100
    best = 0
    for c in range(1, 100):
        pb = c / 100
        if pa + engine.fee_per(pa) + pb + engine.fee_per(pb) <= breakeven + 1e-9:
            best = c
    return best


def pair_up(rows):
    """Group holdings by event: a YES on a lower strike held together with a NO on a higher one is a built middle."""
    by_ev = {}
    for h in rows:
        by_ev.setdefault(h['event_ticker'], []).append(h)
    return by_ev


def summary(desk, max_loss=MAX_LOSS):
    """What Today shows under Your totals: every open full-game total you hold, with the strike to pair it on,
    the most to pay there (so a limit order can rest), the live ask, and the sizing at that price. A YES and a NO
    on the same event read as a built middle. Written to desk_state 'held' by the worker once a minute."""
    out = {}
    for ev_ticker, hs in pair_up(holdings()).items():
        sport = hs[0]['sport']
        ev = next((e for e in desk.events(sport, 'total') if e.get('event_ticker') == ev_ticker), None)
        quotes = feeds.total_quotes(ev) if ev else {}
        rec_id, rec = next(((gid, r) for gid, r in desk.state.get('games', {}).items() if r.get('kalshi_total_event') == ev_ticker), (None, {}))
        name = (ev or {}).get('sub_title') or (ev or {}).get('title') or rec.get('name') or ev_ticker
        strikes = {}
        for h in hs:
            k = next((k for k, v in quotes.items() if v.get('ticker') == h['ticker']), None)
            if k is None:
                m = re.search(r'-(\d+)$', h['ticker'])
                k = float(m.group(1)) + 0.5 if m else None
            strikes[h['ticker']] = k
        yes = [h for h in hs if h['side'] == 'yes' and strikes[h['ticker']] is not None]
        no = [h for h in hs if h['side'] == 'no' and strikes[h['ticker']] is not None]
        built = []
        for a in sorted(yes, key=lambda h: strikes[h['ticker']]):
            for b in sorted(no, key=lambda h: strikes[h['ticker']]):
                ka, kb = strikes[a['ticker']], strikes[b['ticker']]
                if kb > ka:
                    pairs = min(a['shares'], b['shares'])
                    c = (a['paid_c'] + b['paid_c']) / 100
                    built.append(dict(over=ka, under=kb, pairs=pairs, lo=ka + 0.5, hi=kb - 0.5, paid_c=round(100 * c, 1),
                                      win=round(pairs * (2 - c), 2), lose=round(pairs * (1 - c), 2)))
        legs = []
        for h in hs:
            mine = strikes[h['ticker']]
            if mine is None:
                continue
            leg = dict(ticker=h['ticker'], side=h['side'], strike=mine, shares=h['shares'], paid_c=h['paid_c'], targets=[], best=None)
            if quotes and rec.get('phase') in (None, 'pre'):
                cands = sorted((k for k in quotes if (k > mine if h['side'] == 'yes' else k < mine)), key=lambda k: abs(k - mine))[:3]
                for k in cands:
                    numbers = round(abs(k - mine))
                    if not 1 <= numbers <= 10:
                        continue
                    q = quotes[k]
                    ask = q.get('n') if h['side'] == 'yes' else q.get('y')
                    leg['targets'].append(dict(kind='under' if h['side'] == 'yes' else 'over', strike=k, numbers=numbers,
                                               target_c=target_c(h, numbers), ask_c=ask))
                m = best_middle(h, mine, quotes, max_loss)
                if m:
                    leg['best'] = {k: m[k] for k in ('kind', 'strike', 'price_c', 'numbers', 'lo', 'hi', 'pairs', 'cost', 'leg_cost', 'win', 'lose', 'slack_c')}
                sell = sell_now(h, quotes.get(mine, {}))
                if sell:
                    leg['sell'] = sell
            legs.append(leg)
        out[ev_ticker] = dict(game=name, game_id=rec_id, sport=sport, phase=rec.get('phase'), legs=legs, built=built,
                              at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    return out


def sell_now(h, quote):
    """What closing the position at the current bid would make, after the taker fee. None with no bid."""
    bid = quote.get('yb') if h['side'] == 'yes' else quote.get('nb')
    if not bid:
        return None
    p = bid / 100
    return dict(bid_c=bid, pnl=round(h['shares'] * (p - h['paid_c'] / 100) - engine.order_fee(h['shares'], p), 2))


def text(h, mine, m, sell, game_name):
    side = 'Over' if h['side'] == 'yes' else 'Under'
    other = 'No' if m['kind'] == 'under' else 'Yes'
    out = [f"You hold {side} {mine:.1f}, {h['shares']} shares at {h['paid_c']:.0f}c.", '',
           f"MIDDLE: Buy {other} on {m['kind'].upper()} {m['strike']:.1f} at {m['price_c']}c, {m['pairs']} shares (${m['leg_cost']:.0f}).",
           f"Final {m['lo']:.0f} to {m['hi']:.0f} = both pay, +${m['win']:.0f}. Any other final = {engine.money(m['lose'])}.",
           f"Pair cost {100 * m['c']:.1f}c against a breakeven of {100 * m['breakeven']:.1f}c, {m['slack_c']:.1f}c of room."]
    if m['pairs'] < h['shares']:
        out.append(f"The other {h['shares'] - m['pairs']} shares stay a single, to keep a miss under ${MAX_LOSS:.0f}.")
    if sell:
        out.append(f"Or SELL now at {sell['bid_c']}c: {engine.money(sell['pnl'])}.")
    out.append('Nothing is placed for you; you tap buy.')
    return f'MIDDLE OPEN: {game_name}', '\n'.join(out)


def check(desk, push=None, max_loss=MAX_LOSS):
    """One look at every held total. Pushes a MIDDLE OPEN alert the first time a middle clears the breakeven, and
    again only when it gets IMPROVE_C a pair better. Returns the (title, body) pairs pushed."""
    push = push or notify.push
    if not store.enabled():
        return []
    held = desk.state.setdefault('held', {})
    sent = []
    for h in holdings():
        ev = next((e for e in desk.events(h['sport'], 'total') if e.get('event_ticker') == h['event_ticker']), None)
        if not ev:
            continue
        rec = next((r for r in desk.state.get('games', {}).values() if r.get('kalshi_total_event') == h['event_ticker']), None)
        if rec and rec.get('phase') not in (None, 'pre'):
            continue                                   # at the half the engine prices middles; live needs the model
        quotes = feeds.total_quotes(ev)
        mine = next((k for k, v in quotes.items() if v.get('ticker') == h['ticker']), None)
        if mine is None:
            continue
        m = best_middle(h, mine, quotes, max_loss)
        last = held.get(h['ticker']) or {}
        if not m:
            continue
        if last and m['slack_c'] < float(last.get('slack_c', 0)) + IMPROVE_C:
            continue
        title, body = text(h, mine, m, sell_now(h, quotes[mine]), ev.get('sub_title') or ev.get('title') or h['event_ticker'])
        push(title, body, priority='high', tags='football')
        held[h['ticker']] = dict(kind=m['kind'], strike=m['strike'], price_c=m['price_c'], slack_c=m['slack_c'], pairs=m['pairs'],
                                 at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        sent.append((title, body))
    return sent
