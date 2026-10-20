'use client';
import { useEffect, useState } from 'react';
import { money, sizeMiddle } from '@/lib/desk';

const BUDGETS = [5, 10, 15, 20];

function Price({ id, label, value, set }) {
  const bump = (d) => set(Math.min(99, Math.max(1, (Number(value) || 50) + d)));
  return (
    <div className="mc-price">
      <label htmlFor={id}>{label}</label>
      <div className="mc-step">
        <button type="button" onClick={() => bump(-1)} aria-label={`${label} down a cent`}>&minus;</button>
        <input id={id} inputMode="numeric" value={value} onChange={(e) => set(e.target.value.replace(/[^0-9]/g, ''))} />
        <button type="button" onClick={() => bump(1)} aria-label={`${label} up a cent`}>+</button>
      </div>
    </div>
  );
}

function Fill({ name, value, set }) {
  return (
    <span className="seg mc-fill" role="group" aria-label={`${name} fill`}>
      {['take', 'rest'].map((m) => (
        <button key={m} type="button" className={value === m ? 'on' : ''} aria-pressed={value === m} onClick={() => set(m)}>{m === 'take' ? 'Take' : 'Rest'}</button>
      ))}
    </span>
  );
}

// The calculator under the Desk's middle builder and on /calc/. Prices start at the ladder's asks; nudge them to what Kalshi shows.
// On the Desk a new pick loads that pick's asks. With storeKey set (the Calc tab) nothing ever resets what you typed:
// prices, fills and the budget stay put while you change the lines, and come back when you return to the tab.
export default function MiddleCalc({ sport, overLine, underLine, askA, askB, budget0, budget: budgetIn, setBudget: setBudgetIn, maxCost, pHit, storeKey, restore = true }) {
  const [a, setA] = useState(askA ?? '');
  const [b, setB] = useState(askB ?? '');
  const [oFill, setOFill] = useState('take');
  const [uFill, setUFill] = useState('take');
  const [budgetOwn, setBudgetOwn] = useState(budget0 ? Math.round(budget0) : 10);
  const [loaded, setLoaded] = useState(!storeKey);
  // The Desk owns the budget so Compare middles and this calculator size to the same number.
  const budget = budgetIn ?? budgetOwn, setBudget = setBudgetIn ?? setBudgetOwn;

  // A new pick resets the prices to that pick's asks; a ladder refresh on the same pick leaves your nudges alone.
  useEffect(() => { if (!storeKey) { setA(askA ?? ''); setB(askB ?? ''); } }, [overLine, underLine]); // eslint-disable-line react-hooks/exhaustive-deps

  // Calc tab: remember the last prices, fills and budget on this phone (a convenience, never load-bearing).
  useEffect(() => {
    if (!storeKey) return;
    if (!restore) { setLoaded(true); return; }   // the Desk sent its own asks: keep those, start saving from here
    try {
      const s = JSON.parse(localStorage.getItem(storeKey) || 'null');
      if (s) {
        if (s.a !== undefined) setA(s.a);
        if (s.b !== undefined) setB(s.b);
        if (s.oFill) setOFill(s.oFill);
        if (s.uFill) setUFill(s.uFill);
        if (s.budget !== undefined && budgetIn === undefined) setBudgetOwn(s.budget);
      }
    } catch { /* private mode or blocked storage */ }
    setLoaded(true);
  }, [storeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!storeKey || !loaded) return;
    try { localStorage.setItem(storeKey, JSON.stringify({ a, b, oFill, uFill, budget })); } catch { /* ignore */ }
  }, [storeKey, loaded, a, b, oFill, uFill, budget]);

  const numbers = Math.round(Number(underLine) - Number(overLine));
  const linesOk = Number(underLine) > Number(overLine) && numbers >= 1;
  const r = linesOk ? sizeMiddle({ a: Number(a), b: Number(b), oFill, uFill, numbers, sport, budget: Number(budget) || 0, maxCost, pHit }) : null;
  const moved = askA !== undefined && askB !== undefined && (Number(a) !== Number(askA) || Number(b) !== Number(askB));
  const band = [a, b].some((p) => Number(p) < 15 || Number(p) > 85);

  return (
    <section className="mcalc" aria-label="Middle size">
      <div className="mc-row">
        <div className="mc-leg"><span className="mc-name">Over {overLine}</span><Fill name="Over" value={oFill} set={setOFill} /><Price id="mc-a" label="Over price" value={a} set={setA} /></div>
        <div className="mc-leg"><span className="mc-name">Under {underLine}</span><Fill name="Under" value={uFill} set={setUFill} /><Price id="mc-b" label="Under price" value={b} set={setB} /></div>
      </div>
      <div className="mc-budget" role="group" aria-label="Most to lose">
        <span>Most I'll lose</span>
        {BUDGETS.map((v) => <button key={v} type="button" className={Number(budget) === v ? 'on' : ''} aria-pressed={Number(budget) === v} onClick={() => setBudget(v)}>${v}</button>)}
        <input id="mc-budget" aria-label="Loss budget in dollars" inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^0-9.]/g, ''))} />
      </div>
      {!r ? <p className="hint">{linesOk ? 'Enter both prices.' : 'The under line has to sit above the over line. Your prices and budget are kept.'}</p> : (
        <>
          <p className={`mc-verdict ${r.free ? 'free' : r.verdict}`}>
            <b>{r.free ? 'Free roll' : r.verdict === 'play' ? 'Play' : r.verdict === 'thin' ? 'Thin play' : 'Pass'}</b>
            <span>All-in {(100 * r.c).toFixed(1)}c, breakeven {(100 * r.breakeven).toFixed(1)}c{moved ? ', at your prices' : ''}</span>
          </p>
          <p className="mc-big">{r.pairs}<small> shares each side</small></p>
          <p className={`mc-miss ${r.lose < 0 ? 'neg' : 'pos'}`}>
            <b>{r.lose < 0 ? `Miss ${money(r.lose)}` : r.lose > 0 ? `Miss wins ${money(r.lose)}` : 'Miss even'}</b> whichever side hits alone
            {r.free ? '. No final loses.' : r.over > 0 ? `. Free at ${r.freeB}c on the under${r.freeB < Number(b) ? '' : ' (or less)'}.` : '.'}
          </p>
          <dl className="mstats">
            <div><dt>Over leg</dt><dd>{money(r.dollarsA)}</dd></div>
            <div><dt>Under leg</dt><dd>{money(r.dollarsB)}</dd></div>
            <div><dt>Total in</dt><dd>{money(r.cost)}</dd></div>
            <div><dt>Hit</dt><dd className="pos">{money(r.win)}</dd></div>
            <div><dt>Hit to miss</dt><dd>{r.lose < 0 ? `${(r.win / -r.lose).toFixed(1)} to 1` : 'lock'}</dd></div>
            <div><dt>{r.ev === null ? 'Need hit' : 'Edge a pair'}</dt><dd className={r.ev === null ? '' : r.ev >= 0.03 ? 'pos' : 'neg'}>{r.ev === null ? `${Math.max(0, 100 * r.over).toFixed(1)}%` : `${(100 * r.ev).toFixed(1)}c`}</dd></div>
          </dl>
          <p className="mc-note">
            {r.over > 0 ? `A miss costs ${(100 * r.over).toFixed(1)}c a pair` : `A miss pays ${(-100 * r.over).toFixed(1)}c a pair`}{r.fees ? `, fees ${money(r.fees)} in` : ''}. If the over fills at {a}, the under can go to <b>{r.maxB}c</b> and stay inside breakeven. Never buy more under shares than over shares filled.
            {r.costCapped ? ` Held to the 7.5% cost cap (${money(maxCost)}).` : ''}
            {band ? ' A leg is outside the 15 to 85c band.' : ''}
          </p>
        </>
      )}
    </section>
  );
}
