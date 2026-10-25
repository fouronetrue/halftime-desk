"""Tail study (Oct 24, 2026): the second halves that landed outside the middle 80 percent of the desk's number,
the games where an 80-90c side lost. How often, against the price; what they share, read against every other
game; what was knowable at the break; how they actually happened; and what is worth money.

Frames:
  model    the desk's own halftime distribution (engine.HalfModel form), each season scored by a block fit
           without it (leave one season out), every game: NFL 2000-2026, FBS 2006-2025
  book     the same shape recentered on the book's 2H line read during the break (data/odds_h2_*.csv, 2023 on)
  pregame  the full-game total against the closing total (for pregame bets)
Tails: "died" = P(Y <= y) <= a (an over priced 1 - a or more lost), "blew" = P(Y >= y) <= a (an under lost);
a = 0.10 (90c) and 0.20 (80c). Each game carries the model's own chance of each tail, so a bucket is read
against what the model expected, discreteness included. "Legs" = every half-point 2H strike priced 80-90c on
a side, averaged per game, scored win minus price in cents.

Features: data/nfl_features.csv.gz (scripts/build_nfl_features.py, nflverse play by play and schedule) and
data/cfb_features.csv.gz (scripts/build_cfb_features.py, cfbfastR play by play, 2014 on). Every feature is
tagged pre (known before kickoff), half (known at the break) or after (the second half itself).

Usage: python scripts/study_tails.py [calibration|buckets|named|after|predict|gate|middle|pregame|live|all]
       (predict needs scikit-learn)
"""
import os, re, sys, warnings
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine
import fit_cfb

warnings.filterwarnings('ignore')
GRID = np.arange(0, 131)                       # integer second-half points
STRIKES = np.arange(0.5, 90.5, 1.0)            # half-point second-half strikes
PRECIP = re.compile(r'rain|snow|shower|drizzle|sleet|flurr|storm|thunder', re.I)
P5 = {'SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12', 'FBS Independents'}
SPLIT = {'nfl': 2013, 'cfb': 2019}             # discovery seasons <= this, holdout after
OFFS = {'nfl': (0, -1.5, 1.5, -3, 3, -6, 6, -9, 9), 'cfb': (0, -2, 2, -4, 4, -8, 8, -12, 12)}


def block_fit(d, sport):
    y = ((d.fh + d.fa) - (d.h1h + d.h1a)).values.astype(float)
    live = engine.MODEL[sport]
    knee = live.get('knee', 14) if len(live['coef']) > 6 else None
    X = fit_cfb.features(d, knee)
    coef = fit_cfb.fit(X, y)
    mu = fit_cfb.mu_of(coef, X)
    k = float(np.sqrt(np.mean((y - mu) ** 2 / mu)))
    z = np.quantile((y - mu) / (k * np.sqrt(mu)), np.linspace(0, 1, 201))
    return dict(coef=coef, k=k, z=z, knee=knee)


def cdf(x, mu, sd, q):
    """engine.HalfModel.cdf, vectorized: x, mu, sd broadcast; q the 201 residual quantiles."""
    z = (np.asarray(x, float) - mu) / sd
    hi = np.clip(np.searchsorted(q, z, side='right'), 1, len(q) - 1)
    lo = hi - 1
    span = q[hi] - q[lo]
    f = (z - q[lo]) / np.where(span == 0, 1.0, span)
    p = (lo + f) / (len(q) - 1)
    p = np.where(z <= q[0], 0.0, p)
    p = np.where(z >= q[-1], 1.0, p)
    return np.clip(p, 0.0, 1.0)


def market_mu(center, k, q):
    """HalfModel's conversion of a market line (a median) to the mean that puts the block's median on it."""
    cm = np.array(center, float)
    for _ in range(5):
        cm = center - k * np.sqrt(np.maximum(8.0, cm)) * q[100]
    return np.maximum(8.0, cm)


def tails(y, mu, sd, q, prefix):
    """Where y landed: mid-PIT, the tail flags at 10 and 20 percent, and the model's own chance of each tail."""
    out = {}
    lo = cdf(y - 0.5, mu, sd, q)
    hi = cdf(y + 0.5, mu, sd, q)
    out[f'{prefix}pit'] = (lo + hi) / 2
    G = cdf(GRID[None, :] + 0.5, mu[:, None], sd[:, None], q)      # P(Y <= g)
    Gm = cdf(GRID[None, :] - 0.5, mu[:, None], sd[:, None], q)     # P(Y <= g - 1)
    for a in (0.10, 0.20):
        tag = int(round(a * 100))
        out[f'{prefix}died{tag}'] = (hi <= a + 1e-12).astype(int)
        out[f'{prefix}blew{tag}'] = ((1 - lo) <= a + 1e-12).astype(int)
        # model's own chance: P(Y <= y*) for the largest y* with P(Y <= y*) <= a, and the mirror on the high side
        okd = G <= a + 1e-12
        out[f'{prefix}e_died{tag}'] = np.where(okd.any(1), np.where(okd, G, 0).max(1), 0.0)
        oku = (1 - Gm) <= a + 1e-12
        out[f'{prefix}e_blew{tag}'] = np.where(oku.any(1), np.where(oku, 1 - Gm, 0).max(1), 0.0)
    return out


def load(sport):
    if sport == 'nfl':
        d = pd.read_csv(os.path.join(ROOT, 'data', 'nfl_games.csv'))
    else:
        d = pd.read_csv(os.path.join(ROOT, 'data', 'cfb_games.csv'))
    d = d[(d.total > 20) & (d.total < 100) & (d.home_spread.abs() < 60)].reset_index(drop=True)
    d['game_id'] = d.game_id.astype(str)
    d['h1'] = d.h1h + d.h1a
    d['y'] = (d.fh + d.fa) - d.h1
    d['final'] = d.fh + d.fa
    home_fav_by = -d.home_spread
    d['fav_by'] = home_fav_by.abs()
    m1 = d.h1h - d.h1a
    d['favm'] = np.where(home_fav_by >= 0, m1, -m1)
    d['margin'] = m1.abs()
    # the desk's halftime distribution, each season from a block fit without it
    mu = np.zeros(len(d)); k = np.zeros(len(d)); Q = np.zeros((len(d), 201))
    for s in sorted(d.season.unique()):
        te = (d.season == s).values
        b = block_fit(d[~te], sport)
        X = fit_cfb.features(d[te], b['knee'])
        mu[te] = fit_cfb.mu_of(b['coef'], X)
        k[te] = b['k']
        Q[te] = b['z']
    d['mu'] = mu
    d['sd'] = k * np.sqrt(mu)
    d['k'] = k
    # tails need one q per row; blocks differ only slightly by season, so evaluate season by season
    parts = []
    for s in sorted(d.season.unique()):
        te = (d.season == s).values
        q = Q[te][0]
        parts.append(pd.DataFrame(tails(d.y.values[te].astype(float), d.mu.values[te], d.sd.values[te], q, ''), index=d.index[te]))
        d.loc[te, 'median'] = d.mu.values[te] + d.sd.values[te] * q[100]
    d = d.join(pd.concat(parts))
    d['Qidx'] = d.season      # season block id, for the market frame
    blocks = {s: Q[(d.season == s).values][0] for s in d.season.unique()}
    return d, blocks


