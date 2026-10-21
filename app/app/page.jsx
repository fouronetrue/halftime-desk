'use client';
import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import Link from 'next/link';
import { supabase } from '@/lib/supabase';
import { etDate, etDay, etTime, ago, phaseLabel, isHalfish, scoreMoved, spreadText } from '@/lib/desk';
import { middleOpen, freeOpen } from '@/components/HeldTotals';

const SPORTS = [['all', 'All'], ['nfl', 'NFL'], ['cfb', 'College'], ['nba', 'NBA']];

function Heartbeat({ beat }) {
  const age = beat?.last_beat ? (Date.now() - new Date(beat.last_beat).getTime()) / 1000 : null;
  const state = age === null ? 'off' : age < 420 ? 'ok' : 'late';
  const text = age === null ? 'Watcher has not checked in' : state === 'ok' ? `Watching, last look ${ago(beat.last_beat)}` : `Watcher quiet since ${ago(beat.last_beat)}`;
  // five quick taps show the viewport numbers (Shell's debug readout), for sizing problems in the home-screen app
  const taps = useRef([]);
  const tap = () => {
    const now = Date.now();
    taps.current = taps.current.filter((t) => now - t < 3000).concat(now);
    if (taps.current.length >= 5) { taps.current = []; window.dispatchEvent(new Event('hd-debug')); }
  };
  return <p className={`beat ${state}`} onClick={tap}><span className="dot" aria-hidden="true" />{text}</p>;
}

const MAX_MID_LOSS = 15;   // a middle on Today never risks more than this on a miss

// The same picks the PLAY push names (engine.chosen): best cleared single, best cleared middle.
// Both lists are stored best first (singles by edge, mids by EV), so the first entry is the one that clears if any
// does. Today only fetches that first entry (top_single, top_mid) to keep each refresh small.
function bets(sug) {
  const single = sug?.top_single?.ok ? sug.top_single : null;
  const mid = sug?.top_mid?.ok ? sug.top_mid : null;
  let pairs = 0;
  if (mid) {
    const loss = Number(mid.c) - 1;
    pairs = loss > 0 ? Math.min(mid.pairs, Math.floor(MAX_MID_LOSS / loss + 1e-9)) : mid.pairs;
  }
  return { single, mid, pairs };
}

// How long a cleared line has held: the watcher stamps each cleared line with when it first cleared this half.
// A line that just appeared is usually one thin ask about to be taken; one that has held a few minutes is a
// price the market is willing to keep offering. Every one of these is graded at the final (Record, "came and went").
function clearFor(since) {
  if (!since) return null;
  const s = Math.max(0, Math.round((Date.now() - new Date(since).getTime()) / 1000));
  return s < 20 ? 'just now' : s < 90 ? `clear ${s}s` : `clear ${Math.round(s / 60)} min`;
}

function BetLines({ sug }) {
  const { single, mid, pairs } = bets(sug);
  if (!single && !mid) return <p className="betline none"><b>BET:</b> None. Nothing clears the 3c edge.</p>;
  return (
    <div className="bets">
      {single && (
        <p className="betline"><b>BET:</b> Single - {single.kind === 'over' ? 'Over' : 'Under'} {Number(single.line)} ({single.contracts} shares, {single.price_c}c){single.since ? <span className={`clearfor ${clearFor(single.since) === 'just now' ? 'new' : ''}`}>{clearFor(single.since)}</span> : null}</p>
      )}
      {mid && pairs > 0 && (
        <p className="betline"><b>BET:</b> Middle - O{Number(mid.a.line)} ({pairs} shares, {mid.a.price_c}c), U{Number(mid.b.line)} ({pairs} shares, {mid.b.price_c}c){mid.since ? <span className={`clearfor ${clearFor(mid.since) === 'just now' ? 'new' : ''}`}>{clearFor(mid.since)}</span> : null}</p>
      )}
      {single && mid && pairs > 0 && <p className="betnote">One or the other, not both.</p>}
    </div>
  );
}

function GameCard({ g, sug, big, mkt }) {
  const live = g.phase === 'live' || isHalfish(g) || g.phase === 'post';
  const away = live ? (g.phase === 'post' ? g.final_away ?? g.away_score : g.away_score) : null;
  const home = live ? (g.phase === 'post' ? g.final_home ?? g.home_score : g.home_score) : null;
  const awayWins = away !== null && home !== null && away > home;
  const homeWins = away !== null && home !== null && home > away;
  const sp = spreadText(g);
  return (
    <Link href={`/desk/?g=${g.id}`} className={`card ${big ? 'big' : ''} ph-${g.phase}`}>
      <div className="rows">
        <div className={`team ${awayWins ? 'lead' : ''}`}><span className="abbr">{g.away_abbr}</span><span className="name">{g.away_name}</span><span className="pts">{away ?? ''}</span></div>
        <div className={`team ${homeWins ? 'lead' : ''}`}><span className="abbr">{g.home_abbr}</span><span className="name">{g.home_name}</span><span className="pts">{home ?? ''}</span></div>
      </div>
      <div className="side">
        <span className={`chip ${g.phase}`}>{phaseLabel(g)}</span>
        <span className="lines">{g.pre_total ? `o/u ${Number(g.pre_total)}` : 'no total yet'}{sp ? <><br />{sp}</> : null}</span>
      </div>
      {g.phase !== 'post' && !isHalfish(g) && g.phase !== 'live' && mkt?.line && (
        <div className="mktline">
          <span>Kalshi <b>{mkt.line}</b></span>
          {(mkt.legs || []).map((l) => <span key={l.side}>{l.side === 'over' ? 'O' : 'U'}{l.k} <b>{l.c ?? '-'}c</b></span>)}
          <span className="when">{ago(mkt.at)}</span>
        </div>
      )}
      {big && sug && (scoreMoved(g, sug) ? (
        <div className="halfline">
          <span>Fair <b>{Number(sug.fair_line)}</b></span>
          <span>Kalshi <b>{sug.market_line ?? 'n/a'}</b></span>
          <span className="plays">priced at {sug.half_away}-{sug.half_home}</span>
          <p className="betline none"><b>Score moved.</b> The half pricing is stale. No bet.</p>
        </div>
      ) : (
        <div className="halfline">
          <span>Fair <b>{Number(sug.fair_line)}</b></span>
          <span>Kalshi <b>{sug.market_line ?? 'n/a'}</b></span>
          <span className={sug.n_plays ? 'plays on' : 'plays'}>{sug.n_plays ? `${sug.n_plays} clear the edge` : 'Nothing clears'}</span>
          <span className="when">since {etTime(g.half_at)}</span>
          {isHalfish(g) && <BetLines sug={sug} />}
        </div>
      ))}
    </Link>
  );
}

