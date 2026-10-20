'use client';
import Link from 'next/link';
import { ago, money } from '@/lib/desk';

// Your totals: every full-game total you own, from the worker's held summary (Kalshi positions matched to the
// live book). Each leg shows the strike to pair it on, the most to pay there, and the ask right now.
export default function HeldTotals({ held }) {
  const events = Object.values(held || {});
  if (!events.length) return <p className="empty">No open full-game totals on Kalshi right now. Buy one and it shows up here with the strike to pair it on.</p>;
  return (
    <section className="held">
      {events.map((ev) => (
        <div key={ev.game} className={`card held ${ev.phase === 'pre' || !ev.phase ? '' : 'later'}`}>
          <div className="heldhead">
            <span className="game">{ev.game}</span>
            {ev.game_id && <Link href={`/desk/?g=${ev.game_id}`} className="link">Desk</Link>}
          </div>
          {ev.built.map((b, i) => (
            <p key={`b${i}`} className="builtline">Middle built: O{b.over} + U{b.under}, {b.pairs} pairs at {b.paid_c}c. Final {b.lo} to {b.hi} pays {money(b.win)}; any other final {money(b.lose)}.</p>
          ))}
          {ev.legs.map((l) => {
            const covered = ev.built.some((b) => (l.side === 'yes' ? b.over === l.strike : b.under === l.strike));
            const hit = l.best;
            return (
              <div key={l.ticker} className="leg">
                <p className="hold">You hold <b>{l.side === 'yes' ? 'O' : 'U'}{l.strike}</b>, {l.shares} shares at {Number(l.paid_c).toFixed(0)}c{l.sell ? `. Sell now at ${l.sell.bid_c}c: ${money(l.sell.pnl)}` : ''}</p>
                {covered ? null : hit ? (
                  <p className="target on">Buy <b>{hit.kind === 'under' ? 'U' : 'O'}{hit.strike} at {hit.price_c}c</b>, {hit.pairs} shares ({money(hit.leg_cost)}). Final {hit.lo} to {hit.hi} pays {money(hit.win)}; any other final {money(hit.lose)}.</p>
                ) : l.targets.length ? (
                  <ul className="targets">
                    {l.targets.map((t) => (
                      <li key={t.strike} className={t.ask_c !== null && t.ask_c !== undefined && t.ask_c <= t.target_c ? 'on' : ''}>
                        <span>{t.kind === 'under' ? 'U' : 'O'}{t.strike}</span>
                        <span>at <b>{t.target_c}c</b> or less</span>
                        <span className="ask">now {t.ask_c ?? 'no'}{t.ask_c !== null && t.ask_c !== undefined ? 'c' : ' ask'}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="target">{ev.phase && ev.phase !== 'pre' ? 'Game is live. The half push covers middles from here.' : 'No pairable strike on the book yet.'}</p>
                )}
              </div>
            );
          })}
          <p className="when">{ago(ev.at)}</p>
        </div>
      ))}
    </section>
  );
}

// True when any held leg has a middle clearing the breakeven right now: the one thing worth a line on Today.
export function middleOpen(held) {
  return Object.values(held || {}).filter((ev) => (ev.legs || []).some((l) => l.best && !(ev.built || []).some((b) => (l.side === 'yes' ? b.over === l.strike : b.under === l.strike))));
}