def add_market(d, sport, blocks):
    """The book's second-half line read during the break (DraftKings, 2023 on), as a full market center with the
    model's shape: the desk's ladder recentered on the book (sharp_model_pct 0)."""
    o = pd.read_csv(os.path.join(ROOT, 'data', f'odds_h2_{sport}.csv'), usecols=['game_id', 'line_med', 'n_books'])
    o['game_id'] = o.game_id.astype(str)
    d = d.merge(o, on='game_id', how='left')
    has = d.line_med.notna().values
    parts = []
    for s in sorted(d.season[has].unique()):
        te = has & (d.season == s).values
        q = blocks[s]
        k = d.k.values[te]
        mm = market_mu(d.line_med.values[te], k, q)
        parts.append(pd.DataFrame(tails(d.y.values[te].astype(float), mm, k * np.sqrt(mm), q, 'mk_'), index=d.index[te]))
    if parts:
        d = d.join(pd.concat(parts))
    return d


def add_pregame(d):
    """The full-game total against the closing total: z = (final - total) / (k sqrt(total)), the residual quantiles
    from the other seasons, centered so the closing total is the median."""
    T = d.total.values
    r = (d.final.values - T)
    k = np.sqrt(np.mean(r ** 2 / T))
    z_all = r / (k * np.sqrt(T))
    parts = []
    for s in sorted(d.season.unique()):
        te = (d.season == s).values
        q = np.quantile(z_all[~te], np.linspace(0, 1, 201))
        mu = T[te] - k * np.sqrt(T[te]) * q[100]          # the median on the closing total
        parts.append(pd.DataFrame(tails(d.final.values[te].astype(float), mu, k * np.sqrt(T[te]), q, 'pg_'), index=d.index[te]))
    return d.join(pd.concat(parts))


def _q(s, n=5):
    """Quantile bucket labels (Q1 low .. Qn high) on the non-missing values."""
    try:
        return pd.qcut(s, n, labels=[f'Q{i + 1}' for i in range(n)], duplicates='drop')
    except ValueError:
        return pd.Series(np.nan, index=s.index)


def nfl(b):
    f = pd.read_csv(os.path.join(ROOT, 'data', 'nfl_features.csv.gz'), low_memory=False)
    d = b.merge(f.drop(columns=[c for c in ('roof', 'temp', 'wind') if c in f]), on='game_id', how='left')
    d = d.copy()
    d['sport'] = 'nfl'
    # pregame
    hh = pd.to_numeric(d.gametime.str.slice(0, 2), errors='coerce')
    mm = pd.to_numeric(d.gametime.str.slice(3, 5), errors='coerce')
    tod = hh + mm / 60
    d['kick_et'] = tod
    d['slot'] = np.select([tod < 12, tod < 15, tod < 18, tod >= 18], ['morning (London)', '1 PM', '4 PM', 'night'], default=None)
    d['weekday2'] = d.weekday.where(d.weekday.isin(['Sunday', 'Monday', 'Thursday', 'Saturday']), 'other')
    roof = d.roof.fillna('')
    d['roof2'] = np.where(roof.isin(['dome', 'closed']), 'dome/closed', np.where(roof == 'outdoors', 'outdoors', np.where(roof == 'open', 'open roof', 'unknown')))
    surf = d.surface.fillna('').str.lower()
    d['turf'] = np.where(surf == '', np.nan, np.where(surf.str.contains('grass'), 0, 1))
    out = d.roof2 == 'outdoors'
    d['temp_b'] = np.where(out, pd.cut(d.temp, [-50, 32, 45, 60, 75, 150], labels=['32F or less', '33-45F', '46-60F', '61-75F', '76F+']).astype(str), 'indoors/unknown')
    d.loc[out & d.temp.isna(), 'temp_b'] = 'indoors/unknown'
    d['wind_b'] = np.where(out, pd.cut(d.wind, [-1, 5, 10, 15, 100], labels=['0-5 mph', '6-10 mph', '11-15 mph', '16+ mph']).astype(str), 'indoors/unknown')
    d.loc[out & d.wind.isna(), 'wind_b'] = 'indoors/unknown'
    d['precip'] = np.where(d.weather_text.isna(), np.nan, d.weather_text.fillna('').str.contains(PRECIP).astype(float))
    d.loc[~out, 'precip'] = np.nan
    d['div_game2'] = d.div_game
    d['neutral'] = (d.location == 'Neutral').astype(float)
    d['playoff'] = (d.season_type == 'POST').astype(float)
    d['short_rest'] = ((d.away_rest <= 5) | (d.home_rest <= 5)).astype(float)
    d['off_bye'] = ((d.away_rest >= 13) | (d.home_rest >= 13)).astype(float)
    d['week_b'] = pd.cut(d.week, [0, 4, 9, 14, 18, 30], labels=['wk 1-4', 'wk 5-9', 'wk 10-14', 'wk 15-18', 'playoffs']).astype(str)
    d.loc[d.season_type == 'POST', 'week_b'] = 'playoffs'
    d['era'] = pd.cut(d.season, [1999, 2005, 2010, 2015, 2020, 2027], labels=['2000-05', '2006-10', '2011-15', '2016-20', '2021-26']).astype(str)
    return _common(d, 'nfl')


def cfb(b):
    f = pd.read_csv(os.path.join(ROOT, 'data', 'cfb_features.csv.gz'), low_memory=False)
    b['game_id'] = b.game_id.astype(str)
    f['game_id'] = f.game_id.astype(str)
    d = b.merge(f.drop(columns=['season']), on='game_id', how='left')
    d = d.copy()
    d['sport'] = 'cfb'
    st = pd.to_datetime(d.start_date, utc=True, errors='coerce').dt.tz_convert('America/New_York')
    tod = st.dt.hour + st.dt.minute / 60
    d['kick_et'] = tod
    # midnight-to-6 AM ET starts are West Coast or Hawaii late games
    d['slot'] = np.select([(tod >= 6) & (tod < 12.75), (tod >= 12.75) & (tod < 17), (tod >= 17) & (tod < 21.5), (tod >= 21.5) | (tod < 6)],
                          ['noon window', 'afternoon (3:30)', 'evening (7-8)', 'late night (10:30+)'], default=None)
    d.loc[tod.isna(), 'slot'] = None
    wd = st.dt.day_name()
    d['weekday2'] = np.where(wd.isna(), None, np.where(wd == 'Saturday', 'Saturday', np.where(wd.isin(['Tuesday', 'Wednesday']), 'Tue/Wed',
                    np.where(wd == 'Thursday', 'Thursday', np.where(wd == 'Friday', 'Friday', 'other')))))
    d['neutral'] = d.neutral.astype(float)
    hc, ac = d.home_team_conference.fillna(''), d.away_team_conference.fillna('')
    p5h, p5a = hc.isin(P5), ac.isin(P5)
    d['matchup'] = np.where(hc.eq('') | ac.eq(''), None, np.where(p5h & p5a, 'power vs power', np.where(p5h ^ p5a, 'power vs G5', 'G5 vs G5')))
    d['conf_game'] = d.conference_game.astype(str).str.lower().isin(['true', '1', '1.0']).astype(float)
    d.loc[d.conference_game.isna(), 'conf_game'] = np.nan
    d['fcs_opp'] = ((d.away_div == 'fcs') | (d.home_div == 'fcs')).astype(float)
    d['playoff'] = (d.season_type.astype(str).str.lower() == 'postseason').astype(float)
    d['week_b'] = pd.cut(d.week, [-1, 2, 5, 9, 13, 30], labels=['wk 0-2', 'wk 3-5', 'wk 6-9', 'wk 10-13', 'wk 14+']).astype(str)
    d.loc[d.playoff == 1, 'week_b'] = 'bowls/playoff'
    d['era'] = pd.cut(d.season, [2005, 2013, 2016, 2019, 2022, 2026], labels=['2006-13', '2014-16', '2017-19', '2020-22', '2023-25']).astype(str)
    d['elo_gap'] = (d.home_team_pregame_elo - d.away_team_pregame_elo).abs()
    return _common(d, 'cfb')


