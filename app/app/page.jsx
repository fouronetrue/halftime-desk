'use client';
import { useEffect, useMemo, useState, useCallback } from 'react';
import Link from 'next/link';
import { supabase } from '@/lib/supabase';
import { etDate, etDay, etTime, ago, phaseLabel, isHalfish, spreadText } from '@/lib/desk';

const SPORTS = [['all', 'All'], ['nfl', 'NFL'], ['cfb', 'College']];

function Heartbeat({ beat }) {
  const age = beat?.last_beat ? (Date.now() - new Date(beat.last_beat).getTime()) / 1000 : null;
  const state = age === null ? 'off' : age < 420 ? 'ok' : 'late';
  const text = age === null ? 'Watcher has not checked in' : state === 'ok' ? `Watching, last look ${ago(beat.last_beat)}` : `Watcher quiet since ${ago(beat.last_beat)}`;
  return <p className={`beat ${state}`}><span className="dot" aria-hidden="true" />{text}</p>;
}

function GameCard({ g, sug, big }) {
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
      {big && sug && (
        <div className="halfline">
          <span>Fair <b>{Number(sug.fair_line)}</b></span>
          <span>Kalshi <b>{sug.market_line ?? 'n/a'}</b></span>
          <span className={sug.n_plays ? 'plays on' : 'plays'}>{sug.n_plays ? `${sug.n_plays} clear the edge` : 'Nothing clears'}</span>
          <span className="when">since {etTime(g.half_at)}</span>
        </div>
      )}
    </Link>
  );
}

export default function Today() {
  const [games, setGames] = useState([]);
  const [sugs, setSugs] = useState({});
  const [beat, setBeat] = useState(null);
  const [sport, setSport] = useState('all');
  const [showFinal, setShowFinal] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    const today = etDate();
    const yesterday = etDate(new Date(Date.now() - 86400000));
    const [{ data: gs, error }, { data: hb }] = await Promise.all([
      supabase.from('games').select('*').gte('date_et', yesterday).order('start_utc'),
      supabase.from('desk_state').select('last_beat,note').eq('id', 'worker').maybeSingle(),
    ]);
    if (error) { setErr(error.message); return; }
    setErr('');
    const list = (gs || []).filter((g) => g.date_et === today || (g.phase && g.phase !== 'post' && g.phase !== 'pre'));
    setGames(list);
    setBeat(hb);
    const halfIds = list.filter((g) => isHalfish(g) || (g.phase === 'post' && g.half_at)).map((g) => g.id);
    if (halfIds.length) {
      const { data: ss } = await supabase.from('suggestions').select('game_id,taken_at,fair_line,market_line,n_plays')
        .in('game_id', halfIds).order('taken_at', { ascending: false }).limit(halfIds.length * 30);
      const latest = {};
      for (const s of ss || []) if (!latest[s.game_id]) latest[s.game_id] = s;
      setSugs(latest);
    }
  }, []);

  useEffect(() => {
    load();
    const fast = games.some(isHalfish);
    const id = setInterval(() => { if (document.visibilityState === 'visible') load(); }, fast ? 15000 : 60000);
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
      {half.length > 0 && <section><h2>At the half</h2>{half.map((g) => <GameCard key={g.id} g={g} sug={sugs[g.id]} big />)}</section>}
      {live.length > 0 && <section><h2>Live</h2>{live.map((g) => <GameCard key={g.id} g={g} />)}</section>}
      {pre.length > 0 && <section><h2>Coming up</h2>{pre.map((g) => <GameCard key={g.id} g={g} />)}</section>}
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
