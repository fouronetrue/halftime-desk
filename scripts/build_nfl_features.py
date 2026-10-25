"""Per-game NFL features from the nflverse play by play, for the tail study (scripts/study_tails.py): the first
half (what is known at the break), the second half and overtime (how the game finished), and the schedule
(kickoff time, rest, venue, roof, surface, weather).

Sources (free): github.com/nflverse/nflverse-data releases/download/pbp/play_by_play_YYYY.parquet (save as
pbp_YYYY.parquet) and raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv (the schedule, with kickoff
times from 2000). Points per play come from the scoring events (TD to td_team, PAT, two-point try and FG to the
offense, safety and defensive two to the defense), not the running score columns, which glitch in some seasons;
built this way the first-half and second-half points match data/nfl_games.csv on all 7,058 games.

Usage: python -I scripts/build_nfl_features.py PBP_DIR games.csv data/nfl_features.csv.gz
"""
import os, sys, glob, re
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

COLS = ['game_id', 'play_id', 'season', 'posteam', 'defteam', 'home_team', 'away_team', 'game_half', 'qtr',
        'half_seconds_remaining', 'game_seconds_remaining', 'play_type', 'yards_gained', 'passing_yards', 'pass_attempt',
        'complete_pass', 'sack', 'interception', 'fumble_lost', 'touchdown', 'return_touchdown', 'td_team',
        'field_goal_result', 'kick_distance', 'extra_point_result', 'two_point_attempt', 'two_point_conv_result',
        'safety', 'punt_attempt', 'kickoff_attempt', 'own_kickoff_recovery', 'desc', 'fourth_down_converted',
        'fourth_down_failed', 'third_down_converted', 'third_down_failed', 'penalty', 'penalty_yards', 'penalty_team',
        'epa', 'success', 'no_huddle', 'qb_kneel', 'qb_spike', 'yardline_100', 'fixed_drive', 'fixed_drive_result',
        'total_home_score', 'total_away_score', 'timeout', 'qb_scramble', 'air_yards', 'shotgun', 'weather',
        'defensive_two_point_conv']