def _common(d, sport):
    has = d.h1_off.notna()
    d['has_pbp'] = has.astype(int)
    if sport == 'cfb':
        # trust the play by play only where its halftime points match the game table
        bad = has & ((d.h1_pts != d.h1) | (d.h1_off > 110) | (d.h1_xpa > 12))
        for c in [c for c in d.columns if c.startswith(('h1_', 'h2_', 'ot_', 'pts_'))]:
            d.loc[bad, c] = np.nan
        d['has_pbp'] = (has & ~bad).astype(int)
    h = d.has_pbp == 1
    # halftime state
    d['state'] = pd.cut(d.favm, [-100, -8, -1, 0, 7, 14, 21, 100], labels=['fav down 8+', 'fav down 1-7', 'tied', 'fav up 1-7', 'fav up 8-14', 'fav up 15-21', 'fav up 22+']).astype(str)
    d['spread_b'] = (pd.cut(d.fav_by, [-1, 3, 7, 10.5, 14.5, 100], labels=['0-3', '3.5-7', '7.5-10.5', '11-14.5', '15+']) if sport == 'nfl'
                     else pd.cut(d.fav_by, [-1, 3, 7, 14, 21, 28, 100], labels=['0-3', '3.5-7', '7.5-14', '14.5-21', '21.5-28', '28+'])).astype(str)
    d['total_b'] = _q(d.total).astype(str)
    # first-half points against what the pregame total implied (a fit across all games)
    A = np.column_stack([np.ones(len(d)), d.total])
    c, *_ = np.linalg.lstsq(A, d.h1.values.astype(float), rcond=None)
    d['h1_vs_exp'] = d.h1 - A @ c
    d['h1_vs_exp_b'] = pd.cut(d.h1_vs_exp, [-100, -10, -4, 4, 10, 100], labels=['10+ under', '4-10 under', 'on pace', '4-10 over', '10+ over']).astype(str)
    if h.any():
        d['h1_ypp'] = d.h1_yds / d.h1_off
        d['h1_pass_rate'] = d.h1_passp / d.h1_off
        d['h1_kick_miss'] = d.h1_fg_miss + d.h1_xp_miss
        d['h1_pts_per100'] = 100 * d.h1 / d.h1_yds.clip(lower=1)
        # points against yards: the first half's points minus what its yards usually produce
        m = h & d.h1_yds.notna()
        A = np.column_stack([np.ones(m.sum()), d.loc[m, 'h1_yds'], d.loc[m, 'total']])
        cc, *_ = np.linalg.lstsq(A, d.loc[m, 'h1'].values.astype(float), rcond=None)
        d['h1_pts_vs_yds'] = np.nan
        d.loc[m, 'h1_pts_vs_yds'] = d.loc[m, 'h1'] - A @ cc
        # yards against the total: was the first half a shootout in yards, whatever the scoreboard says
        A2 = np.column_stack([np.ones(m.sum()), d.loc[m, 'total']])
        c2, *_ = np.linalg.lstsq(A2, d.loc[m, 'h1_yds'].values.astype(float), rcond=None)
        d['h1_yds_vs_exp'] = np.nan
        d.loc[m, 'h1_yds_vs_exp'] = d.loc[m, 'h1_yds'] - A2 @ c2
        A3 = np.column_stack([np.ones(m.sum()), d.loc[m, 'total']])
        c3, *_ = np.linalg.lstsq(A3, d.loc[m, 'h1_off'].values.astype(float), rcond=None)
        d['h1_plays_vs_exp'] = np.nan
        d.loc[m, 'h1_plays_vs_exp'] = d.loc[m, 'h1_off'] - A3 @ c3
        # who leads at the half, and did the trailing team move the ball
        home_lead = d.h1h > d.h1a
        tr_yds = np.where(home_lead, d.h1_yds_away, d.h1_yds_home)
        ld_yds = np.where(home_lead, d.h1_yds_home, d.h1_yds_away)
        d['trail_outgained'] = np.where(d.margin == 0, np.nan, (tr_yds > ld_yds).astype(float))
        d.loc[~h, 'trail_outgained'] = np.nan
        d['h1_third_rate'] = d.h1_third_down_converted / d.h1_third_att.replace(0, np.nan)
        d['h1_success_rate'] = d.h1_off_success / d.h1_off
        d['h2_ypp'] = d.h2_yds / d.h2_off
        d.loc[~h, [c for c in ('h1_ypp', 'h1_pass_rate', 'h1_kick_miss', 'h1_pts_per100', 'h1_third_rate', 'h1_success_rate', 'h2_ypp') if c in d]] = np.nan
    return d


