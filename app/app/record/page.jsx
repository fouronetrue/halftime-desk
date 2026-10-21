'use client';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { supabase } from '@/lib/supabase';
import { etTime, gradeSheet, money } from '@/lib/desk';

// Record: every halftime the desk graded, newest first, and how the P&L got where it is. Plays are graded at
// the sizes the push suggested (the first single is the play, the rest are backups; a middle is graded on its
// own). "You" is what your Kalshi positions on that game's total market actually settled for, after fees.
const GATE = 250;
const SPORTS = [['all', 'All'], ['nfl', 'NFL'], ['cfb', 'College'], ['nba', 'NBA']];

const num = (v) => (v === null || v === undefined || v === '' ? null : Number(v));
const signed = (v) => `${v >= 0 ? '+' : '-'}$${Math.abs(v).toFixed(Math.abs(v) >= 100 ? 0 : 2)}`;

function grade(r) {
  const T = num(r.final_total);
  const g = gradeSheet(r.sheet || {}, T);
  const fair = num(r.fair), mkt = num(r.mkt);
  const closer = fair === null || mkt === null || T === null ? null : Math.abs(T - fair) < Math.abs(T - mkt) ? 'model' : Math.abs(T - fair) > Math.abs(T - mkt) ? 'market' : 'tie';
  return { singles: g?.options || [], mid: g?.mid || null, rev: g?.rev || null, rest: g?.rest || null, play: g?.play || null, lead: g?.lead, T, fair, mkt, closer, played: Boolean(g?.play) };
}

