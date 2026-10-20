"""python scripts/build_nba_first_half_box.py <dir of play_by_play_YYYY.parquet> data/nba_first_half_box.csv
The parquet files are nba/pbp/parquet/play_by_play_YYYY.parquet in github.com/sportsdataverse/hoopR-nba-data
(about 20 MB a season, not kept in this repo). Needs pyarrow and pandas.
First-half box score from ESPN play-by-play: per game and team, the
first-half field goal attempts, three-point attempts, free throws (non-technical and technical), fouls
committed, turnovers, offensive rebounds, points, and the possession estimate FGA - OREB + TOV + 0.44 x FTA.
Writes one row per game."""
import sys, os, re, csv
import pyarrow.parquet as pq
import pandas as pd

src_dir, dst = sys.argv[1], sys.argv[2]
out = []
TOV_WORDS = ('Turnover', 'Traveling', 'Charge', 'Violation', 'Kicked Ball', 'Double Dribble', 'Palming', 'Illegal Dribble', 'Bad Pass')
for f in sorted(os.listdir(src_dir)):
    if not f.endswith('.parquet'):
        continue
    cols = ['game_id', 'game_date', 'season', 'season_type', 'home_team_id', 'away_team_id', 'home_team_abbrev', 'away_team_abbrev',
            'period_number', 'type_text', 'shooting_play', 'score_value', 'team_id', 'text', 'home_score', 'away_score', 'game_spread', 'home_team_spread', 'home_favorite']
    df = pq.read_table(os.path.join(src_dir, f), columns=cols).to_pandas()
    h1 = df[df['period_number'] <= 2].copy()
    tt = h1['type_text'].fillna('')
    is_ft = tt.str.startswith('Free Throw')
    h1['fga'] = (h1['shooting_play'] == True) & ~is_ft
    h1['tpa'] = h1['fga'] & h1['text'].fillna('').str.contains('three point', case=False)
    h1['ft'] = is_ft & ~tt.str.contains('Technical')
    h1['ft_tech'] = is_ft & tt.str.contains('Technical')
    h1['foul'] = tt.str.contains('Foul') & ~tt.str.contains('Turnover')
    h1['tov'] = tt.apply(lambda s: any(w in s for w in TOV_WORDS))
    h1['oreb'] = (tt == 'Offensive Rebound') & ~h1['text'].fillna('').str.contains('team rebound', case=False)   # the box score counts player rebounds only
    h1['pts'] = h1['score_value'].fillna(0).astype(float)
    agg = h1.groupby(['game_id', 'team_id'])[['fga', 'tpa', 'ft', 'ft_tech', 'foul', 'tov', 'oreb', 'pts']].sum()
    meta = df.groupby('game_id').agg(game_date=('game_date', 'first'), season=('season', 'first'), season_type=('season_type', 'first'),
                                     home_team_id=('home_team_id', 'first'), away_team_id=('away_team_id', 'first'),
                                     home=('home_team_abbrev', 'first'), away=('away_team_abbrev', 'first'),
                                     home_final=('home_score', 'max'), away_final=('away_score', 'max'),
                                     espn_home_spread=('home_team_spread', 'first'))
    # halftime score: the last row of period 2
    p2 = df[df['period_number'] == 2].groupby('game_id').agg(h1h=('home_score', 'max'), h1a=('away_score', 'max'))
    n = 0
    for gid, m in meta.iterrows():
        try:
            hrow = agg.loc[(gid, float(m['home_team_id']))]
            arow = agg.loc[(gid, float(m['away_team_id']))]
        except KeyError:
            continue
        if gid not in p2.index:
            continue
        def poss(r):
            return float(r['fga'] - r['oreb'] + r['tov'] + 0.44 * r['ft'])
        out.append(dict(game_id=gid, date=str(m['game_date'])[:10], season=int(m['season']), season_type=int(m['season_type']), home=str(m['home']).lower(), away=str(m['away']).lower(),
                        h1h=int(p2.loc[gid, 'h1h']), h1a=int(p2.loc[gid, 'h1a']), final_h=int(m['home_final']), final_a=int(m['away_final']),
                        espn_home_spread=m['espn_home_spread'],
                        h_fga=int(hrow['fga']), a_fga=int(arow['fga']), h_tpa=int(hrow['tpa']), a_tpa=int(arow['tpa']),
                        h_ft=int(hrow['ft']), a_ft=int(arow['ft']), h_ft_tech=int(hrow['ft_tech']), a_ft_tech=int(arow['ft_tech']),
                        h_foul=int(hrow['foul']), a_foul=int(arow['foul']), h_tov=int(hrow['tov']), a_tov=int(arow['tov']),
                        h_oreb=int(hrow['oreb']), a_oreb=int(arow['oreb']), h_poss=round(poss(hrow), 2), a_poss=round(poss(arow), 2)))
        n += 1
    print(f, len(df), 'rows', n, 'games')
with open(dst, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
    w.writeheader(); w.writerows(out)
print(len(out), 'games written to', dst)
