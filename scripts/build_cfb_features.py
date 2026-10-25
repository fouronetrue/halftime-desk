"""Per-game FBS features from the cfbfastR play by play, for the tail study (scripts/study_tails.py): the first
half (what is known at the break), the second half and overtime, kickoff time, venue, conferences and Elo.

Source (free): github.com/sportsdataverse/sportsdataverse-data releases/download/cfbfastR_cfb_pbp/
play_by_play_YYYY.parquet (2014 on; save as pbp_YYYY.parquet). Missed PATs and two-point tries are read off the
touchdown play's text; the running score is made monotone per game. The study keeps a game's play-by-play
features only when its first-half points match data/cfb_games.csv (9,050 of 9,207 games 2014-2025).

Usage: python -I scripts/build_cfb_features.py PBP_DIR data/cfb_features.csv.gz
"""
import os, sys, glob, re
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

COLS = ['game_id', 'id_play', 'game_play_number', 'period', 'play_type', 'play_text', 'pos_team', 'def_pos_team',
        'home', 'away', 'pos_team_score', 'def_pos_team_score', 'pass', 'rush', 'yards_gained', 'sack', 'int',
        'turnover', 'downs_turnover', 'fg_inds', 'fg_made', 'yds_fg', 'punt', 'safety', 'kickoff_onside', 'down',
        'distance', 'yards_to_goal', 'penalty_flag', 'penalty_declined', 'penalty_offset', 'yds_penalty', 'EPA',
        'success', 'completion', 'pass_attempt', 'drive_id', 'drive_result', 'clock_minutes', 'clock_seconds',
        'start_date', 'neutral_site', 'conference_game', 'venue', 'home_team_conference', 'away_team_conference',
        'home_team_division', 'away_team_division', 'home_team_pregame_elo', 'away_team_pregame_elo', 'season',
        'season_type', 'week']

NONOFF_TD = {'Interception Return Touchdown', 'Fumble Return Touchdown', 'Punt Return Touchdown',
             'Kickoff Return Touchdown', 'Blocked Punt Touchdown', 'Fumble Recovery (Opponent) Touchdown',
             'Blocked Field Goal Touchdown', 'Missed Field Goal Return Touchdown', 'Defensive 2pt Conversion'}
OFF_TD = {'Rushing Touchdown', 'Passing Touchdown', 'Fumble Recovery (Own) Touchdown'}
PAT_MISS = re.compile(r'(PAT|KICK|EXTRA POINT|XP)[^)]{0,20}(MISS|BLOCK|NO GOOD|FAIL)|(MISS|BLOCK)[^)]{0,6}(PAT|KICK|EXTRA POINT)', re.I)
TWO_PT = re.compile(r'TWO[- ]?POINT|2[- ]?PT|2-POINT', re.I)
TWO_PT_FAIL = re.compile(r'(FAIL|NO GOOD|UNSUCCESSFUL|INCOMPLETE|INTERCEPT)', re.I)