def tagged_features(d, sport):
    """(name, label series, tag). Buckets are labeled for reading, quantiles as Q1 (low) .. Q5 (high)."""
    F = []
    def add(name, s, tag):
        F.append((name, s.astype(object).where(s.notna(), None), tag))
    def cnt(s, cuts, labels):
        return pd.cut(s, cuts, labels=labels).astype(str).where(s.notna(), None)
    # pregame
    add('kickoff slot (ET)', d.slot, 'pre')
    add('weekday', d.weekday2, 'pre')
    add('pregame total (quintile)', d.total_b, 'pre')
    add('spread size', d.spread_b, 'pre')
    add('season phase', d.week_b, 'pre')
    add('era', d.era, 'pre')
    add('neutral site', d.neutral.map({0.0: 'home field', 1.0: 'neutral'}), 'pre')
    add('playoff or bowl', d.playoff.map({0.0: 'regular season', 1.0: 'postseason'}), 'pre')
    if sport == 'nfl':
        add('roof', d.roof2, 'pre')
        add('surface', d.turf.map({0.0: 'grass', 1.0: 'turf'}), 'pre')
        add('temperature (outdoors)', d.temp_b, 'pre')
        add('wind (outdoors)', d.wind_b, 'pre')
        add('rain or snow (outdoors)', d.precip.map({0.0: 'dry', 1.0: 'rain/snow'}), 'pre')
        add('division game', d.div_game2.map({0: 'non-division', 1: 'division'}), 'pre')
        add('short rest (Thursday etc.)', d.short_rest.map({0.0: 'normal rest', 1.0: 'a team on short rest'}), 'pre')
        add('off a bye', d.off_bye.map({0.0: 'no bye', 1.0: 'a team off a bye'}), 'pre')
    else:
        add('matchup', d.matchup, 'pre')
        add('conference game', d.conf_game.map({0.0: 'non-conference', 1.0: 'conference'}), 'pre')
        add('FCS opponent', d.fcs_opp.map({0.0: 'FBS vs FBS', 1.0: 'FCS opponent'}), 'pre')
        add('Elo gap (quintile)', _q(d.elo_gap), 'pre')
    # at the half
    add('halftime state', d.state, 'half')
    add('1H points vs pregame pace', d.h1_vs_exp_b, 'half')
    if 'h1_ypp' in d:
        add('1H plays (pace, quintile)', _q(d.h1_plays_vs_exp), 'half')
        add('1H drives (quintile)', _q(d.h1_drive), 'half')
        add('1H yards vs pregame expectation (quintile)', _q(d.h1_yds_vs_exp), 'half')
        add('1H yards per play (quintile)', _q(d.h1_ypp), 'half')
        add('1H points vs what its yards usually score (quintile)', _q(d.h1_pts_vs_yds), 'half')
        add('1H pass rate (quintile)', _q(d.h1_pass_rate), 'half')
        add('1H passing yards (quintile)', _q(d.h1_pass_yds_net), 'half')
        add('1H rushing yards (quintile)', _q(d.h1_rush_yds), 'half')
        add('1H turnovers', cnt(d.h1_to, [-1, 0, 1, 2, 99], ['0', '1', '2', '3+']), 'half')
        add('1H turnovers in their own end (opp 40 in)', cnt(d.h1_to_opp_terr, [-1, 0, 1, 99], ['0', '1', '2+']), 'half')
        add('1H defensive or return TD', cnt(d.h1_nonoff_td, [-1, 0, 99], ['none', '1+']), 'half')
        add('1H missed FGs (incl. blocked)', cnt(d.h1_fg_miss, [-1, 0, 1, 99], ['0', '1', '2+']), 'half')
        add('1H missed short FGs (<45 yd)', cnt(d.h1_fg_miss_short, [-1, 0, 99], ['0', '1+']), 'half')
        add('1H missed PATs', cnt(d.h1_xp_miss, [-1, 0, 99], ['0', '1+']), 'half')
        add('1H missed kicks (FG + PAT)', cnt(d.h1_kick_miss, [-1, 0, 1, 99], ['0', '1', '2+']), 'half')
        add('1H red-zone trips with no points', cnt(d.h1_rz_empty, [-1, 0, 1, 99], ['0', '1', '2+']), 'half')
        add('1H failed 4th downs in opp territory', cnt(d.h1_fourth_fail_opp, [-1, 0, 99], ['0', '1+']), 'half')
        add('1H 4th-down tries', cnt(d.h1_fourth_att, [-1, 0, 1, 2, 99], ['0', '1', '2', '3+']), 'half')
        add('1H explosive plays 20+ (quintile)', _q(d.h1_explosive), 'half')
        add('1H sacks', cnt(d.h1_sack, [-1, 1, 3, 99], ['0-1', '2-3', '4+']), 'half')
        add('1H penalty yards (quintile)', _q(d.h1_pen_yds), 'half')
        add('1H points in the last 2 minutes', cnt(d.pts_last2_h1, [-1, 0, 7, 99], ['0', '1-7', '8+']), 'half')
        add('1H offensive EPA, both teams (quintile)', _q(d.h1_off_epa), 'half')
        add('1H success rate (quintile)', _q(d.h1_success_rate), 'half')
        add('1H third-down rate (quintile)', _q(d.h1_third_rate), 'half')
        add('1H punts (quintile)', _q(d.h1_punt_attempt), 'half')
        add('trailing team outgained the leader', d.trail_outgained.map({0.0: 'leader outgained', 1.0: 'trailer outgained'}), 'half')
        # after
        add('overtime', d.ot.map({0: 'no OT', 1: 'OT'}), 'after')
        add('2H turnovers', cnt(d.h2_to, [-1, 0, 1, 2, 99], ['0', '1', '2', '3+']), 'after')
        add('2H defensive or return TD', cnt(d.h2_nonoff_td, [-1, 0, 99], ['none', '1+']), 'after')
        add('2H missed kicks (FG + PAT)', cnt(d.h2_fg_miss + d.h2_xp_miss, [-1, 0, 1, 99], ['0', '1', '2+']), 'after')
        add('2H red-zone trips with no points', cnt(d.h2_rz_empty, [-1, 0, 1, 99], ['0', '1', '2+']), 'after')
        add('2H plays (quintile)', _q(d.h2_off), 'after')
        add('2H yards per play (quintile)', _q(d.h2_ypp), 'after')
        add('2H passing yards (quintile)', _q(d.h2_pass_yds_net), 'after')
        add('2H explosive plays (quintile)', _q(d.h2_explosive), 'after')
        add('2H 4th-down tries', cnt(d.h2_fourth_att, [-1, 0, 2, 99], ['0', '1-2', '3+']), 'after')
        add('garbage-time points (Q4, margin 17+)', cnt(d.pts_garbage, [-1, 0, 7, 14, 999], ['0', '1-7', '8-14', '15+']), 'after')
        add('points in the last 5 minutes', cnt(d.pts_last5, [-1, 0, 7, 14, 999], ['0', '1-7', '8-14', '15+']), 'after')
        add('2H onside kicks', cnt(d.h2_onside, [-1, 0, 99], ['0', '1+']), 'after')
        add('2H two-point tries', cnt(d.h2_twopa, [-1, 0, 99], ['0', '1+']), 'after')
    return F


def stat(sub, act, exp):
    a = sub[act].values.astype(float); e = sub[exp].values.astype(float)
    n = len(a)
    if n == 0:
        return n, np.nan, np.nan, np.nan
    var = (e * (1 - e)).sum()
    z = (a.sum() - e.sum()) / np.sqrt(var) if var > 0 else np.nan
    return n, a.mean(), e.mean(), z


def bucket_table(sport, d):
    rows = []
    for name, lab, tag in tagged_features(d, sport):
        for val in sorted(lab.dropna().unique(), key=str):
            m = (lab == val).values
            for frame_pre in ('', 'mk_'):
                if frame_pre == 'mk_':
                    if tag == 'after':
                        continue
                    mm = m & d['mk_died10'].notna().values
                else:
                    mm = m
                sub = d[mm]
                if len(sub) < (60 if frame_pre == '' else 40):
                    continue
                r = dict(sport=sport, frame='model' if frame_pre == '' else 'book', tag=tag, feature=name, bucket=str(val), n=len(sub),
                         share=len(sub) / max(1, int((lab.notna() & (d['mk_died10'].notna() if frame_pre else True)).sum())))
                for t in ('died10', 'blew10', 'died20', 'blew20'):
                    n, act, exp, z = stat(sub, frame_pre + t, frame_pre + 'e_' + t)
                    r[t] = act; r['e_' + t] = exp; r['z_' + t] = z
                    if frame_pre == '':
                        for part, sel in (('disc', sub.season <= SPLIT[sport]), ('hold', sub.season > SPLIT[sport])):
                            s2 = sub[sel.values]
                            _, a2, e2, z2 = stat(s2, t, 'e_' + t) if len(s2) >= 30 else (0, np.nan, np.nan, np.nan)
                            r[f'{part}_n'] = len(s2); r[f'{part}_{t}'] = a2; r[f'{part}_z_{t}'] = z2
                rows.append(r)
    return pd.DataFrame(rows)


