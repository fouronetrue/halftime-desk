'use client';
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import MiddleCalc from '@/components/MiddleCalc';
import MiddleCompare from '@/components/MiddleCompare';
import FairMiddle from '@/components/FairMiddle';
import { ago, etTime, isHalfish, middle, money, phaseLabel, reverse, reverseAt, scoreMoved, seriesOf, spreadText } from '@/lib/desk';

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

// The reverse middle: NO on the lower line plus YES on the higher one. One leg pays on any final outside the
// hole between them, both lose inside it. The gauge runs the other way from the middle's: the pair has to cost
// less than 1 minus P(hole) minus the 3c margin, which only happens when the ladder prices the hole too dear.
function ReverseBuilder({ r, pick, sport, clear, pairs, setPairs }) {
  const pct = Math.min(100, Math.max(0, ((r.c - 0.5) / (r.breakeven + 0.1 - 0.5)) * 100));
  const mark = Math.min(100, Math.max(0, ((r.breakeven - 0.5) / (r.breakeven + 0.1 - 0.5)) * 100));
  const at = reverseAt(r, pairs === '' ? r.pairs : pairs);
  return (
    <section className="middle reverse" aria-live="polite">
      <div className="mhead">
        <h3>Reverse: Under {pick.under} + Over {pick.over}</h3>
        <button className="link" onClick={clear}>Clear</button>
      </div>
      <p className="legs">No {pick.under} at {r.a}c, Yes {pick.over} at {r.b}c. Any final outside {r.lo} to {r.hi} pays one leg; {r.lo} to {r.hi} ({r.numbers} number{r.numbers === 1 ? '' : 's'}) loses both.</p>
      <div className={`gauge ${r.under ? 'good' : 'bad'}`} role="img" aria-label={`Pair cost ${(100 * r.c).toFixed(1)} cents against a limit of ${(100 * r.breakeven).toFixed(1)}`}>
        <div className="fill" style={{ width: `${pct}%` }} />
        <div className="mark" style={{ left: `${mark}%` }} />
      </div>
      <p className="gaugetext">Pair cost <b>{(100 * r.c).toFixed(1)}c</b> with fees. Has to be under {(100 * r.breakeven).toFixed(1)}c (100 minus the {Math.round(100 * r.pHole)}% hole minus 3c). {r.under ? 'Under it.' : 'Over it: pass.'}</p>
      <dl className="mstats">
        <div><dt>Pairs (engine size)</dt><dd>{r.ok ? r.pairs : 'Pass'}</dd></div>
        <div><dt>Hole</dt><dd>{Math.round(100 * r.pHole)}%</dd></div>
        <div><dt>Edge a pair</dt><dd className={r.ev >= 0.03 ? 'pos' : 'neg'}>{(100 * r.ev).toFixed(1)}c</dd></div>
        <div><dt>Pairs</dt><dd><input className="num" inputMode="numeric" value={pairs === '' ? r.pairs : pairs} onChange={(e) => setPairs(e.target.value)} aria-label="Pairs" /></dd></div>
        <div><dt>Total in</dt><dd>{money(at.cost)}</dd></div>
        <div><dt>One leg pays</dt><dd className="pos">{money(at.win)}</dd></div>
        <div><dt>Final in the hole</dt><dd className="neg">{money(at.lose)}</dd></div>
      </dl>
      <p className="hint">Buy No {pick.under} for {money(at.dollarsA)} and Yes {pick.over} for {money(at.dollarsB)}. The engine sizes this as one bet, quarter Kelly on the pair with the hole as the risk, under the single caps. It is two cheap wings: the edge is the two singles' edges added, the pair just swings less.</p>
    </section>
  );
}