def per_game(t):
    t = t[t.game_id.notna()].copy()
    t = t.sort_values(['game_id', 'game_play_number', 'id_play'], kind='mergesort')
    num = ['pass', 'rush', 'yards_gained', 'sack', 'int', 'turnover', 'downs_turnover', 'fg_inds', 'yds_fg', 'punt',
           'safety', 'kickoff_onside', 'down', 'distance', 'yards_to_goal', 'yds_penalty', 'EPA', 'success',
           'completion', 'pass_attempt', 'clock_minutes', 'clock_seconds', 'period']
    for c in num:
        t[c] = pd.to_numeric(t[c], errors='coerce')
    for c in ['pass', 'rush', 'sack', 'int', 'turnover', 'downs_turnover', 'fg_inds', 'punt', 'safety', 'kickoff_onside',
              'success', 'completion', 'pass_attempt']:
        t[c] = t[c].fillna(0.0)
    pt = t.play_type.fillna('')
    txt = t.play_text.fillna('')
    off = (t['pass'] == 1) | (t['rush'] == 1)
    t['off'] = off.astype(float)
    t['passp'] = (t['pass'] == 1).astype(float)
    t['rushp'] = ((t['rush'] == 1) & (t['pass'] != 1)).astype(float)
    yg = t.yards_gained.fillna(0.0)
    t['yds'] = np.where(off, yg, 0.0)
    t['pass_yds_net'] = np.where(t['pass'] == 1, yg, 0.0)
    t['rush_yds'] = np.where(t.rushp == 1, yg, 0.0)
    t['explosive'] = (off & (yg >= 20)).astype(float)
    t['big_pass'] = ((t['pass'] == 1) & (yg >= 30)).astype(float)
    fum_lost = pt.isin(['Fumble Recovery (Opponent)', 'Fumble Recovery (Opponent) Touchdown', 'Fumble Return Touchdown'])
    t['interception'] = t['int']
    t['fumble_lost'] = fum_lost.astype(float)
    t['to'] = t['int'] + t.fumble_lost
    t['to_opp_terr'] = np.where(t.yards_to_goal <= 40, t.to, 0.0)
    t['off_td'] = pt.isin(OFF_TD).astype(float)
    t['nonoff_td'] = pt.isin(NONOFF_TD - {'Defensive 2pt Conversion'}).astype(float)
    t['fga'] = t.fg_inds
    fgm = t.fg_made.astype(str).str.lower().isin(['true', '1', '1.0'])
    t['fgm'] = (fgm & (t.fg_inds == 1)).astype(float)
    t['fg_miss'] = ((t.fg_inds == 1) & ~fgm).astype(float)
    t['fg_miss_short'] = ((t.fg_inds == 1) & ~fgm & (t.yds_fg < 45)).astype(float)
    is_td = pt.str.contains('Touchdown') & ~pt.isin(['Defensive 2pt Conversion'])
    two = is_td & txt.str.contains(TWO_PT.pattern, flags=re.I, regex=True)
    t['twopa'] = two.astype(float)
    t['twop_fail'] = (two & txt.str.contains(TWO_PT_FAIL.pattern, flags=re.I, regex=True)).astype(float)
    t['xpa'] = (is_td & ~two).astype(float)
    t['xp_miss'] = (is_td & ~two & txt.str.contains(PAT_MISS.pattern, flags=re.I, regex=True)).astype(float)
    t['safety_p'] = t.safety
    t['punt_attempt'] = t.punt
    t['onside'] = t.kickoff_onside
    fourth = off & (t.down == 4)
    t['fourth_att'] = fourth.astype(float)
    t['fourth_down_failed'] = (fourth & (t.downs_turnover == 1)).astype(float)
    t['fourth_fail_opp'] = (fourth & (t.downs_turnover == 1) & (t.yards_to_goal <= 40)).astype(float)
    third = off & (t.down == 3)
    t['third_att'] = third.astype(float)
    t['third_down_converted'] = (third & (yg >= t.distance) & (t.to == 0)).astype(float)
    t['off_epa'] = np.where(off, t.EPA.fillna(0.0), 0.0)
    t['off_success'] = np.where(off, t.success, 0.0)
    pen = t.penalty_flag.astype(str).str.lower().isin(['true', '1']) & ~t.penalty_declined.astype(str).str.lower().isin(['true', '1']) \
        & ~t.penalty_offset.astype(str).str.lower().isin(['true', '1'])
    t['penalty'] = pen.astype(float)
    t['pen_yds'] = np.where(pen, t.yds_penalty.fillna(0.0).abs(), 0.0)
    # running score: the score after each play, home and away, made monotone (a score never goes down)
    hs = np.where(t.pos_team == t.home, t.pos_team_score, t.def_pos_team_score).astype(float)
    as_ = np.where(t.pos_team == t.home, t.def_pos_team_score, t.pos_team_score).astype(float)
    t['hs'] = pd.Series(hs, index=t.index).groupby(t.game_id).cummax()
    t['as'] = pd.Series(as_, index=t.index).groupby(t.game_id).cummax()
    t['hs'] = t.hs.groupby(t.game_id).ffill().fillna(0.0)
    t['as'] = t['as'].groupby(t.game_id).ffill().fillna(0.0)
    tot = t.hs + t['as']
    t['pts'] = (tot - tot.groupby(t.game_id).shift(1).fillna(0.0)).clip(lower=0)
    margin = (t.hs - t['as'])
    t['margin_pre'] = margin.groupby(t.game_id).shift(1).fillna(0.0).abs()
    clock = t.clock_minutes.fillna(0) * 60 + t.clock_seconds.fillna(0)
    t['pts_last2_h1'] = np.where((t.period == 2) & (clock <= 120), t.pts, 0.0)
    t['pts_q3'] = np.where(t.period == 3, t.pts, 0.0)
    t['pts_q4'] = np.where(t.period == 4, t.pts, 0.0)
    t['pts_last5'] = np.where((t.period == 4) & (clock <= 300), t.pts, 0.0)
    t['pts_last2'] = np.where((t.period == 4) & (clock <= 120), t.pts, 0.0)
    t['pts_garbage'] = np.where((t.period == 4) & (t.margin_pre >= 17), t.pts, 0.0)
    t['pts_close_q4'] = np.where((t.period == 4) & (t.margin_pre <= 8), t.pts, 0.0)
    t['half'] = np.where(t.period <= 2, 'h1', np.where(t.period <= 4, 'h2', 'ot'))

    stats = ['off', 'passp', 'rushp', 'yds', 'pass_yds_net', 'rush_yds', 'explosive', 'big_pass', 'pass_attempt',
             'completion', 'sack', 'interception', 'fumble_lost', 'to', 'to_opp_terr', 'off_td', 'nonoff_td', 'fga', 'fgm',
             'fg_miss', 'fg_miss_short', 'xpa', 'xp_miss', 'twopa', 'twop_fail', 'safety_p', 'punt_attempt', 'onside',
             'fourth_att', 'fourth_down_failed', 'fourth_fail_opp', 'third_att', 'third_down_converted', 'off_epa',
             'off_success', 'penalty', 'pen_yds', 'pts']
    g = t.groupby(['game_id', 'half'])[stats].sum().unstack('half')
    g.columns = [f'{h}_{s}' for s, h in g.columns]
    extra = t.groupby('game_id')[['pts_last2_h1', 'pts_q3', 'pts_q4', 'pts_last5', 'pts_last2', 'pts_garbage', 'pts_close_q4']].sum()
    g = g.join(extra)
    # halftime and final off the running score, to check against the game table
    h1 = t[t.period <= 2].groupby('game_id')[['hs', 'as']].max().rename(columns={'hs': 'pbp_h1h', 'as': 'pbp_h1a'})
    fin = t.groupby('game_id')[['hs', 'as']].max().rename(columns={'hs': 'pbp_fh', 'as': 'pbp_fa'})
    g = g.join(h1).join(fin)
    t['side'] = np.where(t.pos_team == t.home, 'home', np.where(t.pos_team == t.away, 'away', None))
    tt = t[t.half.isin(['h1', 'h2']) & t.side.notna()].groupby(['game_id', 'half', 'side'])[['yds', 'pass_yds_net', 'to', 'off', 'off_epa']].sum()
    tt = tt.unstack(['half', 'side'])
    tt.columns = [f'{h}_{s}_{side}' for s, h, side in tt.columns]
    g = g.join(tt)
    d = t[off & t.drive_id.notna()].groupby(['game_id', 'drive_id']).agg(half=('half', 'first'), rz=('yards_to_goal', lambda s: float((s <= 20).any())),
                                                                       res=('drive_result', 'first'))
    d['rz_td'] = ((d.rz == 1) & (d.res == 'TD')).astype(float)
    d['rz_empty'] = ((d.rz == 1) & ~d.res.isin(['TD', 'FG'])).astype(float)
    d['drive'] = 1.0
    d['td_drive'] = (d.res == 'TD').astype(float)
    dd = d[d.half.isin(['h1', 'h2'])].groupby(['game_id', 'half'])[['drive', 'rz', 'rz_td', 'rz_empty', 'td_drive']].sum().unstack('half')
    dd.columns = [f'{h}_{s}' for s, h in dd.columns]
    g = g.join(dd)
    meta = t.groupby('game_id')[['start_date', 'neutral_site', 'conference_game', 'venue', 'home_team_conference', 'away_team_conference',
                                 'home_team_division', 'away_team_division', 'home_team_pregame_elo', 'away_team_pregame_elo']].first()
    g = g.join(meta)
    return g.reset_index()


def main(pbp_dir, out_csv):
    frames = []
    for path in sorted(glob.glob(os.path.join(pbp_dir, 'pbp_*.parquet'))):
        names = pq.ParquetFile(path).schema_arrow.names
        t = pq.read_table(path, columns=[c for c in COLS if c in names]).to_pandas()
        for c in COLS:
            if c not in t:
                t[c] = np.nan
        f = per_game(t)
        f['season'] = int(re.search(r'(\d{4})', os.path.basename(path)).group(1))
        frames.append(f)
        print(os.path.basename(path), len(f), 'games', flush=True)
        del t
    feat = pd.concat(frames, ignore_index=True)
    for c in feat.columns:
        if feat[c].dtype.kind == 'f':
            feat[c] = feat[c].round(3)
    feat.to_csv(out_csv, index=False)
    print(len(feat), 'games ->', out_csv)


if __name__ == '__main__':
    main(*sys.argv[1:3])
