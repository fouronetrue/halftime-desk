'use client';
import { useMemo, useState } from 'react';
import { money, sizeMiddle } from '@/lib/desk';

const SORTS = [
  { key: 'ev', label: 'Best edge' },
  { key: 'win', label: 'Biggest hit' },
  { key: 'lose', label: 'Smallest miss' },
  { key: 'hit', label: 'Most likely' },
];

// Every Yes-low / No-high pairing on the ladder at the current asks (taken), sized to the same loss budget.
export default function MiddleCompare({ rows, sport, budget, maxCost, mids, pick, onPick }) {
  const [sort, setSort] = useState('ev');
  const [showPass, setShowPass] = useState(false);

  const all = useMemo(() => {
    const out = [];
    for (const o of rows) {
      for (const u of rows) {
        const lo = Number(o.strike), hi = Number(u.strike);
        if (!(hi > lo) || hi - lo > 10 || !o.yes_ask || !u.no_ask) continue;
        const numbers = Math.round(hi - lo);
        const known = (mids || []).find((x) => Number(x.a.line) === lo && Number(x.b.line) === hi);
        const pHit = known ? known.p_mid : Math.max(0, o.p_over - u.p_over - u.p_push);
        const r = sizeMiddle({ a: Number(o.yes_ask), b: Number(u.no_ask), numbers, sport, budget, maxCost, pHit });
        if (!r || !r.pairs) continue;
        const evDollars = Math.round(r.pairs * r.ev * 100) / 100;
        const band = [Number(o.yes_ask), Number(u.no_ask)].some((p) => p < 15 || p > 85);
        out.push({ lo, hi, numbers, a: o.yes_ask, b: u.no_ask, pHit, evDollars, band, ...r });
      }
    }
    return out;
  }, [rows, sport, budget, maxCost, mids]);

  const live = all.filter((x) => x.verdict !== 'pass' && !x.band);
  const list = (showPass ? all : live).slice().sort((x, y) => {
    const bad = (z) => (z.band || z.verdict === 'pass' ? 1 : 0);
    if (bad(x) !== bad(y)) return bad(x) - bad(y);
    if (sort === 'win') return y.win - x.win;
    if (sort === 'lose') return y.lose - x.lose;
    if (sort === 'hit') return y.pHit - x.pHit;
    return y.evDollars - x.evDollars;
  }).slice(0, 8);
  const hidden = all.length - live.length;

  if (!all.length) return null;
  return (
    <section className="mcomp" aria-label="Compare middles">
      <div className="mhead"><h3>Compare middles</h3><span className="mc-sub">risking ${budget} each</span></div>
      <span className="seg" role="group" aria-label="Sort by">
        {SORTS.map((s) => <button key={s.key} type="button" className={sort === s.key ? 'on' : ''} aria-pressed={sort === s.key} onClick={() => setSort(s.key)}>{s.label}</button>)}
      </span>
      {!list.length ? <p className="hint">No pairing clears breakeven at these asks.</p> : (
        <ol className="mclist">
          {list.map((x) => {
            const on = pick.over === x.lo && pick.under === x.hi;
            return (
              <li key={`${x.lo}-${x.hi}`}>
                <button type="button" className={`${on ? 'on' : ''} ${x.band ? 'pass' : x.verdict}`} aria-pressed={on} onClick={() => onPick(x.lo, x.hi)}>
                  <span className="mcl-pair">o{x.lo} / u{x.hi}<small>{x.a}c + {x.b}c, {x.numbers} num{x.band ? ', outside 15 to 85c' : ''}</small></span>
                  <span className="mcl-n"><small>{x.costCapped ? 'shares, cost cap' : 'shares'}</small>{x.pairs}</span>
                  <span className="mcl-n neg"><small>miss</small>{money(x.lose)}</span>
                  <span className="mcl-n pos"><small>hit</small>{money(x.win)}</span>
                  <span className="mcl-n"><small>hits</small>{Math.round(100 * x.pHit)}%</span>
                  <span className={`mcl-n ${x.evDollars >= 0 ? 'pos' : 'neg'}`}><small>edge</small>{money(x.evDollars)}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
      {hidden > 0 && <button type="button" className="link mc-more" onClick={() => setShowPass(!showPass)}>{showPass ? 'Hide passes' : `Show ${hidden} that fail breakeven or the 15 to 85c band`}</button>}
      <p className="mc-note">Every row risks the same budget, so a miss costs about the same everywhere. What changes is how much a hit pays and how often it hits. <b>Edge</b> is the average result per try at the model's hit rate: the fairest single number for comparing pairs. Prices are the last asks the watcher saw (every 15 seconds at the half), taken, fees in. "Cost cap" means size stopped at 7.5% of bankroll before it reached your budget, so the miss is smaller than the budget. Model hit rates under 15c or over 85c are not trusted; tap a row to size it at what Kalshi shows.</p>
    </section>
  );
}