def legs(d, Q, frame='model', lo=0.80, hi=0.90):
    """Q: season -> the block's 201 quantiles. Returns a per-game frame with over/under leg price and win."""
    out = []
    for s in sorted(d.season.unique()):
        te = (d.season == s).values
        if frame == 'book':
            te = te & d.line_med.notna().values
        if not te.any():
            continue
        sub = d[te]
        q = Q[s]
        if frame == 'model':
            mu, sd = sub.mu.values, sub.sd.values
        else:
            mu = market_mu(sub.line_med.values, sub.k.values, q)
            sd = sub.k.values * np.sqrt(mu)
        P = 1 - cdf(np.floor(STRIKES)[None, :] + 0.5, mu[:, None], sd[:, None], q)    # P(over t)
        y = sub.y.values[:, None]
        over_win = (y > STRIKES[None, :]).astype(float)
        po = np.where((P >= lo) & (P <= hi), P, np.nan)                     # overs priced 80-90c
        pu = np.where((1 - P >= lo) & (1 - P <= hi), 1 - P, np.nan)         # unders priced 80-90c
        wo = np.where(np.isnan(po), np.nan, over_win)
        wu = np.where(np.isnan(pu), np.nan, 1 - over_win)
        with np.errstate(invalid='ignore'):
            r = pd.DataFrame(dict(game_id=sub.game_id.values, season=sub.season.values,
                                  over_price=np.nanmean(po, 1), over_win=np.nanmean(wo, 1), over_n=np.sum(~np.isnan(po), 1),
                                  under_price=np.nanmean(pu, 1), under_win=np.nanmean(wu, 1), under_n=np.sum(~np.isnan(pu), 1)))
        out.append(r)
    return pd.concat(out, ignore_index=True)


def summarize(L, mask=None, label=''):
    if mask is not None:
        L = L[mask]
    res = {}
    for side in ('over', 'under'):
        x = L[L[f'{side}_n'] > 0]
        n = len(x)
        if n == 0:
            continue
        diff = x[f'{side}_win'] - x[f'{side}_price']
        res[side] = dict(games=n, legs=int(x[f'{side}_n'].sum()), price=x[f'{side}_price'].mean(), won=x[f'{side}_win'].mean(),
                         edge_c=100 * diff.mean(), se_c=100 * diff.std(ddof=1) / np.sqrt(n))
    both = pd.concat([L[L.over_n > 0][['over_price', 'over_win']].set_axis(['p', 'w'], axis=1), L[L.under_n > 0][['under_price', 'under_win']].set_axis(['p', 'w'], axis=1)])
    if len(both):
        dd = both.w - both.p
        res['both'] = dict(games=len(both), price=both.p.mean(), won=both.w.mean(), edge_c=100 * dd.mean(), se_c=100 * dd.std(ddof=1) / np.sqrt(len(both)))
    return res


def design(d, sport):
    global LogisticRegression, HistGradientBoostingClassifier, roc_auc_score, log_loss
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score, log_loss
    X = pd.DataFrame(index=d.index)
    X['total'] = d.total; X['fav_by'] = d.fav_by; X['h1_vs_exp'] = d.h1_vs_exp; X['favm'] = d.favm; X['margin'] = d.margin
    X['fav_trail_1_7'] = ((d.favm < 0) & (d.favm >= -7)).astype(float)
    X['kick_et'] = d.kick_et
    for c in ['h1_plays_vs_exp', 'h1_yds_vs_exp', 'h1_ypp', 'h1_pts_vs_yds', 'h1_pass_rate', 'h1_pass_yds_net', 'h1_rush_yds', 'h1_to', 'h1_to_opp_terr',
              'h1_nonoff_td', 'h1_fg_miss', 'h1_xp_miss', 'h1_rz_empty', 'h1_fourth_att', 'h1_fourth_fail_opp', 'h1_explosive', 'h1_big_pass', 'h1_sack', 'h1_pen_yds',
              'pts_last2_h1', 'h1_off_epa', 'h1_success_rate', 'h1_third_rate', 'h1_punt_attempt', 'h1_drive', 'trail_outgained', 'h1_twopa']:
        X[c] = d[c]
    if sport == 'nfl':
        for v in ['1 PM', '4 PM', 'night', 'morning (London)']:
            X[f'slot_{v}'] = (d.slot == v).astype(float)
        X['dome'] = (d.roof2 == 'dome/closed').astype(float)
        X['wind'] = np.where(d.roof2 == 'outdoors', d.wind, 0)
        X['temp'] = np.where(d.roof2 == 'outdoors', d.temp, 65)
        X['precip'] = d.precip.fillna(0)
        X['turf'] = d.turf
        X['div'] = d.div_game2
        X['short_rest'] = d.short_rest; X['playoff'] = d.playoff; X['week'] = d.week
    else:
        for v in ['noon window', 'afternoon (3:30)', 'evening (7-8)', 'late night (10:30+)']:
            X[f'slot_{v}'] = (d.slot == v).astype(float)
        X['power_power'] = (d.matchup == 'power vs power').astype(float)
        X['g5_g5'] = (d.matchup == 'G5 vs G5').astype(float)
        X['conf'] = d.conf_game; X['fcs'] = d.fcs_opp; X['neutral'] = d.neutral; X['elo_gap'] = d.elo_gap
        X['weeknight'] = d.weekday2.isin(['Tue/Wed', 'Thursday', 'Friday']).astype(float)
        X['playoff'] = d.playoff; X['week'] = d.week
        X['spread28'] = (d.fav_by >= 28).astype(float)
    X = X.astype(float)
    X = X.fillna(X.median())
    return X


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def cv(d, X, target, base_col, seasons):
    y = d[target].values.astype(int)
    p0 = d[base_col].values.astype(float)
    off = logit(p0)
    pl = np.zeros(len(d)); pg = np.zeros(len(d))
    Z = (X - X.mean()) / X.std().replace(0, 1)
    for s in seasons:
        te = (d.season == s).values
        tr = ~te
        # logistic on the residual log-odds: fit with the desk's log-odds as a fixed offset via sample augmentation
        lr = LogisticRegression(C=0.05, max_iter=2000)
        A = np.column_stack([Z.values, off])
        lr.fit(A[tr], y[tr])
        pl[te] = lr.predict_proba(A[te])[:, 1]
        gb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0, min_samples_leaf=80)
        gb.fit(np.column_stack([X.values, p0])[tr], y[tr])
        pg[te] = gb.predict_proba(np.column_stack([X.values, p0])[te])[:, 1]
    out = dict(n=len(y), rate=y.mean(), base_rate=p0.mean(),
               ll_base=log_loss(y, np.clip(p0, 1e-4, 1 - 1e-4)), ll_logit=log_loss(y, pl), ll_gb=log_loss(y, pg),
               auc_base=roc_auc_score(y, p0) if len(np.unique(p0)) > 1 else 0.5, auc_logit=roc_auc_score(y, pl), auc_gb=roc_auc_score(y, pg))
    # how well the best fifth by the logistic model does
    q = pd.qcut(pl, 5, labels=False, duplicates='drop')
    out['top5_rate'] = y[q == q.max()].mean(); out['top5_base'] = p0[q == q.max()].mean()
    out['bot5_rate'] = y[q == 0].mean(); out['bot5_base'] = p0[q == 0].mean()
    return out, pl, lr, Z.columns


