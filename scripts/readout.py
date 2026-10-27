"""Readouts computed where the Supabase keys are (the nightly export job) and printed into data/desk as counts
and dollars only. Two things:

1. The shadow auto-order summary, one file per slate (data/desk/shadow/DATE.csv): per sport and mode, the
   orders trade.py planned, how many the ladder reached (the shadow fill model: the ask touched the resting
   bid), at the break or in play, by pair (the tight and the wide middle) and by seconds after the first look,
   the middles that would have filled both legs or one leg, and the P&L at the fill model split the same way.
   The orders table itself never leaves Supabase: no ticker, strike, price or id reaches the file. tests/export.py
   holds it to that. This is the readout the Nov 3 phase 1 go or no is read from.

2. The honest scorecard (data/desk/scorecard.md): the results table, which both the worker and the GitHub
   backup grade into (one row a game), plus the games only log/results.csv has (the ones graded before the
   mirror existed), one row a game window. The lead play per window by week and sport, the end-of-third window,
   the model against the market, the finals against the market, the resting-middle what-if, drift, the mismatch
   lane's shadow shots, the lines that came and went, and the shadow totals. The repo scorecard
   (python watch.py --scorecard) only sees what reaches the CSV; this one sees everything.

A break is a break for the stage that posted the order: a half order touched at the end of the third was
filled in play, after the score moved, whatever the phase label says.
"""
import csv, io, json, datetime as dt

BREAK_PHASES = {'half': ('half', 'early3', ''), 'q3': ('q3end', 'early4', '')}
FILLED = ('touched', 'filled', 'partial')
SHADOW_COLS = ['date_et', 'sport', 'mode', 'games', 'rest_orders', 'rest_cost', 'rest_touched', 'touched_break', 'touched_play',
               'tight_orders', 'tight_touched', 'wide_orders', 'wide_touched', 'other_orders', 'other_touched',
               'touch_under_60s', 'touch_1_5m', 'touch_5_15m', 'touch_later', 'touch_median_s',
               'middles', 'middles_both', 'middles_one', 'graded', 'pnl', 'pnl_both', 'pnl_lone', 'pnl_cost',
               'takes', 'takes_available', 'takes_pnl']
# Every NBA play through this slate was a quarter-break misread (claude/breaks-oct25.md): ESPN's "period 2, 0:00"
# priced as the half, "period 3, 0:00" as the end of the third. Fixed Oct 25 at 8:32 PM ET; a correctly read NBA
# break has never produced a directional play, so the scorecard shows the NBA record with and without them.
NBA_MISREAD_THROUGH = '2026-10-25'


def num(v):
    try:
        return None if v in (None, '') else float(v)
    except (TypeError, ValueError):
        return None


def at_break(o):
    return (o.get('touch_phase') or '') in BREAK_PHASES.get(o.get('stage') or 'half', BREAK_PHASES['half'])


def is_filled(o):
    return o.get('status') in FILLED


def shadow_rows(orders, day=None):
    """The per-slate summary rows from the orders table's rows (any slate; day filters by date_et when given)."""
    rows = [o for o in orders if day is None or str(o.get('date_et')) == str(day)]
    out = []
    for date_et in sorted({str(o.get('date_et')) for o in rows}):
        for sport in sorted({o.get('sport') or '' for o in rows if str(o.get('date_et')) == date_et}):
            for mode in sorted({o.get('mode') or '' for o in rows if str(o.get('date_et')) == date_et and (o.get('sport') or '') == sport}):
                mine = [o for o in rows if str(o.get('date_et')) == date_et and (o.get('sport') or '') == sport and (o.get('mode') or '') == mode]
                out.append(summarise(mine, date_et, sport, mode))
    return out


