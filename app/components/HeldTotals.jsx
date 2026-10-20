'use client';
import Link from 'next/link';
import { ago, money } from '@/lib/desk';

// Your totals: every full-game total you own, from the worker's held summary (Kalshi positions matched to the
// live book). Each leg shows the strike to pair it on and two prices: "free", where the leg you hold pays for
// the other one outright (no final loses), and "worth it", the project breakeven where a miss still costs a
// little. The ask right now sits next to them. A free pair is sized so your side winning alone nets $0.
const even = (x) => (Math.abs(Number(x)) < 1 ? 'even' : money(x));
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
                <p className="hold">You hold <b>{l.side === 'yes' ? 'O' : 'U'}{l.strike}</b>, {l.shares} shares at {Number(l.paid_c).toFixed(0)}c{l.sell ? `. Sell now at ${l.sell.bid_c}c: ${money(l.sell.pnl)}` : ''}{!covered && l.free_c && !(hit && hit.tier === 'free') ? `. It pays for the other side at ${l.free_c}c taken, ${l.free_rest_c}c resting.` : ''}</p>
                {covered ? null : hit && hit.tier === 'free' ? (
                  <p className="target free"><b>FREE:</b> Buy <b>{hit.kind === 'under' ? 'U' : 'O'}{hit.strike} at {hit.price_c}c</b>, {hit.pairs} shares ({money(hit.leg_cost)}). Final {hit.lo} to {hit.hi} pays {money(hit.both)}. {l.side === 'yes' ? 'Over' : 'Under'} alone {even(hit.held_alone)}, {l.side === 'yes' ? 'under' : 'over'} alone {even(hit.other_alone)}. Your {l.side === 'yes' ? 'over' : 'under'} pays for it.</p>
                ) : hit ? (
                  <p className="target on">Buy <b>{hit.kind === 'under' ? 'U' : 'O'}{hit.strike} at {hit.price_c}c</b>, {hit.pairs} shares ({money(hit.leg_cost)}). Final {hit.lo} to {hit.hi} pays {money(hit.win)}; any other final {money(hit.lose)}.</p>
                ) : l.targets.length ? (
                  <ul className="targets">
                    {l.targets.map((t) => {
                      const ask = t.ask_c !== null && t.ask_c !== undefined ? t.ask_c : null;
                      const cls = ask === null ? '' : ask <= (t.free_c || 0) ? 'free' : ask <= t.target_c ? 'on' : '';
                      return (
                        <li key={t.strike} className={cls}>
                          <span>{t.kind === 'under' ? 'U' : 'O'}{t.strike}</span>
                          <span>{t.free_c ? <>free <b>{t.free_c}c</b>, </> : null}worth it <b>{t.target_c}c</b></span>
                          <span className="ask">now {ask ?? 'no'}{ask !== null ? 'c' : ' ask'}</span>
                        </li>
                      );
                    })}
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

// True when one of those open middles is free (the held leg pays for the other one).
export function freeOpen(ev) {
  return (ev.legs || []).some((l) => l.best?.tier === 'free');
}
