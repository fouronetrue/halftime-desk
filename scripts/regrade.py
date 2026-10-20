"""Regrade every settled game from what was actually pushed.

For each game with a final in the games table and at least one alert, rebuild its results row from the first
PLAY push (the half, or Q3 when the half was a read), else the first push, exactly as watch.py settle() does
now. An alert sent before sheets were kept is rebuilt from its suggestions row. Rows for games with no alert
at all are left as they are. Safe to run again.

Usage: python scripts/regrade.py [--dry-run]    (needs SUPABASE_URL and SUPABASE_SECRET_KEY)
"""
import os, sys, argparse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import store, watch

RESULTS_COLUMNS = watch.RESULTS_COLUMNS


def main(dry_run=False):
    if not store.enabled():
        sys.exit('regrade: SUPABASE_URL and SUPABASE_SECRET_KEY are required')
    games = store.read('games', {'select': 'id,sport,short,date_et,away_abbr,home_abbr,final_away,final_home', 'final_away': 'not.is.null', 'limit': 5000})
    alerts = store.read('alerts', {'select': 'game_id,kind,slot,sent_at,suggestion_at,sheet', 'order': 'sent_at', 'limit': 10000})
    by_game = {}
    for a in alerts:
        by_game.setdefault(a['game_id'], []).append(a)
    desk = watch.Desk({}, {})
    changed, rows = 0, []
    for g in games:
        hits = by_game.get(g['id'])
        if not hits:
            continue
        pick = next((a for a in hits if a.get('kind') == 'play'), hits[0])
        sh = pick.get('sheet') or desk.sheet_from_suggestion(g['id'], pick.get('suggestion_at'))
        if not sh:
            print(f"{g['short']}: no sheet and no suggestions row for its push, left alone")
            continue
        sh.setdefault('kind', pick.get('kind')); sh.setdefault('slot', pick.get('slot'))
        T = int(g['final_away']) + int(g['final_home'])
        gr = watch.grade_sheet(sh, T)
        fair, mkt = sh.get('fair'), sh.get('mkt')
        row = dict(settled_at=watch.now_iso(), sport=g['sport'], game=g['short'], date_et=g['date_et'], half=f"{sh.get('h1a')}-{sh.get('h1h')}",
                   total=sh.get('total'), home_spread=sh.get('spread'), fair=fair, mkt=mkt,
                   final=f"{g['away_abbr']} {g['final_away']}, {g['home_abbr']} {g['final_home']}", final_total=T,
                   model_err=round(abs(T - float(fair)), 1) if fair is not None else None, mkt_err=round(abs(T - float(mkt)), 1) if mkt is not None else None,
                   n_plays=gr['n_plays'], plays_cost=gr['cost'], plays_pnl=gr['pnl'], mid_pnl=gr['mid_pnl'], plays=gr['detail'],
                   rest_mid=gr['rest_text'] or None, rest_mid_pnl=gr['rest_pnl'], game_id=g['id'], sheet=sh)
        rows.append(row)
        changed += 1
        print(f"{g['date_et']} {g['short']}: {pick['kind']} at the {pick['slot']}, final {T}, play {gr['pnl']:+.0f} on ${gr['cost']:.0f}, middle {gr['mid_pnl'] if gr['mid_pnl'] is not None else 'none'}{' (rebuilt)' if sh.get('rebuilt') else ''}")
    if dry_run:
        print(f'dry run: {changed} rows would be written')
        return
    for i in range(0, len(rows), 50):
        store.write('results', rows[i:i + 50], on_conflict='game_id')
    print(f'regraded {changed} games')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    main(ap.parse_args().dry_run)