def gate_run(sport, d, width=False, weather=False):
    live = engine.MODEL[sport]
    knee = live.get('knee', 14) if len(live['coef']) > 6 else None
    y_all = d.y.values.astype(float)
    bad_all = d.bad.values.astype(float) if 'bad' in d else np.zeros(len(d))
    logs, briers, maes, legc, mids = [], [], [], [], []
    for s in sorted(d.season.unique()):
        te = (d.season == s).values; tr = ~te
        Xtr = fit_cfb.features(d[tr], knee); Xte = fit_cfb.features(d[te], knee)
        ytr = y_all[tr]; yte = y_all[te]
        coef = fit_cfb.fit(Xtr, ytr)
        mutr = fit_cfb.mu_of(coef, Xtr); mute = fit_cfb.mu_of(coef, Xte)
        if weather:
            w = float(np.sum((ytr - mutr) * bad_all[tr]) / max(1.0, bad_all[tr].sum()))
            mutr = np.maximum(8.0, mutr + w * bad_all[tr]); mute = np.maximum(8.0, mute + w * bad_all[te])
        k = float(np.sqrt(np.mean((ytr - mutr) ** 2 / mutr)))
        ztr = (ytr - mutr) / (k * np.sqrt(mutr))
        ftr = np.minimum(d.fav_by.values[tr], 35.0); fte = np.minimum(d.fav_by.values[te], 35.0)
        if width:
            A = np.column_stack([np.ones(tr.sum()), ftr])
            c, *_ = np.linalg.lstsq(A, ztr ** 2, rcond=None)
            str_ = np.sqrt(np.maximum(0.3, A @ c)); ste = np.sqrt(np.maximum(0.3, c[0] + c[1] * fte))
        else:
            str_ = np.ones(tr.sum()); ste = np.ones(te.sum())
        q = np.quantile(ztr / str_, np.linspace(0, 1, 201))
        sd = k * np.sqrt(mute) * ste
        p_eq = cdf(yte + 0.5, mute, sd, q) - cdf(yte - 0.5, mute, sd, q)
        logs.append(np.log(np.clip(p_eq, 1e-6, 1)))
        med = mute + sd * q[100]
        maes.append(np.abs(yte - med))
        mr = np.round(med * 2) / 2
        for off in OFFS[sport]:
            t = np.floor(mr + off) + 0.5        # the half-point strike at that offset from the median
            p = 1 - cdf(np.floor(t) + 0.5, mute, sd, q)
            briers.append((p - (yte > t)) ** 2)
        P = 1 - cdf(np.floor(STRIKES)[None, :] + 0.5, mute[:, None], sd[:, None], q)
        ow = (yte[:, None] > STRIKES[None, :]).astype(float)
        for prc, win in ((P, ow), (1 - P, 1 - ow)):
            m = (prc >= 0.80) & (prc <= 0.90)
            with np.errstate(invalid='ignore'):
                g = np.nanmean(np.where(m, win - prc, np.nan), 1)
            legc.append(g[~np.isnan(g)])
        lo_, hi_ = np.ceil(mr - 3), np.floor(mr + 3)
        pm = cdf(hi_ + 0.5, mute, sd, q) - cdf(lo_ - 0.5, mute, sd, q)
        mids.append(np.column_stack([pm, ((yte >= lo_) & (yte <= hi_)).astype(float), d.fav_by.values[te]]))
    mids = np.vstack(mids)
    return dict(log_per_game=np.concatenate(logs), log=np.concatenate(logs).mean(), brier=np.concatenate(briers).mean(), mae=np.concatenate(maes).mean(),
                legs_c=100 * np.concatenate(legc).mean(), mid=mids)


def bad_weather(d):
    return (((d.precip == 1) | (d.wind_b == '16+ mph')) & (d.roof2 == 'outdoors')).astype(float)


# ---------------------------------------------------------------- the report


_CACHE = {}


def build(sport):
    if sport not in _CACHE:
        b, Q = load(sport)
        b = add_market(b, sport, Q)
        b = add_pregame(b)
        d = nfl(b) if sport == 'nfl' else cfb(b)
        if sport == 'nfl':
            d['bad'] = bad_weather(d)
        _CACHE[sport] = (d, Q)
    return _CACHE[sport]


def _legline(lab, r):
    b, o, u = r.get('both'), r.get('over'), r.get('under')
    if not b:
        return f'  {lab:<40} (none)'
    return (f"  {lab:<40} games {b['games'] // 2 if o and u else b['games']:>5} | won {100 * b['won']:.1f}% at {100 * b['price']:.1f}c ({b['edge_c']:+.1f}c, se {b['se_c']:.1f})"
            f" | overs {o['edge_c']:+.1f}c, unders {u['edge_c']:+.1f}c")


def calibration():
    print('1. How often the 80-90c side lost, against the price')
    for sport in ('nfl', 'cfb'):
        d, Q = build(sport)
        print(f'\n{sport.upper()}: {len(d)} games {d.season.min()}-{d.season.max()}')
        for pre, lab in (('', 'desk model (each season out of sample)'), ('mk_', "book's 2H line, model shape (2023 on)"), ('pg_', 'pregame: final vs closing total')):
            m = d[pre + 'died10'].notna()
            print(f"  {lab:<42} n {m.sum():>6} | died (90c over lost) {100 * d.loc[m, pre + 'died10'].mean():.1f}% vs said {100 * d.loc[m, pre + 'e_died10'].mean():.1f}%"
                  f" | blew (90c under lost) {100 * d.loc[m, pre + 'blew10'].mean():.1f}% vs {100 * d.loc[m, pre + 'e_blew10'].mean():.1f}%"
                  f" | 80c: {100 * d.loc[m, pre + 'died20'].mean():.1f}/{100 * d.loc[m, pre + 'e_died20'].mean():.1f}, {100 * d.loc[m, pre + 'blew20'].mean():.1f}/{100 * d.loc[m, pre + 'e_blew20'].mean():.1f}")
        for frame in ('model', 'book'):
            L = legs(d, Q, frame).merge(d.drop(columns=['season']), on='game_id', how='left')
            print(_legline(f'80-90c legs, {frame} frame', summarize(L)))