def summarise(mine, date_et, sport, mode):
    rest = [o for o in mine if o.get('kind') == 'rest']
    takes = [o for o in mine if o.get('kind') == 'take']
    touched = [o for o in rest if is_filled(o)]
    brk = [o for o in touched if at_break(o)]
    tight = [o for o in rest if o.get('reason') == 'rest_mid']
    wide = [o for o in rest if o.get('reason') == 'rest_mid wide']
    other = [o for o in rest if o not in tight and o not in wide]
    secs = sorted(int(o['touch_s']) for o in touched if o.get('touch_s') is not None)
    pairs = {}
    for o in rest:
        if o.get('pair'):
            pairs.setdefault((o.get('game_id'), o.get('stage'), o['pair'], o.get('reason')), []).append(o)
    both = [v for v in pairs.values() if sum(1 for o in v if is_filled(o)) >= 2]
    one = [v for v in pairs.values() if sum(1 for o in v if is_filled(o)) == 1]
    graded = [o for o in touched if num(o.get('pnl')) is not None]
    pnl_both = sum(num(o.get('pnl')) or 0 for v in both for o in v if num(o.get('pnl')) is not None)
    pnl_lone = sum(num(o.get('pnl')) or 0 for v in one for o in v if num(o.get('pnl')) is not None)
    tg = [o for o in takes if is_filled(o) and num(o.get('pnl')) is not None]
    return dict(date_et=date_et, sport=sport, mode=mode, games=len({o.get('game_id') for o in mine}),
                rest_orders=len(rest), rest_cost=round(sum(num(o.get('cost')) or 0 for o in rest), 2), rest_touched=len(touched),
                touched_break=len(brk), touched_play=len(touched) - len(brk),
                tight_orders=len(tight), tight_touched=sum(1 for o in tight if is_filled(o)),
                wide_orders=len(wide), wide_touched=sum(1 for o in wide if is_filled(o)),
                other_orders=len(other), other_touched=sum(1 for o in other if is_filled(o)),
                touch_under_60s=sum(1 for s in secs if s < 60), touch_1_5m=sum(1 for s in secs if 60 <= s < 300),
                touch_5_15m=sum(1 for s in secs if 300 <= s < 900), touch_later=sum(1 for s in secs if s >= 900),
                touch_median_s=secs[len(secs) // 2] if secs else '',
                middles=len(pairs), middles_both=len(both), middles_one=len(one),
                graded=len(graded), pnl=round(sum(num(o['pnl']) for o in graded), 2), pnl_both=round(pnl_both, 2), pnl_lone=round(pnl_lone, 2),
                pnl_cost=round(sum(num(o.get('cost')) or 0 for o in graded), 2),
                takes=len(takes), takes_available=sum(1 for o in takes if is_filled(o)), takes_pnl=round(sum(num(o['pnl']) for o in tg), 2))


def shadow_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=SHADOW_COLS, lineterminator='\n', extrasaction='ignore')
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


# ---------------- the honest scorecard ----------------
def dedupe(db_rows, csv_rows):
    """One row per game: the results table's row wins; a CSV row is kept only for a game the table lacks."""
    out = {}
    for r in db_rows:
        r = dict(r)
        r['date'] = str(r.get('date_et') or r.get('date') or '')
        r['src'] = 'db'
        out[(r.get('sport'), r.get('game'), r['date'])] = r
    for r in csv_rows:
        if r.get('settled_utc') == 'settled_utc':
            continue   # a header line among the rows (a bad merge) is not a game
        r = dict(r)
        r['date'] = str(r.get('date') or r.get('date_et') or '')
        k = (r.get('sport'), r.get('game'), r['date'])
        if k not in out:
            r['src'] = 'csv'
            out[k] = r
    return sorted(out.values(), key=lambda r: (r['date'], r.get('sport') or '', r.get('game') or ''))


def sheet_of(r, key='sheet'):
    s = r.get(key)
    if isinstance(s, str):
        try:
            s = json.loads(s)
        except ValueError:
            s = None
    return s if isinstance(s, dict) else None


def list_of(r, key):
    v = r.get(key)
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = None
    return v if isinstance(v, list) else []


def week_start(date):
    """The Tuesday that starts the desk week (the unit resets on Tuesday)."""
    d = dt.date.fromisoformat(date)
    return d - dt.timedelta(days=(d.weekday() - 1) % 7)


def md(day):
    d = dt.date.fromisoformat(str(day))
    return f"{d.strftime('%b')} {d.day}"