def per_game(t):
    t = t[t.game_id.notna()].copy()
    t = t.sort_values(['game_id', 'play_id'])
    for c in ['yards_gained', 'passing_yards', 'pass_attempt', 'complete_pass', 'sack', 'interception', 'fumble_lost',
              'touchdown', 'return_touchdown', 'two_point_attempt', 'safety', 'punt_attempt', 'kickoff_attempt',
              'own_kickoff_recovery', 'fourth_down_converted', 'fourth_down_failed', 'third_down_converted',
              'third_down_failed', 'penalty', 'penalty_yards', 'epa', 'success', 'no_huddle', 'qb_kneel', 'qb_spike',
              'timeout', 'qb_scramble', 'shotgun']:
        t[c] = pd.to_numeric(t[c], errors='coerce').fillna(0.0)
    pt = t.play_type.fillna('')
    off = pt.isin(['pass', 'run'])
    t['off'] = off.astype(float)
    t['passp'] = (pt == 'pass').astype(float)
    t['rushp'] = (pt == 'run').astype(float)
    t['yds'] = np.where(off, t.yards_gained, 0.0)
    t['pass_yds_net'] = np.where(pt == 'pass', t.yards_gained, 0.0)
    t['pass_yds_gross'] = np.where(pt == 'pass', t.passing_yards, 0.0)
    t['rush_yds'] = np.where(pt == 'run', t.yards_gained, 0.0)
    t['explosive'] = (off & (t.yards_gained >= 20)).astype(float)
    t['big_pass'] = ((pt == 'pass') & (t.yards_gained >= 30)).astype(float)
    t['to'] = t.interception + t.fumble_lost
    t['to_opp_terr'] = np.where(t.yardline_100 <= 40, t.to, 0.0)
    t['off_td'] = ((t.touchdown == 1) & off & (t.td_team == t.posteam)).astype(float)
    t['nonoff_td'] = ((t.touchdown == 1) & ((t.return_touchdown == 1) | (t.td_team == t.defteam))).astype(float)
    fg = t.field_goal_result.fillna('')
    t['fga'] = fg.isin(['made', 'missed', 'blocked']).astype(float)
    t['fgm'] = (fg == 'made').astype(float)
    t['fg_miss'] = fg.isin(['missed', 'blocked']).astype(float)
    t['fg_miss_short'] = (fg.isin(['missed', 'blocked']) & (pd.to_numeric(t.kick_distance, errors='coerce') < 45)).astype(float)
    xp = t.extra_point_result.fillna('')
    t['xpa'] = xp.isin(['good', 'failed', 'blocked', 'aborted']).astype(float)
    t['xp_miss'] = xp.isin(['failed', 'blocked', 'aborted']).astype(float)
    tp = t.two_point_conv_result.fillna('')
    t['twopa'] = tp.isin(['success', 'failure']).astype(float)
    t['twop_fail'] = (tp == 'failure').astype(float)
    t['onside'] = ((t.kickoff_attempt == 1) & t.desc.str.contains('onside', case=False, na=False)).astype(float)
    t['fourth_att'] = t.fourth_down_converted + t.fourth_down_failed
    t['fourth_fail_opp'] = np.where(t.yardline_100 <= 40, t.fourth_down_failed, 0.0)
    t['third_att'] = t.third_down_converted + t.third_down_failed
    t['off_epa'] = np.where(off, t.epa, 0.0)
    t['off_success'] = np.where(off, t.success, 0.0)
    t['pen_yds'] = np.where(t.penalty == 1, t.penalty_yards, 0.0)
    t['shotgun_p'] = np.where(off, t.shotgun, 0.0)
    t['nohuddle_p'] = np.where(off, t.no_huddle, 0.0)
    # points scored on each play, from the scoring events (the running score columns have glitches in some
    # seasons): a TD to td_team, a PAT, two-point try or FG to the offense, a safety or a defensive two to the defense
    xpg = (xp == 'good').astype(float)
    tpg = (tp == 'success').astype(float)
    dtp = pd.to_numeric(t.get('defensive_two_point_conv'), errors='coerce').fillna(0.0) if 'defensive_two_point_conv' in t else 0.0
    home_pts = (6 * t.touchdown * (t.td_team == t.home_team) + (xpg + 2 * tpg + 3 * t.fgm) * (t.posteam == t.home_team)
                + 2 * (t.safety + dtp) * (t.defteam == t.home_team))
    away_pts = (6 * t.touchdown * (t.td_team == t.away_team) + (xpg + 2 * tpg + 3 * t.fgm) * (t.posteam == t.away_team)
                + 2 * (t.safety + dtp) * (t.defteam == t.away_team))
    t['pts'] = home_pts + away_pts
    t['pts_home'] = home_pts
    run_margin = (home_pts - away_pts).groupby(t.game_id).cumsum()
    t['margin_pre'] = (run_margin - (home_pts - away_pts)).abs()
    t['pts_last2_h1'] = np.where((t.game_half == 'Half1') & (t.half_seconds_remaining <= 120), t.pts, 0.0)
    t['pts_q3'] = np.where(t.qtr == 3, t.pts, 0.0)
    t['pts_q4'] = np.where(t.qtr == 4, t.pts, 0.0)
    t['pts_last5'] = np.where((t.qtr == 4) & (t.game_seconds_remaining <= 300), t.pts, 0.0)
    t['pts_last2'] = np.where((t.qtr == 4) & (t.game_seconds_remaining <= 120), t.pts, 0.0)
    t['pts_garbage'] = np.where((t.qtr == 4) & (t.margin_pre >= 17), t.pts, 0.0)
    t['pts_close_q4'] = np.where((t.qtr == 4) & (t.margin_pre <= 8), t.pts, 0.0)

    stats = ['off', 'passp', 'rushp', 'yds', 'pass_yds_net', 'pass_yds_gross', 'rush_yds', 'explosive', 'big_pass',
             'pass_attempt', 'complete_pass', 'sack', 'interception', 'fumble_lost', 'to', 'to_opp_terr', 'off_td',
             'nonoff_td', 'fga', 'fgm', 'fg_miss', 'fg_miss_short', 'xpa', 'xp_miss', 'twopa', 'twop_fail', 'safety',
             'punt_attempt', 'onside', 'fourth_att', 'fourth_down_failed', 'fourth_fail_opp', 'third_att',
             'third_down_converted', 'off_epa', 'off_success', 'penalty', 'pen_yds', 'qb_kneel', 'shotgun_p',
             'nohuddle_p', 'qb_scramble', 'timeout', 'pts', 'pts_home']
    half = t.game_half.map({'Half1': 'h1', 'Half2': 'h2', 'Overtime': 'ot'})
    t['half'] = half
    g = t[t.half.notna()].groupby(['game_id', 'half'])[stats].sum().unstack('half')
    g.columns = [f'{h}_{s}' for s, h in g.columns]
    extra = t.groupby('game_id')[['pts_last2_h1', 'pts_q3', 'pts_q4', 'pts_last5', 'pts_last2', 'pts_garbage', 'pts_close_q4']].sum()
    g = g.join(extra)
    # per-team offense by half (home offense / away offense)
    t['side'] = np.where(t.posteam == t.home_team, 'home', np.where(t.posteam == t.away_team, 'away', None))
    tt = t[t.half.isin(['h1', 'h2']) & t.side.notna()].groupby(['game_id', 'half', 'side'])[['yds', 'pass_yds_net', 'to', 'off', 'off_epa']].sum()
    tt = tt.unstack(['half', 'side'])
    tt.columns = [f'{h}_{s}_{side}' for s, h, side in tt.columns]
    g = g.join(tt)
    # drives: red zone trips and how they ended, by half of the drive's first play
    d = t[off & t.fixed_drive.notna()].groupby(['game_id', 'fixed_drive']).agg(half=('half', 'first'), rz=('yardline_100', lambda s: float((s <= 20).any())),
                                                                              res=('fixed_drive_result', 'first'), team=('posteam', 'first'))
    d['rz_td'] = ((d.rz == 1) & (d.res == 'Touchdown')).astype(float)
    d['rz_empty'] = ((d.rz == 1) & ~d.res.isin(['Touchdown', 'Field goal'])).astype(float)
    d['drive'] = 1.0
    d['td_drive'] = (d.res == 'Touchdown').astype(float)
    dd = d[d.half.isin(['h1', 'h2'])].groupby(['game_id', 'half'])[['drive', 'rz', 'rz_td', 'rz_empty', 'td_drive']].sum().unstack('half')
    dd.columns = [f'{h}_{s}' for s, h in dd.columns]
    g = g.join(dd)
    g = g.join(t.groupby('game_id').weather.first().rename('weather_text'))
    return g.reset_index()