def buckets(top=25):
    print('2. Every pregame and halftime bucket against the model (z: actual minus expected tail count, in SE)')
    for sport in ('nfl', 'cfb'):
        d, _ = build(sport)
        r = bucket_table(sport, d)
        m = r[(r.frame == 'model') & r.tag.isin(['pre', 'half'])].copy()
        zc = ['z_died10', 'z_blew10', 'z_died20', 'z_blew20']
        m['zmax'] = m[zc].abs().max(1)
        nz = m[zc].abs().values.flatten()
        nz = nz[~np.isnan(nz)]
        print(f'\n{sport.upper()}: {len(m)} buckets, {len(nz)} z-scores; |z| >= 3: {int((nz >= 3).sum())} (chance alone ~{0.0027 * len(nz):.1f}), |z| >= 4: {int((nz >= 4).sum())}')
        cols = ['tag', 'feature', 'bucket', 'n', 'died10', 'e_died10', 'z_died10', 'blew10', 'e_blew10', 'z_blew10', 'disc_z_died10', 'hold_z_died10', 'disc_z_blew10', 'hold_z_blew10']
        with pd.option_context('display.width', 250, 'display.max_colwidth', 44):
            print(m.sort_values('zmax', ascending=False)[cols].head(top).round(3).to_string(index=False))


def named():
    print('3. The things you would look at: 80-90c legs by each (model frame, games with play by play)')
    for sport in ('nfl', 'cfb'):
        d, Q = build(sport)
        L = legs(d, Q, 'model').merge(d.drop(columns=['season']), on='game_id', how='left')
        L = L[L.has_pbp == 1]
        print(f'\n{sport.upper()} ({L.game_id.nunique()} games)')
        items = [('1H passing yards', pd.qcut(L.h1_pass_yds_net, 5, labels=['lowest fifth', '2nd', 'middle', '4th', 'highest fifth'])),
                 ('1H missed kicks (FG + PAT)', pd.cut(L.h1_kick_miss, [-1, 0, 1, 99], labels=['none', '1', '2+'])),
                 ('1H turnovers', pd.cut(L.h1_to, [-1, 0, 1, 2, 99], labels=['0', '1', '2', '3+'])),
                 ('1H defensive or return TD', pd.cut(L.h1_nonoff_td, [-1, 0, 99], labels=['none', '1+'])),
                 ('1H red-zone trips with no points', pd.cut(L.h1_rz_empty, [-1, 0, 1, 99], labels=['0', '1', '2+'])),
                 ('1H pace (plays vs normal)', pd.qcut(L.h1_plays_vs_exp, 5, labels=['slowest fifth', '2nd', 'middle', '4th', 'fastest fifth'])),
                 ('1H points against its yards', pd.qcut(L.h1_pts_vs_yds, 5, labels=['fewest per yard', '2nd', 'middle', '4th', 'most per yard'])),
                 ('kickoff slot (ET)', L.slot)]
        if sport == 'nfl':
            items += [('weather (outdoors)', pd.Series(np.where(L.precip == 1, 'rain or snow', np.where(L.wind_b == '16+ mph', 'wind 16+, dry', np.where(L.roof2 == 'outdoors', 'outdoors, fair', 'dome or closed'))), index=L.index))]
        else:
            items += [('pregame spread', pd.cut(L.fav_by, [-1, 7, 14, 21, 28, 100], labels=['0-7', '7.5-14', '14.5-21', '21.5-28', '28+']))]
        for name, lab in items:
            print(f'  -- {name}')
            cats = list(lab.cat.categories) if hasattr(lab, 'cat') else sorted(lab.dropna().unique())
            for v in cats:
                msk = (lab == v).values
                if msk.sum() >= 60:
                    print('  ' + _legline(str(v), summarize(L, msk)))


def after():
    print('4. How the tail games actually happened (second half, games with play by play)')
    cols = {'y_vs_median': '2H points vs the desk median', 'ot': 'went to overtime', 'h2_off': '2H plays', 'h2_drive': '2H drives',
            'h2_yds': '2H yards', 'h2_ypp': '2H yards per play', 'h2_pass_yds_net': '2H passing yards (net)', 'h2_rush_yds': '2H rushing yards',
            'h2_explosive': '2H plays of 20+ yards', 'h2_big_pass': '2H passes of 30+', 'h2_to': '2H turnovers', 'nonoff': '2H defensive or return TD',
            'kmiss': '2H missed kick (FG or PAT)', 'rze': '2H red-zone trip, no points', 'h2_punt_attempt': '2H punts', 'h2_sack': '2H sacks',
            'garb': 'any garbage-time points (Q4, margin 17+)', 'pts_last5': 'points in the last 5 minutes', 'late14': '14+ points in the last 5 minutes',
            'late0': 'no points in the last 5 minutes', 'onside': '2H onside kick', 'twop': '2H two-point try', 'any_event': 'OT, a return TD or 14+ late (any)'}
    for sport in ('nfl', 'cfb'):
        d, _ = build(sport)
        d = d[d.has_pbp == 1].copy()
        d['grp'] = np.where(d.died10 == 1, 'died', np.where(d.blew10 == 1, 'blew up', 'other 80%'))
        d['y_vs_median'] = d.y - d['median']
        d['nonoff'] = (d.h2_nonoff_td > 0).astype(float)
        d['kmiss'] = ((d.h2_fg_miss + d.h2_xp_miss) > 0).astype(float)
        d['rze'] = (d.h2_rz_empty >= 1).astype(float)
        d['garb'] = (d.pts_garbage > 0).astype(float)
        d['late14'] = (d.pts_last5 >= 14).astype(float)
        d['late0'] = (d.pts_last5 == 0).astype(float)
        d['onside'] = (d.h2_onside > 0).astype(float)
        d['twop'] = (d.h2_twopa > 0).astype(float)
        d['any_event'] = ((d.ot == 1) | (d.nonoff == 1) | (d.late14 == 1)).astype(float)
        t = d.groupby('grp')[list(cols)].mean().T
        t.index = [cols[c] for c in t.index]
        print(f"\n{sport.upper()}: died {int((d.grp == 'died').sum())}, blew up {int((d.grp == 'blew up').sum())}, other {int((d.grp == 'other 80%').sum())}")
        print(t[['died', 'other 80%', 'blew up']].round(2).to_string())


def predict():
    from sklearn.linear_model import LogisticRegression  # noqa: F401  (imported in cv via the module scope)
    print('5. Can anything known at the break call the tails? Season-grouped cross-validation against the desk model')
    for sport in ('nfl', 'cfb'):
        d, _ = build(sport)
        d = d[d.has_pbp == 1].reset_index(drop=True)
        X = design(d, sport)
        print(f'\n{sport.upper()}: {len(d)} games, {X.shape[1]} pregame and first-half features')
        for target in ('died10', 'blew10', 'died20', 'blew20'):
            r, _, _, _ = cv(d, X, target, 'e_' + target, sorted(d.season.unique()))
            print(f"  {target}: actual {r['rate']:.3f} (desk {r['base_rate']:.3f}) | log loss desk {r['ll_base']:.4f}, desk + features {r['ll_logit']:.4f}, boosted {r['ll_gb']:.4f}"
                  f" | AUC {r['auc_base']:.3f} / {r['auc_logit']:.3f} / {r['auc_gb']:.3f}")