def windows(rows):
    """Every graded game window as one record: the half (every row) and the NBA's end of the third (rows with
    q3_score). A window with plays_cost is a window the push led with a play."""
    out = []
    for r in rows:
        out.append(dict(sport=r.get('sport'), game=r.get('game'), date=r['date'], stage='half', cost=num(r.get('plays_cost')) or 0.0,
                        pnl=num(r.get('plays_pnl')) or 0.0, rest=num(r.get('rest_mid_pnl')), mid=num(r.get('mid_pnl')), src=r.get('src')))
        if r.get('q3_score') not in (None, ''):
            out.append(dict(sport=r.get('sport'), game=r.get('game'), date=r['date'], stage='q3', cost=num(r.get('q3_plays_cost')) or 0.0,
                            pnl=num(r.get('q3_plays_pnl')) or 0.0, rest=num(r.get('q3_rest_mid_pnl')), mid=num(r.get('q3_mid_pnl')), src=r.get('src')))
    return out


def misread(w):
    return w['sport'] == 'nba' and w['date'] <= NBA_MISREAD_THROUGH


def play_table(wins):
    """Lead play per game window by week and sport: plays, won, cost, P&L."""
    by = {}
    for w in wins:
        if not w['cost']:
            continue
        k = (week_start(w['date']), w['sport'])
        t = by.setdefault(k, dict(plays=0, won=0, cost=0.0, pnl=0.0, lo=w['date'], hi=w['date']))
        t['plays'] += 1
        t['won'] += 1 if w['pnl'] > 0 else 0
        t['cost'] += w['cost']
        t['pnl'] += w['pnl']
        t['lo'], t['hi'] = min(t['lo'], w['date']), max(t['hi'], w['date'])
    lines = ['| week | sport | plays | won | risked | P&L |', '|---|---|---|---|---|---|']
    weeks = sorted({k[0] for k in by})
    tot = dict(plays=0, won=0, cost=0.0, pnl=0.0)
    for wk in weeks:
        dates = [w['date'] for w in wins if week_start(w['date']) == wk]   # the week's graded slates, plays or not
        span = f"{md(min(dates))} to {md(max(dates))}"
        for (w0, sport), t in sorted(by.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            if w0 != wk:
                continue
            lines.append(f"| {span} | {sport.upper()} | {t['plays']} | {t['won']} | ${t['cost']:,.0f} | ${t['pnl']:+,.0f} |")
            for k2 in tot:
                tot[k2] += t[k2]
    lines.append(f"| all | all | {tot['plays']} | {tot['won']} | ${tot['cost']:,.0f} | ${tot['pnl']:+,.0f} |")
    bad = [w for w in wins if w['cost'] and misread(w)]
    if bad:
        bp = sum(w['pnl'] for w in bad)
        lines.append(f"| all, without the NBA misreads | all | {tot['plays'] - len(bad)} | {tot['won'] - sum(1 for w in bad if w['pnl'] > 0)} | "
                     f"${tot['cost'] - sum(w['cost'] for w in bad):,.0f} | ${tot['pnl'] - bp:+,.0f} |")
        lines.append('')
        lines.append(f"The NBA plays through the {md(NBA_MISREAD_THROUGH)} slate ({len(bad)}, ${bp:+,.0f}) were quarter-break misreads, fixed that night "
                     f"(claude/breaks-oct25.md). Read the NBA record from the next slate on.")
    return lines


def mean_se(xs):
    n = len(xs)
    if not n:
        return None, None, 0
    m = sum(xs) / n
    sd = (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return m, (sd / n ** 0.5 if n > 1 else 0.0), n


def versus(rows, key):
    """Finals against a line on the row (the market at the break, or the pregame total): mean, SE, n, over share."""
    xs = [num(r['final_total']) - num(r[key]) for r in rows if num(r.get('final_total')) is not None and num(r.get(key)) is not None]
    m, se, n = mean_se(xs)
    if not n:
        return ''
    z = m / se if se else 0.0
    flag = ' (past 2 SE, watch)' if abs(z) >= 2 and n >= 30 else ''
    return f"{m:+.1f} on {n} ({z:+.1f} SE), over {100 * sum(1 for x in xs if x > 0) / n:.0f}%{flag}"


def model_lines(rows):
    out = ['| sport | games | model closer | ties | miss: model | miss: market | finals vs the market at the break | finals vs the pregame total |',
           '|---|---|---|---|---|---|---|---|']
    for sport in sorted({r.get('sport') for r in rows}):
        both = [r for r in rows if r.get('sport') == sport and num(r.get('model_err')) is not None and num(r.get('mkt_err')) is not None]
        if not both:
            continue
        closer = sum(1 for r in both if num(r['model_err']) < num(r['mkt_err']))
        ties = sum(1 for r in both if num(r['model_err']) == num(r['mkt_err']))
        me = sum(num(r['model_err']) for r in both) / len(both)
        ke = sum(num(r['mkt_err']) for r in both) / len(both)
        out.append(f"| {sport.upper()} | {len(both)} | {closer} | {ties} | {me:.1f} | {ke:.1f} | {versus(both, 'mkt')} | {versus(both, 'total')} |")
    return out


def drift_lines(rows):
    """This season's finals against the model's own second-half number (the sheet's mu_model and the break score),
    the fair line when a row carries no sheet (the CSV-only games). Past 2 SE on 30+ games is the watch flag."""
    by = {}
    for r in rows:
        T = num(r.get('final_total'))
        if T is None:
            continue
        sh = sheet_of(r)
        if sh and sh.get('mu_model') is not None and sh.get('h1a') is not None and sh.get('h1h') is not None:
            resid, how = T - float(sh['h1a']) - float(sh['h1h']) - float(sh['mu_model']), 'model'
        elif num(r.get('fair')) is not None:
            resid, how = T - num(r['fair']), 'fair line'
        else:
            continue
        by.setdefault((r.get('sport'), how), []).append(resid)
    out = []
    for (sport, how), rs in sorted(by.items(), key=lambda kv: str(kv[0])):
        m, se, n = mean_se(rs)
        z = m / se if se else 0.0
        out.append(f"- {sport.upper()}: finals vs the {how} {m:+.1f} on {n} game{'s' if n != 1 else ''} ({z:+.1f} SE)" + (' (past 2 SE, watch)' if abs(z) >= 2 and n >= 30 else ''))
    return out


def rest_lines(wins):
    out = ['| sport | window | games | hits | P&L |', '|---|---|---|---|---|']
    for sport in sorted({w['sport'] for w in wins}):
        for stage in ('half', 'q3'):
            ws = [w for w in wins if w['sport'] == sport and w['stage'] == stage and w['rest'] is not None]
            if ws:
                out.append(f"| {sport.upper()} | {'half' if stage == 'half' else 'end of 3rd'} | {len(ws)} | {sum(1 for w in ws if w['rest'] > 0)} | ${sum(w['rest'] for w in ws):+,.0f} |")
    return out


def shot_lines(rows):
    """The mismatch lane's shadow shots (college 28+ spreads), graded as what-ifs from the sheet."""
    shots = []
    for r in rows:
        sh = sheet_of(r)
        T = num(r.get('final_total'))
        if not sh or T is None:
            continue
        for x in ((sh.get('shot') or {}).get('picks') or [])[:1]:
            win = T > x['line'] if x['kind'] == 'over' else T < x['line']
            shots.append(dict(date=r['date'], win=win, pnl=(x['contracts'] - x['cost']) if win else -x['cost'], cost=x['cost']))
    if not shots:
        return ['- no graded shots yet (the first Saturday of SHOT lines is Oct 31)']
    out = ['| slate | shots | won | risked | P&L |', '|---|---|---|---|---|']
    for date in sorted({s['date'] for s in shots}):
        ss = [s for s in shots if s['date'] == date]
        out.append(f"| {md(date)} | {len(ss)} | {sum(1 for s in ss if s['win'])} | ${sum(s['cost'] for s in ss):,.0f} | ${sum(s['pnl'] for s in ss):+,.0f} |")
    out.append(f"| all | {len(shots)} | {sum(1 for s in shots if s['win'])} | ${sum(s['cost'] for s in shots):,.0f} | ${sum(s['pnl'] for s in shots):+,.0f} |")
    return out


def flicker_lines(rows):
    """Lines that cleared the edge in a priced row of a break and were not the push's play, graded at the best
    price they showed. Whether chasing them is worth it is answered by this count."""
    out = ['| sport | came and went | hit | P&L at best price |', '|---|---|---|---|']
    any_ = False
    for sport in sorted({r.get('sport') for r in rows}):
        fl = [f for r in rows if r.get('sport') == sport for key in ('flickers', 'flickers_q3') for f in list_of(r, key) if not f.get('pushed')]
        if not fl:
            continue
        any_ = True
        out.append(f"| {sport.upper()} | {len(fl)} | {sum(1 for f in fl if f.get('win'))} | ${sum(num(f.get('pnl')) or 0 for f in fl):+,.0f} |")
    return out if any_ else ['- nothing came and went yet']


def auto_lines(orders):
    rows = shadow_rows(orders)
    if not rows:
        return ['- no auto orders recorded yet']
    out = ['| sport | mode | nights | games | resting orders | would fill | at the break | middles both legs | one leg | P&L (both) | P&L (lone) |',
           '|---|---|---|---|---|---|---|---|---|---|---|']
    for sport in sorted({r['sport'] for r in rows}):
        for mode in sorted({r['mode'] for r in rows if r['sport'] == sport}):
            rs = [r for r in rows if r['sport'] == sport and r['mode'] == mode]
            s = lambda k: sum(r[k] for r in rs)
            out.append(f"| {sport.upper()} | {mode} | {len(rs)} | {s('games')} | {s('rest_orders')} | {s('rest_touched')} | {s('touched_break')} | "
                       f"{s('middles_both')} of {s('middles')} | {s('middles_one')} | ${s('pnl_both'):+,.0f} | ${s('pnl_lone'):+,.0f} |")
    return out


def scorecard_md(db_rows, csv_rows, orders, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = dedupe(db_rows, csv_rows)
    wins = windows(rows)
    n_db = sum(1 for r in rows if r['src'] == 'db')
    n_csv = len(rows) - n_db
    lines = ['# Halftime Desk scorecard', '',
             f"Written by the nightly export on {now.strftime('%Y-%m-%d')} (UTC) from the Supabase results table ({n_db} games, graded by the worker "
             f"and the GitHub backup) plus the {n_csv} games only log/results.csv has (graded before the mirror existed). One row a game window; "
             f"{len(wins)} windows on {len(rows)} games. The repo scorecard (python watch.py --scorecard) sees only what reached the CSV; this one sees everything.",
             '', '## Lead play per game window', '',
             'The play the push led with: the first single, or the middle when it led. The end-of-third window (NBA) is its own window.', '']
    lines += play_table(wins)
    q3 = [w for w in wins if w['stage'] == 'q3']
    if q3:
        q3p = [w for w in q3 if w['cost']]
        lines += ['', f"End of 3rd (NBA): {len(q3)} windows graded, {len(q3p)} with a play, ${sum(w['pnl'] for w in q3p):+,.0f} on ${sum(w['cost'] for w in q3p):,.0f}."]
    lines += ['', '## Model against the market', '',
              'Miss is the distance from the final total. Finals vs a line is the final minus that line (plus means the overs hit); the pregame total is the closing line the game was priced off.', '']
    lines += model_lines(rows)
    lines += ['', '## Drift (this season against the model)', ''] + (drift_lines(rows) or ['- nothing graded'])
    lines += ['', '## Resting middles, what-if (assumes both legs filled)', ''] + rest_lines(wins)
    lines += ['', '## Mismatch lane (college 28+), shadow shots', ''] + shot_lines(rows)
    lines += ['', '## Came and went (cleared between pushes, not played)', ''] + flicker_lines(rows)
    lines += ['', '## Auto orders (shadow fill model: the ask touched the resting bid)', '',
              'Per slate in data/desk/shadow/. A fill at the break is the market handing the middle over; a fill in play is the game moving against the leg.', '']
    lines += auto_lines(orders)
    return '\n'.join(lines) + '\n'