function Spark({ points }) {
  if (points.length < 2) return null;
  const w = 320, h = 56, pad = 4;
  const lo = Math.min(0, ...points), hi = Math.max(0, ...points);
  const y = (v) => h - pad - ((v - lo) / (hi - lo || 1)) * (h - 2 * pad);
  const x = (i) => pad + (i / (points.length - 1)) * (w - 2 * pad);
  const d = points.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const last = points[points.length - 1];
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Cumulative plays P&L across ${points.length} plays, ending at ${signed(last)}`}>
      <line x1={pad} x2={w - pad} y1={y(0)} y2={y(0)} className="zero" />
      <path d={d} className={last >= 0 ? 'pos' : 'neg'} />
    </svg>
  );
}

export default function Record() {
  const [rows, setRows] = useState(null);
  const [you, setYou] = useState({});
  const [sport, setSport] = useState('all');
  const [only, setOnly] = useState('plays');
  const [open, setOpen] = useState(null);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.from('results').select('*').order('settled_at', { ascending: false }).limit(400);
      const list = data || [];
      setRows(list);
      const ids = list.map((r) => r.game_id);
      if (!ids.length) return;
      // your settled Kalshi positions on each game's total market, after fees
      const [{ data: gs }, { data: ps }] = await Promise.all([
        supabase.from('games').select('id,kalshi_total_event').in('id', ids),
        supabase.from('positions').select('event_ticker,realized_pnl,fees_paid').eq('settlement_status', 'settled'),
      ]);
      const byEvent = {};
      for (const p of ps || []) byEvent[p.event_ticker] = (byEvent[p.event_ticker] || 0) + Number(p.realized_pnl || 0) - Number(p.fees_paid || 0);
      const out = {};
      for (const g of gs || []) if (g.kalshi_total_event && byEvent[g.kalshi_total_event] !== undefined) out[g.id] = Math.round(byEvent[g.kalshi_total_event] * 100) / 100;
      setYou(out);
    })();
  }, []);

  const graded = useMemo(() => (rows || []).map((r) => ({ r, g: grade(r) })), [rows]);
  const inSport = graded.filter(({ r }) => sport === 'all' || r.sport === sport);
  const shown = only === 'plays' ? inSport.filter(({ g }) => g.played) : inSport;

  // the scorecard, over the sport filter
  const plays = inSport.filter(({ g }) => g.play);
  const wins = plays.filter(({ g }) => g.play.win).length;
  const cost = plays.reduce((s, { g }) => s + Number(g.play.cost || 0), 0);
  const pnl = plays.reduce((s, { g }) => s + Number(g.play.pnl || 0), 0);
  const mids = inSport.filter(({ g }) => g.mid);
  const midHits = mids.filter(({ g }) => g.mid.hit).length;
  const midPnl = mids.reduce((s, { g }) => s + (g.mid.pnl || 0), 0);
  const both = inSport.filter(({ g }) => g.closer);
  const closer = both.filter(({ g }) => g.closer === 'model').length;
  // The bets that came and went: every line that cleared the edge in any priced row of the half but was not the
  // push, graded at its best moment. Split by how long it held, since a one-look flicker is usually a thin ask.
  const extra = inSport.flatMap(({ r }) => (r.flickers || []).filter((f) => !f.pushed).map((f) => ({ ...f, game: r.game })));
  const held = extra.filter((f) => (f.secs || 0) >= 60), quick = extra.filter((f) => (f.secs || 0) < 60);
  const rec = (xs) => ({ n: xs.length, w: xs.filter((f) => f.win).length, pnl: xs.reduce((s, f) => s + Number(f.pnl || 0), 0), cost: xs.reduce((s, f) => s + Number(f.cost || 0), 0) });
  const fx = { all: rec(extra), held: rec(held), quick: rec(quick) };
  const withFlickers = inSport.filter(({ r }) => Array.isArray(r.flickers)).length;
  const rests = inSport.filter(({ g }) => g.rest && g.rest.pnl !== null);
  const restPnl = rests.reduce((s, { g }) => s + g.rest.pnl, 0);
  const restHits = rests.filter(({ g }) => g.rest.hit).length;
  const youTotal = inSport.reduce((s, { r }) => s + (you[r.game_id] || 0), 0);
  const youCount = inSport.filter(({ r }) => you[r.game_id] !== undefined).length;
  const curve = [...plays].reverse().reduce((acc, { g }) => { acc.push((acc[acc.length - 1] || 0) + Number(g.play.pnl || 0)); return acc; }, []);

  if (rows === null) return <main />;
  let lastDate = null;
  return (
    <main>
      <header className="top">
        <h1>Record</h1>
        <div className="seg" role="tablist" aria-label="Sport">
          {SPORTS.map(([k, l]) => <button key={k} role="tab" aria-selected={sport === k} className={sport === k ? 'on' : ''} onClick={() => setSport(k)}>{l}</button>)}
        </div>
      </header>
      <div className="progress" role="img" aria-label={`${inSport.length} of ${GATE} halftimes graded`}>
        <div className="fill" style={{ width: `${Math.min(100, (100 * inSport.length) / GATE)}%` }} />
      </div>
      <p className="gaugetext"><b>{inSport.length}</b> of {GATE} halftimes graded toward the Nov 27 verdict.</p>

      {inSport.length > 0 && (
        <>
          <div className="board rec">
            <div><span>Plays</span><b>{wins}-{plays.length - wins}</b><small className={pnl >= 0 ? 'pos' : 'neg'}>{signed(pnl)} on {money(cost)}{cost ? `, ${((100 * pnl) / cost).toFixed(1)}%` : ''}</small></div>
            <div><span>Middles called</span><b>{midHits} of {mids.length}</b><small className={midPnl >= 0 ? 'pos' : 'neg'}>{mids.length ? signed(midPnl) : 'none yet'}</small></div>
            <div><span>Model closer</span><b>{both.length ? `${closer} of ${both.length}` : 'n/a'}</b><small>than Kalshi, at the final</small></div>
          </div>
          {curve.length > 1 && <p className="sparkcap">Plays P&amp;L, one point per play, oldest to newest</p>}
          <Spark points={curve} />
          <p className="sub">
            Resting middles, what-if: {rests.length} games, {restHits} finals inside the window, {signed(restPnl)} if every one had filled both sides.
            {youCount ? ` Your Kalshi totals on these games, after fees: ${signed(youTotal)} across ${youCount}.` : ''}
          </p>
          {withFlickers > 0 && (
            <div className="flick">
              <h3>Came and went</h3>
              <p className="sub">Lines that cleared the edge at some moment of the half but were not the push ({withFlickers} games tracked). Graded at the best price each showed, at the size the engine gave it then.</p>
              <dl className="mstats">
                <div><dt>All of them</dt><dd className={fx.all.pnl >= 0 ? 'pos' : 'neg'}>{fx.all.n ? `${fx.all.w}-${fx.all.n - fx.all.w}, ${signed(fx.all.pnl)}` : 'none'}</dd></div>
                <div><dt>Held a minute or more</dt><dd className={fx.held.pnl >= 0 ? 'pos' : 'neg'}>{fx.held.n ? `${fx.held.w}-${fx.held.n - fx.held.w}, ${signed(fx.held.pnl)}` : 'none'}</dd></div>
                <div><dt>Under a minute</dt><dd className={fx.quick.pnl >= 0 ? 'pos' : 'neg'}>{fx.quick.n ? `${fx.quick.w}-${fx.quick.n - fx.quick.w}, ${signed(fx.quick.pnl)}` : 'none'}</dd></div>
              </dl>
              {fx.all.cost > 0 && <p className="sub">{signed(fx.all.pnl)} on {money(fx.all.cost)} if every one had been taken, {((100 * fx.all.pnl) / fx.all.cost).toFixed(1)}%. The pushes above are the record; this is the question, not the answer, until the count is in the dozens.</p>}
            </div>
          )}
        </>
      )}

      <div className="seg" role="tablist" aria-label="Which games">
        {[['plays', 'Plays only'], ['all', 'Every half']].map(([k, l]) => <button key={k} role="tab" aria-selected={only === k} className={only === k ? 'on' : ''} onClick={() => setOnly(k)}>{l}</button>)}
      </div>
      {rows.length === 0 && <p className="empty">Nothing graded yet. The first rows land when a priced game goes final.</p>}
      {rows.length > 0 && shown.length === 0 && <p className="empty">No plays graded{sport === 'all' ? '' : ` in ${sport === 'nfl' ? 'the NFL' : 'college'}`} yet.</p>}
      <ul className="reclist">
        {shown.map(({ r, g }) => {
          const date = r.date_et;
          const head = date !== lastDate;
          lastDate = date;
          const day = head ? inSport.filter((x) => x.r.date_et === date) : [];
          const dayPnl = day.reduce((s, x) => s + (x.g.play ? x.g.play.pnl : 0), 0);
          const dayPlays = day.filter((x) => x.g.played).length;
          const play = g.lead === 'single' ? g.singles[0] : null;
          const yours = you[r.game_id];
          return (
            <li key={r.game_id} className="recwrap">
              {head && (
                <h2 className="recday">
                  <span>{new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })}</span>
                  <span className="dayline">{day.length} graded, {dayPlays} play{dayPlays === 1 ? '' : 's'}{dayPlays ? <>, <b className={dayPnl >= 0 ? 'pos' : 'neg'}>{signed(dayPnl)}</b></> : null}</span>
                </h2>
              )}
              <div className={`rec ${g.played ? 'played' : 'quiet'}`}>
                <button className="rechead" onClick={() => setOpen(open === r.game_id ? null : r.game_id)} aria-expanded={open === r.game_id}>
                  <span className="game">{r.game}<small>{r.sport === 'nfl' ? 'NFL' : r.sport === 'nba' ? 'NBA' : 'CFB'}</small></span>
                  <span className="recscore">Half {r.half}. Final {r.final}, {g.T} points.</span>
                  {play ? (
                    <span className={`call ${play.win ? 'win' : 'loss'}`}>
                      <b>{play.win ? 'WIN' : 'LOSS'}</b> {play.kind === 'over' ? 'Over' : 'Under'} {Number(play.line)} at {play.price_c}c, {play.contracts} shares
                      <em className={play.pnl >= 0 ? 'pos' : 'neg'}>{signed(play.pnl)}</em>
                    </span>
                  ) : g.mid || g.rev ? null : (
                    <span className="call none">No play. Fair {g.fair}, Kalshi {g.mkt ?? 'n/a'}.</span>
                  )}
                  {g.mid && (
                    <span className={`call ${g.mid.hit ? 'win' : 'loss'}`}>
                      <b>{g.mid.hit ? 'HIT' : 'MISS'}</b> Middle O{Number(g.mid.a_line)} at {g.mid.a_price}c + U{Number(g.mid.b_line)} at {g.mid.b_price}c, {g.mid.pairs} pairs{g.lead === 'mid' ? ' (the play)' : ''}
                      <em className={(g.mid.pnl || 0) >= 0 ? 'pos' : 'neg'}>{signed(g.mid.pnl || 0)}</em>
                    </span>
                  )}
                  {g.rev && (
                    <span className={`call ${g.rev.hole ? 'loss' : 'win'}`}>
                      <b>{g.rev.hole ? 'HOLE' : 'WIN'}</b> Reverse U{Number(g.rev.a_line)} at {g.rev.a_price}c + O{Number(g.rev.b_line)} at {g.rev.b_price}c, {g.rev.pairs} pairs{g.lead === 'rev' ? ' (the play)' : ''}
                      <em className={(g.rev.pnl || 0) >= 0 ? 'pos' : 'neg'}>{signed(g.rev.pnl || 0)}</em>
                    </span>
                  )}
                </button>
                {open === r.game_id && (
                  <div className="recmore">
                    <p>Pregame o/u {Number(r.total)}{r.home_spread !== null && r.home_spread !== undefined ? `, home ${Number(r.home_spread) > 0 ? '+' : ''}${Number(r.home_spread)}` : ''}. Model fair {g.fair}, Kalshi {g.mkt ?? 'n/a'}, final {g.T}: {g.closer === 'model' ? 'model closer' : g.closer === 'market' ? 'Kalshi closer' : g.closer === 'tie' ? 'tie' : 'no market line'}.</p>
                    {g.singles.filter((s) => !s.play).map((s, i) => (
                      <p key={i} className="alt">{g.lead === 'mid' ? 'Single' : 'Backup'} {s.kind === 'over' ? 'over' : 'under'} {Number(s.line)} at {s.price_c}c would have {s.win ? 'won' : 'lost'} {signed(s.pnl)}.</p>
                    ))}
                    {r.sheet?.rebuilt && <p className="alt">Graded from the prices the push was priced at (sent before sheets were kept).</p>}
                    {g.rest && <p className="alt">Resting middle O{Number(g.rest.a_line)} at {g.rest.a_price}c + U{Number(g.rest.b_line)} at {g.rest.b_price}c, {g.rest.pairs} pairs: {g.rest.hit ? 'final inside the window' : 'missed'}, {signed(g.rest.pnl || 0)} if both sides had filled.</p>}
                    {yours !== undefined && <p className="alt">You on this total, after fees: <b className={yours >= 0 ? 'pos' : 'neg'}>{signed(yours)}</b>.</p>}
                    {(r.flickers || []).filter((f) => !f.pushed).length > 0 && (
                      <>
                        <p className="alt"><b className="chalk">Came and went</b> (cleared at some moment, not the push):</p>
                        {(r.flickers || []).filter((f) => !f.pushed).map((f, i) => (
                          <p key={`f${i}`} className={`alt flickline ${f.win ? 'win' : 'loss'}`}>
                            <b>{f.win ? (f.kind === 'single' ? 'would have won' : 'would have hit') : (f.kind === 'single' ? 'would have lost' : 'would have missed')}</b>{' '}
                            {f.kind === 'single' ? `${f.side === 'over' ? 'Over' : 'Under'} ${f.line} at ${f.price_c}c, ${f.contracts} shares` : f.kind === 'mid' ? `Middle O${f.a_line} at ${f.a_price}c + U${f.b_line} at ${f.b_price}c, ${f.pairs} pairs` : `Reverse U${f.a_line} at ${f.a_price}c + O${f.b_line} at ${f.b_price}c, ${f.pairs} pairs`}: {signed(f.pnl)}. Clear {f.secs >= 60 ? `${Math.round(f.secs / 60)} min` : f.n > 1 ? `${f.secs}s` : 'one look'}{f.n > 1 ? ` (${f.n} looks)` : ''}, best edge {f.best_edge_c}c, first {etTime(f.first)}.
                          </p>
                        ))}
                      </>
                    )}
                    <Link className="link" href={`/desk/?g=${r.game_id}`}>Open the desk as it was</Link>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </main>
  );
}