export default function Today() {
  const [games, setGames] = useState([]);
  const [sugs, setSugs] = useState({});
  const [beat, setBeat] = useState(null);
  const [mkts, setMkts] = useState({});
  const [held, setHeld] = useState({});
  const [sport, setSport] = useState('all');
  const [showFinal, setShowFinal] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    const today = etDate();
    const yesterday = etDate(new Date(Date.now() - 86400000));
    const [{ data: gs, error }, { data: hb }, { data: pm }, { data: hd }] = await Promise.all([
      supabase.from('games').select('*').gte('date_et', yesterday).order('start_utc'),
      supabase.from('desk_state').select('last_beat,note').eq('id', 'worker').maybeSingle(),
      supabase.from('desk_state').select('state').eq('id', 'pregame').maybeSingle(),
      supabase.from('desk_state').select('state').eq('id', 'held').maybeSingle(),
    ]);
    if (error) { setErr(error.message); return; }
    setErr('');
    const list = (gs || []).filter((g) => g.date_et === today || (g.phase && g.phase !== 'post' && g.phase !== 'pre'));
    setGames(list);
    setBeat(hb);
    setMkts(pm?.state || {});
    setHeld(hd?.state || {});
    const halfIds = list.filter((g) => isHalfish(g) || (g.phase === 'post' && g.half_at)).map((g) => g.id);
    if (halfIds.length) {
      const { data: ss } = await supabase.from('suggestions').select('game_id,taken_at,fair_line,market_line,n_plays,half_away,half_home,top_single:singles->0,top_mid:mids->0')
        .in('game_id', halfIds).order('taken_at', { ascending: false }).limit(halfIds.length * 30);
      const latest = {};
      for (const s of ss || []) if (!latest[s.game_id]) latest[s.game_id] = s;
      setSugs(latest);
    }
  }, []);

  useEffect(() => {
    load();
    const fast = games.some(isHalfish);
    const id = setInterval(() => { if (document.visibilityState === 'visible') load(); }, fast ? 5000 : 60000);
    const onVis = () => document.visibilityState === 'visible' && load();
    document.addEventListener('visibilitychange', onVis);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', onVis); };
  }, [load, games.some(isHalfish)]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(() => games.filter((g) => sport === 'all' || g.sport === sport), [games, sport]);
  const half = shown.filter(isHalfish);
  const live = shown.filter((g) => g.phase === 'live');
  const pre = shown.filter((g) => g.phase === 'pre' || !g.phase);
  const done = shown.filter((g) => g.phase === 'post');

  return (
    <main>
      <header className="top">
        <h1>{etDay()}</h1>
        <Heartbeat beat={beat} />
        <div className="seg" role="tablist" aria-label="Sport">
          {SPORTS.map(([k, l]) => <button key={k} role="tab" aria-selected={sport === k} className={sport === k ? 'on' : ''} onClick={() => setSport(k)}>{l}</button>)}
        </div>
      </header>
      {err && <p className="err">Could not load games: {err}</p>}
      {middleOpen(held).map((ev) => (
        <p key={ev.game} className="openline"><b>{freeOpen(ev) ? 'Free middle' : 'Middle open'}</b> on your {ev.game} total. <Link href="/bets/" className="link">See Bets</Link></p>
      ))}
      {half.length > 0 && <section><h2>At the half</h2>{half.map((g) => <GameCard key={g.id} g={g} sug={sugs[g.id]} big />)}</section>}
      {live.length > 0 && <section><h2>Live</h2>{live.map((g) => <GameCard key={g.id} g={g} />)}</section>}
      {pre.length > 0 && <section><h2>Coming up</h2>{pre.map((g) => <GameCard key={g.id} g={g} mkt={mkts[g.id]} />)}</section>}
      {done.length > 0 && (
        <section>
          <button className="fold" onClick={() => setShowFinal(!showFinal)} aria-expanded={showFinal}>{showFinal ? 'Hide' : 'Show'} {done.length} final{done.length === 1 ? '' : 's'}</button>
          {showFinal && done.map((g) => <GameCard key={g.id} g={g} sug={sugs[g.id]} />)}
        </section>
      )}
      {!err && shown.length === 0 && <p className="empty">No games on today&apos;s slate yet. The watcher adds them as ESPN posts the scoreboard.</p>}
    </main>
  );
}