// What the push said about everything you own on this game's total, from the suggestions row (held): one
// position, a line a leg with one verdict, the finals together in dollars, and the no-lose hedge when one exists.
// Old rows (before Oct 22) carried a list of legs with per-leg options; those still render as plain lines.
const signedMoney = (v) => `${v >= 0 ? '+' : '-'}$${Math.abs(Number(v)).toFixed(0)}`;
const spanText = (g) => (g.lo === null || g.lo === undefined) ? `${Math.round(g.hi)} or less` : (g.hi === null || g.hi === undefined) ? `${Math.round(g.lo)} or more` : g.lo === g.hi ? `${Math.round(g.lo)}` : `${Math.round(g.lo)} to ${Math.round(g.hi)}`;
function Finals({ regions }) {
  return (
    <ul className="finals">
      {(regions || []).map((g, i) => (
        <li key={i} className={g.pnl < -0.5 ? 'neg' : g.pnl > 0.5 ? 'pos' : ''}><span>{spanText(g)}</span><b>{signedMoney(g.pnl)}</b>{g.p !== null && g.p !== undefined ? <em>{Math.round(100 * g.p)}%</em> : null}</li>
      ))}
    </ul>
  );
}
function HeldAtHalf({ held }) {
  const pos = Array.isArray(held) ? (held.length ? { legs: held } : null) : held;
  if (!pos?.legs?.length) return null;
  const hd = pos.hedge;
  return (
    <section className="held athalf">
      {pos.legs.map((h) => {
        const side = h.side === 'yes' ? 'Over' : 'Under';
        const s = h.sell || h.options?.sell;
        const fair = h.fair_c ?? h.options?.fair_c;
        const sell = s && s.verdict === 'SELL';
        return (
          <p key={h.ticker || `${h.side}${h.strike}`} className="hold">You hold <b>{side} {Number(h.strike)}</b>, {h.shares} sh at {Number(h.paid_c).toFixed(0)}c.
            {fair !== undefined && fair !== null ? <> Worth {Math.round(fair)}c.</> : null}
            {sell ? <> Bid {s.bid_c}c: <b className="pos">SELL</b> for {signedMoney(s.pnl)}.</> : <> <b>Hold.</b></>}</p>
        );
      })}
      {pos.regions && pos.legs.length > 1 && (
        <div className="together">
          <p className="target">{pos.window ? <>Together it's a <b>{Math.round(pos.window[0])} to {Math.round(pos.window[1])}</b> middle.</> : 'Together, by final:'}{pos.no_lose ? ' No final loses.' : ''}</p>
          <Finals regions={pos.regions} />
        </div>
      )}
      {hd && (
        <div className="together">
          <p className="target free"><b>NO-LOSE HEDGE:</b> buy {hd.kind === 'over' ? 'Over' : 'Under'} {Number(hd.strike)} at {hd.ask_c}c, {hd.shares} sh ({money(hd.cost)}).{Math.abs(hd.edge_c) >= 0.05 ? ` The leg is ${Math.abs(hd.edge_c).toFixed(1)}c ${hd.edge_c < 0 ? 'under' : 'over'} fair.` : ''}</p>
          <Finals regions={hd.regions} />
        </div>
      )}
    </section>
  );
}

function MiddleBuilder({ m, pick, sport, clear, sug, budget, setBudget, pairs, setPairs }) {
  if (pick.over === null && pick.under === null) return <p className="hint">Tap an Over price, then an Under price on a higher line, to build a middle. An Under on a lower line builds a reverse middle instead.</p>;
  if (pick.over === null || pick.under === null) return <p className="hint">{pick.over === null ? `Under ${pick.under} picked. Now tap an Over price: a lower line for a middle, a higher one for a reverse.` : `Over ${pick.over} picked. Now tap an Under price: a higher line for a middle, a lower one for a reverse.`} <button className="link" onClick={clear}>Clear</button></p>;
  if (!m) return <p className="hint">Over {pick.over ?? '?'}, under {pick.under ?? '?'}: pick two different lines. <button className="link" onClick={clear}>Clear</button></p>;
  if (m.missing) return <p className="hint">One of those legs has no ask right now. <button className="link" onClick={clear}>Clear</button></p>;
  if (m.kind === 'rev') return <ReverseBuilder r={m} pick={pick} sport={sport} clear={clear} pairs={pairs} setPairs={setPairs} />;
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
      <MiddleCalc sport={sport} overLine={pick.over} underLine={pick.under} askA={m.a} askB={m.b} budget={budget} setBudget={setBudget} maxCost={Number(sug?.max_cost || 0)} pHit={m.pHit} />
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
  const [budget, setBudget] = useState(10);
  const [pairs, setPairs] = useState('');
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
    const t = setInterval(() => { if (document.visibilityState === 'visible') load(); }, fast ? 5000 : 60000);
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
    if (under.strike < over.strike) {   // the under on the lower line: a reverse middle
      const knownR = (sug?.revs || []).find((x) => Number(x.a.line) === pick.under && Number(x.b.line) === pick.over);
      return reverse(under, over, game?.sport, sug, knownR ? knownR.p_hole : undefined);
    }
    const known = (sug?.mids || []).find((x) => Number(x.a.line) === pick.over && Number(x.b.line) === pick.under);
    return middle(over, under, game?.sport, sug, known ? known.p_mid : undefined);
  }, [rows, pick, sug, game]);

  if (!id) return <main><h1>Desk</h1><p className="empty">Pick a game on <Link href="/">Today</Link> to open its desk.</p></main>;
  if (err) return <main><p className="err">Could not load this game: {err}</p></main>;
  if (!game) return <main />;

  const onPick = (side, strike) => setPick((p) => ({ ...p, [side]: p[side] === strike ? null : strike }));
  const series = seriesOf(game.kalshi_total_event || sug?.event_ticker);
  const sp = spreadText(game);
  // Once the live score leaves the halftime score the pricing is stale: nothing glows, nothing counts as cleared.
  const moved = scoreMoved(game, sug);
  const cleared = moved ? [] : (sug?.singles || []).filter((l) => l.ok);
  const revOn = moved ? null : (sug?.revs || []).find((x) => x.ok) || null;

  return (
    <main>
      <header className="deskhead">
        <p className="back"><Link href="/">Today</Link><Link href={`/calc/?s=${game.sport}${pick.over !== null && pick.under !== null && m && !m.missing && m.kind !== 'rev' ? `&o=${pick.over}&u=${pick.under}&a=${m.a}&b=${m.b}` : ''}`}>Middle calc</Link></p>
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
          {moved ? (
            <p className="stamp stale"><b>Score moved since the half.</b> Priced at {sug.half_away}-{sug.half_home} ({etTime(sug.taken_at)}); the ladder below is that moment, not now. No bet.</p>
          ) : (
            <p className="stamp">Priced {ago(sug.taken_at)} ({etTime(sug.taken_at)}). {cleared.length ? `${cleared.length} line${cleared.length === 1 ? '' : 's'} clear the 3c edge.` : 'Nothing clears the 3c edge.'}{revOn ? <> Reverse middle clears: <button className="link" onClick={() => setPick({ over: Number(revOn.b.line), under: Number(revOn.a.line) })}>U{Number(revOn.a.line)} + O{Number(revOn.b.line)}, +{(100 * revOn.ev).toFixed(1)}c a pair</button>.</> : null}</p>
          )}
          {!moved && <HeldAtHalf held={sug.held} />}
          <FairMiddle rows={rows} fair={Number(sug.fair_line)} sport={game.sport} maxCost={Number(sug?.max_cost || 0)} mids={sug?.mids} takenAt={sug.taken_at} onPick={(o, u) => setPick({ over: o, under: u })} />
          <Ladder rows={rows} legs={moved ? {} : legs} pick={pick} onPick={onPick} />
          <MiddleCompare rows={rows} sport={game.sport} budget={Number(budget) || 0} maxCost={Number(sug?.max_cost || 0)} mids={sug?.mids} pick={pick} onPick={(o, u) => setPick({ over: o, under: u })} />
          <MiddleBuilder m={m} pick={pick} sport={game.sport} sug={sug} budget={budget} setBudget={setBudget} pairs={pairs} setPairs={setPairs} clear={() => { setPick({ over: null, under: null }); setPairs(''); }} />
          {series && <a className="cta" href={`https://kalshi.com/markets/${series}`} target="_blank" rel="noopener noreferrer">Open on Kalshi</a>}
        </>
      )}
    </main>
  );
}

export default function Desk() {
  return <Suspense fallback={<main />}><DeskView /></Suspense>;
}