def main(pbp_dir, sched_csv, out_csv):
    frames = []
    for path in sorted(glob.glob(os.path.join(pbp_dir, 'pbp_*.parquet'))):
        names = pq.ParquetFile(path).schema_arrow.names
        t = pq.read_table(path, columns=[c for c in COLS if c in names]).to_pandas()
        for c in COLS:
            if c not in t:
                t[c] = np.nan
        f = per_game(t)
        frames.append(f)
        print(os.path.basename(path), len(f), 'games', flush=True)
    feat = pd.concat(frames, ignore_index=True)
    s = pd.read_csv(sched_csv)
    keep = ['game_id', 'game_type', 'weekday', 'gametime', 'location', 'away_rest', 'home_rest', 'away_moneyline',
            'home_moneyline', 'div_game', 'roof', 'surface', 'temp', 'wind', 'away_coach', 'home_coach', 'referee',
            'stadium', 'away_qb_name', 'home_qb_name']
    feat = feat.merge(s[keep], on='game_id', how='left')
    for c in feat.columns:
        if feat[c].dtype.kind == 'f':
            feat[c] = feat[c].round(3)
    feat.to_csv(out_csv, index=False)
    print(len(feat), 'games ->', out_csv)


if __name__ == '__main__':
    main(*sys.argv[1:4])