def gate():
    print('6. The two candidate changes, leave one season out (log score per game; z from the paired per-game difference)')
    for sport in ('nfl', 'cfb'):
        d, _ = build(sport)
        order = np.concatenate([np.where((d.season == s).values)[0] for s in sorted(d.season.unique())])
        dd = d.iloc[order].reset_index(drop=True)
        r0 = gate_run(sport, d)
        variants = [('width by spread', dict(width=True))] + ([('bad-weather mean term', dict(weather=True))] if sport == 'nfl' else [])
        for name, kw in variants:
            r1 = gate_run(sport, d, **kw)
            diff = r1['log_per_game'] - r0['log_per_game']
            z = diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))
            per = pd.Series(diff).groupby(dd.season.values).mean()
            print(f"  {sport.upper()} {name:<22} log score {diff.mean():+.5f} per game (z {z:+.2f}, better in {int((per > 0).sum())} of {len(per)} seasons)"
                  f" | Brier at rungs {r1['brier'] - r0['brier']:+.5f} | MAE {r0['mae']:.3f} -> {r1['mae']:.3f}")
            if 'weather' in name:
                m = dd.bad.values == 1
                per_bad = pd.Series(diff[m]).groupby(dd.season.values[m]).mean()
                print(f"      bad-weather games ({m.sum()}): {diff[m].mean():+.4f} per game (z {diff[m].mean() / (diff[m].std(ddof=1) / np.sqrt(m.sum())):+.2f},"
                      f" better in {int((per_bad > 0).sum())} of {len(per_bad)} seasons)")


def middle():
    print("7. The middle zone: how often the second half landed within 3, 5 and 7 points of the desk's median")
    for sport in ('nfl', 'cfb'):
        d, Q = build(sport)
        res = []
        for s in sorted(d.season.unique()):
            te = (d.season == s).values
            sub = d[te]
            q = Q[s]
            med = np.round(sub['median'].values * 2) / 2
            for w in (3, 5, 7):
                lo, hi = np.ceil(med - w), np.floor(med + w)
                p = cdf(hi + 0.5, sub.mu.values, sub.sd.values, q) - cdf(lo - 0.5, sub.mu.values, sub.sd.values, q)
                res.append(pd.DataFrame(dict(w=w, p=p, a=((sub.y >= lo) & (sub.y <= hi)).astype(float).values, fav_by=sub.fav_by.values,
                                             bad=sub.bad.values if 'bad' in sub else 0)))
        r = pd.concat(res)
        groups = [('all', r.fav_by.notna())]
        if sport == 'cfb':
            groups += [('spread 28+', r.fav_by >= 28), ('spread 21.5-28', (r.fav_by > 21) & (r.fav_by < 28)), ('spread 0-7', r.fav_by <= 7)]
        else:
            groups += [('bad weather', r.bad == 1), ('spread 11+', r.fav_by >= 11)]
        for g, m in groups:
            line = []
            for w in (3, 5, 7):
                x = r[m & (r.w == w)]
                se = np.sqrt((x.p * (1 - x.p)).sum()) / len(x)
                line.append(f'within {w}: {100 * x.a.mean():.1f}% vs {100 * x.p.mean():.1f}% ({(x.a.mean() - x.p.mean()) / se:+.1f} SE)')
            print(f"  {sport.upper()} {g:<16} n {int((m & (r.w == 3)).sum()):>5}: " + '; '.join(line))


def pregame(top=10):
    print('8. Pregame frame (final total against the closing total): the strongest pregame buckets')
    for sport in ('nfl', 'cfb'):
        d, _ = build(sport)
        rows = []
        for name, lab, tag in tagged_features(d, sport):
            if tag != 'pre':
                continue
            for val in sorted(lab.dropna().unique(), key=str):
                sub = d[(lab == val).values]
                if len(sub) < 60:
                    continue
                r = dict(feature=name, bucket=str(val), n=len(sub), final_vs_total=(sub.final - sub.total).mean())
                for t in ('died10', 'blew10'):
                    _, a, e, z = stat(sub, 'pg_' + t, 'pg_e_' + t)
                    r[t], r['e_' + t], r['z_' + t] = a, e, z
                    for part, sel in (('disc', sub.season <= SPLIT[sport]), ('hold', sub.season > SPLIT[sport])):
                        s2 = sub[sel.values]
                        r[f'{part}_z_{t}'] = stat(s2, 'pg_' + t, 'pg_e_' + t)[3] if len(s2) >= 30 else np.nan
                rows.append(r)
        x = pd.DataFrame(rows)
        x['zmax'] = x[['z_died10', 'z_blew10']].abs().max(1)
        print(f'\n{sport.upper()}')
        with pd.option_context('display.width', 250):
            print(x.sort_values('zmax', ascending=False).head(top).drop(columns=['zmax']).round(3).to_string(index=False))


def live():
    print("9. The live desk: Kalshi's own ladder at the first look at each break (log/halftime_log.csv), graded")
    h = pd.read_csv(os.path.join(ROOT, 'log', 'halftime_log.csv'))
    res = pd.read_csv(os.path.join(ROOT, 'log', 'results.csv')).drop_duplicates(['sport', 'game', 'date'])[['sport', 'game', 'date', 'final_total']]
    hh = h[h.phase == 'half'].sort_values('time_utc').drop_duplicates(['sport', 'game', 'date'], keep='first')
    m = hh.merge(res, on=['sport', 'game', 'date'], how='inner')
    rows = []
    for _, x in m.iterrows():
        for tok in str(x.quotes).split():
            mt = re.match(r'([\d.]+):(\d+)/(\d+)', tok)
            if not mt:
                continue
            k, yes, no = float(mt.group(1)), int(mt.group(2)), int(mt.group(3))
            if 80 <= yes <= 90:
                rows.append(dict(sport=x.sport, game=x.game, date=x.date, side='over', price=yes, win=float(x.final_total > k)))
            if 80 <= no <= 90:
                rows.append(dict(sport=x.sport, game=x.game, date=x.date, side='under', price=no, win=float(x.final_total < k)))
    L = pd.DataFrame(rows).groupby(['sport', 'game', 'date', 'side']).agg(price=('price', 'mean'), win=('win', 'mean')).reset_index()
    print(f"  {m.date.min()} to {m.date.max()}, {len(m)} graded halves")
    for sp, g in list(L.groupby('sport')) + [('football', L[L.sport.isin(['nfl', 'cfb'])])]:
        print(f"  {sp:<9} {g.game.nunique():>3} games, {len(g):>3} game-sides: ask {g.price.mean():.1f}c, won {100 * g.win.mean():.1f}%"
              f" ({100 * g.win.mean() - g.price.mean():+.1f}c, se {100 * g.win.std() / np.sqrt(len(g)):.1f})")


SECTIONS = dict(calibration=calibration, buckets=buckets, named=named, after=after, predict=predict, gate=gate,
                middle=middle, pregame=pregame, live=live)

if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    for k, fn in SECTIONS.items():
        if which in ('all', k):
            fn()
            print()
