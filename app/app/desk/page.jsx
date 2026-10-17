'use client';
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import MiddleCalc from '@/components/MiddleCalc';
import { ago, etTime, isHalfish, middle, money, phaseLabel, seriesOf, spreadText } from '@/lib/desk';

function lastGame() {
  try { return localStorage.getItem('hd-last-game'); } catch { return null; }
}

function Ladder({ rows, legs, pick, onPick }) {
  return (
    <table className="ladder">
      <thead>
        <tr><th scope="col">Total</th><th scope="col" colSpan="2">Over (Yes)</th><th scope="col" colSpan="2">Under (No)</th></tr>
        <tr className="sub"><th></th><th>ask</th><th>fair</th><th>ask</th><th>fair</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const o = legs[`over ${Number(r.strike)}`], u = legs[`under ${Number(r.strike)}`];
          const fo = Math.round(100 * r.p_over), fu = Math.round(100 * Math.max(0, 1 - r.p_over - r.p_push));
          const pickO = pick.over === Number(r.strike), pickU = pick.under === Number(r.strike);
          return (
            <tr key={r.strike}>
              <th scope="row">{Number(r.strike)}</th>
              <td className={`px ${o?.ok ? 'glow' : ''} ${pickO ? 'picked' : ''}`}>
                <button onClick={() => onPick('over', Number(r.strike))} aria-pressed={pickO} aria-label={`Over ${Number(r.strike)} at ${r.yes_ask ?? 'no'} cents`}>
                  <b>{r.yes_ask ?? '-'}</b>{r.yes_bid ? <small>bid {r.yes_bid}</small> : null}
                </button>
              </td>
              <td className="fair">{fo}<small>take {r.over_take} rest {r.over_rest}</small>{o ? <em className={o.edge >= 0 ? 'pos' : 'neg'}>{o.edge >= 0 ? '+' : ''}{(100 * o.edge).toFixed(1)}</em> : null}</td>
              <td className={`px ${u?.ok ? 'glow' : ''} ${pickU ? 'picked' : ''}`}>
                <button onClick={() => onPick('under', Number(r.strike))} aria-pressed={pickU} aria-label={`Under ${Number(r.strike)} at ${r.no_ask ?? 'no'} cents`}>
                  <b>{r.no_ask ?? '-'}</b>{r.no_bid ? <small>bid {r.no_bid}</small> : null}
                </button>
              </td>
              <td className="fair">{fu}<small>take {r.under_take} rest {r.under_rest}</small>{u ? <em className={u.edge >= 0 ? 'pos' : 'neg'}>{u.edge >= 0 ? '+' : ''}{(100 * u.edge).toFixed(1)}</em> : null}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function MiddleBuilder({ m, pick, sport, clear, sug }) {
  if (pick.over === null && pick.under === null) return <p className="hint">Tap an Over price, then an Under price on a higher line, to build a middle.</p>;
  if (pick.over === null || pick.under === null) return <p className="hint">{pick.over === null ? `Under ${pick.under} picked. Now tap an Over price on a lower line.` : `Over ${pick.over} picked. Now tap an Under price on a higher line.`} <button className="link" onClick={clear}>Clear</button></p>;
  if (!m) return <p className="hint">Over {pick.over ?? '?'}, under {pick.under ?? '?'}. The under line has to sit above the over line. <button className="link" onClick={clear}>Clear</button></p>;
  if (m.missing) return <p className="hint">One of those legs has no ask right now. <button className="link" onClick={clear}>Clear</button></p>;
  const pct = Math.min(100, Math.max(0, ((m.c - 0.85) / (m.breakeven + 0.1 - 0.85)) * 100));
  const mark = Math.min(100, Math.max(0, ((m.breakeven - 0.85) / (m.breakeven + 0.1 - 0.85)) * 100));
  return (
    <section className="middle" aria-live="polite">
      <div className="mhead">
        <h3>Over {pick.over} + Under {pick.under}</h3>
        <button className="link" onClick={clear}>Clear</button>
      </div>
      <p className="legs">Yes {pick.over} at {m.a}c, No {pick.under} at {m.b}c. Final {m.lo} to {m.hi} wins both ({m.numbers} number{m.numbers === 1 ? '' : 's'}).</p>
      <div className={`gauge ${m.under ? 'good' : 'bad'}`} role="img" aria-label={`Pair cost ${(100 * m.c).toFixed(1)} cents against a breakeven of ${(100 * m.breakeven).toFixed(1)}`}>
        <div className="fill" style={{ width: `${pct}%` }} />
        <div className="mark" style={{ left: `${mark}%` }} />
      </div>
      <p className="gaugetext">Pair cost <b>{(100 * m.c).toFixed(1)}c</b> with fees. Breakeven {(100 * m.breakeven).toFixed(1)}c for {sport === 'nfl' ? 'NFL' : 'college'}. {m.under ? 'Under it.' : 'Over it: pass.'}</p>
      <dl className="mstats">
        <div><dt>Shares each side</dt><dd>{m.ok ? m.pairs : 'Pass'}</dd></div>
        <div><dt>Total in</dt><dd>{m.ok ? money(m.cost) : '$0'}</dd></div>
        <div><dt>Hits</dt><dd>{Math.round(100 * m.pHit)}%</dd></div>
        <div><dt>Both pay</dt><dd className="pos">{m.ok ? money(m.win) : '-'}</dd></div>
        <div><dt>Any other final</dt><dd className={m.lose < 0 ? 'neg' : 'pos'}>{m.ok ? money(m.lose) : '-'}</dd></div>
        <div><dt>Edge a pair</dt><dd className={m.ev >= 0.03 ? 'pos' : 'neg'}>{(100 * m.ev).toFixed(1)}c</dd></div>
      </dl>
      <h4 className="mc-head">Size it at the prices Kalshi shows</h4>
      <MiddleCalc sport={sport} overLine={pick.over} underLine={pick.under} askA={m.a} askB={m.b} budget0={10} maxCost={Number(sug?.max_cost || 0)} pHit={m.pHit} />
    </section>
  );
}

function DeskView() {
  const params = useSearchParams();
  const id = params.get('g') || lastGame();
  const [game, setGame] = useState(null);
  const [sug, setSug] = useState(null);
  const [rows, setRows] = useState([]);
  const [pick, setPick] = useState({ over: null, under: null });
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    if (!id) return;
    const { data: g, error } = await supabase.from('games').select('*').eq('id', id).maybeSingle();
    if (error) { setErr(error.message); return; }
    setGame(g);
    const { data: s } = await supabase.from('suggestions').select('*').eq('game_id', id).order('taken_at', { ascending: false }).limit(1);
    const latest = s?.[0] || null;
    setSug(latest);
    if (latest) {
      const { data: q } = await supabase.from('quote_snapshots').select('*').eq('game_id', id).eq('taken_at', latest.taken_at).order('strike');
      setRows(q || []);
    }
  }, [id]);

  useEffect(() => {
    if (id) { try { localStorage.setItem('hd-last-game', id); } catch { /* private mode */ } }
    load();
    const fast = game && isHalfish(game);
    const t = setInterval(() => { if (document.visibilityState === 'visible') load(); }, fast ? 15000 : 60000);
    return () => clearInterval(t);
  }, [id, load, game && isHalfish(game)]); // eslint-disable-line react-hooks/exhaustive-deps

  const legs = useMemo(() => {
    const out = {};
    for (const l of sug?.singles || []) out[`${l.kind} ${Number(l.line)}`] = l;
    return out;
  }, [sug]);

  const m = useMemo(() => {
    const over = rows.find((r) => Number(r.strike) === pick.over);
    const under = rows.find((r) => Number(r.strike) === pick.under);
    if (!over || !under) return pick.over !== null && pick.under !== null ? null : undefined;
    const known = (sug?.mids || []).find((x) => Number(x.a.line) === pick.over && Number(x.b.line) === pick.under);
    return middle(over, under, game?.sport, sug, known ? known.p_mid : undefined);
  }, [rows, pick, sug, game]);

  if (!id) return <main><h1>Desk</h1><p className="empty">Pick a game on <Link href="/">Today</Link> to open its desk.</p></main>;
  if (err) return <main><p className="err">Could not load this game: {err}</p></main>;
  if (!game) return <main />;

  const onPick = (side, strike) => setPick((p) => ({ ...p, [side]: p[side] === strike ? null : strike }));
  const series = seriesOf(game.kalshi_total_event || sug?.event_ticker);
  const sp = spreadText(game);
  const cleared = (sug?.singles || []).filter((l) => l.ok);

  return (
    <main>
      <header className="deskhead">
        <p className="back"><Link href="/">Today</Link><Link href={`/calc/?s=${game.sport}${pick.over !== null && pick.under !== null && m && !m.missing ? `&o=${pick.over}&u=${pick.under}&a=${m.a}&b=${m.b}` : ''}`}>Middle calc</Link></p>
        <h1 className="score">
          <span>{game.away_abbr} {game.away_score ?? ''}</span>
          <span>{game.home_abbr} {game.home_score ?? ''}</span>
        </h1>
        <p className="meta"><span className={`chip ${game.phase}`}>{phaseLabel(game)}</span> Pregame o/u {game.pre_total ? Number(game.pre_total) : 'n/a'}{sp ? `, ${sp}` : ''}{game.half_away !== null && game.half_away !== undefined ? `. Half: ${game.half_away}-${game.half_home}.` : ''}</p>
      </header>

      {!sug ? (
        <p className="empty">Prices show up here when this game reaches the half. Until then the watcher is only tracking the pregame line.</p>
      ) : (
        <>
          <div className="board">
            <div><span>Fair total</span><b>{Number(sug.fair_line)}</b></div>
            <div><span>Kalshi</span><b>{sug.market_line ?? 'n/a'}</b></div>
            <div><span>2H points</span><b>{Number(sug.mu).toFixed(1)}</b></div>
          </div>
          <p className="stamp">Priced {ago(sug.taken_at)} ({etTime(sug.taken_at)}). {cleared.length ? `${cleared.length} line${cleared.length === 1 ? '' : 's'} clear the 3c edge.` : 'Nothing clears the 3c edge.'}</p>
          <Ladder rows={rows} legs={legs} pick={pick} onPick={onPick} />
          <MiddleBuilder m={m} pick={pick} sport={game.sport} sug={sug} clear={() => setPick({ over: null, under: null })} />
          {series && <a className="cta" href={`https://kalshi.com/markets/${series}`} target="_blank" rel="noopener noreferrer">Open on Kalshi</a>}
        </>
      )}
    </main>
  );
}

export default function Desk() {
  return <Suspense fallback={<main />}><DeskView /></Suspense>;
}
