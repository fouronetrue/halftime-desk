'use client';
import { useEffect, useState } from 'react';
import { money, orderFee, sizeMiddle, sizeHeld, heldOutcomes } from '@/lib/desk';

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
      {['take', 'rest', 'held'].map((m) => (
        <button key={m} type="button" className={value === m ? 'on' : ''} aria-pressed={value === m} onClick={() => set(m)}>{m === 'take' ? 'Take' : m === 'rest' ? 'Rest' : 'I hold'}</button>
      ))}
    </span>
  );
}

// The dollars already in a held leg (contracts times the price paid, the way Kalshi's ticket shows the cost);
// the share count follows, and the fee is added back on since the leg was taken at the ask.
function Held({ id, label, dollars, set, shares, paid }) {
  const cost = shares ? Math.round((shares * paid / 100 + orderFee(shares, paid / 100)) * 100) / 100 : 0;
  return (
    <div className="mc-held">
      <label htmlFor={id}>{label}</label>
      <div className="mc-step mc-dollars">
        <span>$</span>
        <input id={id} inputMode="decimal" value={dollars} onChange={(e) => set(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="75" />
        <span className="mc-shares">{shares ? `${shares} sh` : ''}</span>
      </div>
      <span className="mc-sub">{shares ? `${money(cost)} in with the fee` : 'dollars in the leg'}</span>
    </div>
  );
}

// The call on a pair: a free roll, a play, a thin play or a pass, from its all-in cost against the breakeven.
function Verdict({ free, verdict, children }) {
  const cls = free ? 'free' : verdict || '';
  const word = free ? 'Free roll' : verdict === 'play' ? 'Play' : verdict === 'thin' ? 'Thin play' : verdict === 'pass' ? 'Pass' : 'Held';
  return <p className={`mc-verdict ${cls}`}><b>{word}</b><span>{children}</span></p>;
}

// The three finals as a stat row; even inside half a cent.
function Finals({ rows }) {
  return (
    <dl className="mstats mc-outcomes">
      {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className={v < -0.005 ? 'neg' : v > 0.005 ? 'pos' : ''}>{Math.abs(v) < 0.005 ? 'even' : money(v)}</dd></div>)}
    </dl>
  );
}

// While the keyboard is up the readout sits under it, so the call rides in a bar pinned just above the keys
// (the shell keeps --vvt and --vvh at the visible area; the bar only shows with the keyboard, see .kb in the css).
function KbBar({ free, verdict, line, finals }) {
  const cls = free ? 'free' : verdict || '';
  const word = free ? 'Free roll' : verdict === 'play' ? 'Play' : verdict === 'thin' ? 'Thin play' : verdict === 'pass' ? 'Pass' : 'Held';
  return (
    <div className={`mc-kbbar ${cls}`} aria-live="polite">
      <div><b>{word}</b><span>{line}</span></div>
      <div className="mc-kbfinals">{finals.map(([k, v]) => <span key={k}>{k} <b className={v < -0.005 ? 'neg' : v > 0.005 ? 'pos' : ''}>{Math.abs(v) < 0.005 ? 'even' : money(v)}</b></span>)}</div>
    </div>
  );
}

// One leg held: the other side's size, the three finals at that size, and the prices that change the call.
function HeldReadout({ r, heldName, otherName, otherPrice, budget, maxCost }) {
  const held = heldName.toLowerCase(), other = otherName.toLowerCase();
  const pick = r.pick;
  const why = r.free ? `Your ${held} pays for it, so no final loses. Past ${r.protect.n} shares the ${held} winning alone starts to cost you.`
    : r.verdict === 'pass' ? `The pair is over breakeven, so this hedge is not a play: it buys the smallest worst case, not an edge. Fewer ${other} shares cut one miss and grow the other.`
    : `Matching what you hold makes a miss cost the same whichever side hits alone, and no size gets the worst case lower. More than you hold is a naked ${other} bet.`;
  const rows = [[`${heldName} wins alone`, pick.heldAlone], ['Both (the middle)', pick.both], [`${otherName} wins alone`, pick.otherAlone]];
  return (
    <>
      <Verdict free={r.free} verdict={r.verdict}>Pair {(100 * r.c).toFixed(1)}c all in with your {held} at cost, breakeven {(100 * r.breakeven).toFixed(1)}c</Verdict>
      <p className="mc-big">{pick.n}<small> {other} shares at {otherPrice}c</small></p>
      <p className="mc-miss"><b>{money(pick.dollars)}</b>{pick.fee ? `plus ${money(pick.fee)} fee` : 'no fee resting'}, {money(r.costA + pick.dollars + pick.fee)} in the game all told</p>
      <p className="mc-note">{why}</p>
      <Finals rows={rows} />
      <p className="mc-note">
        {r.free ? ` Matching them, ${r.even.n} shares, keeps a miss at ${money(r.even.heldAlone)} either way with the middle ${money(r.even.both)}.`
          : ` Covering the ${held} instead, ${r.protect.n} shares, leaves the ${held} alone ${Math.abs(r.protect.heldAlone) < 0.005 ? 'even' : money(r.protect.heldAlone)} and the ${other} alone ${money(r.protect.otherAlone)}.`}
        {r.overBudget ? ` A miss at ${r.even.n} shares is ${money(r.even.heldAlone)}, past your $${budget}; no ${other} size gets it inside.` : ''}
        {r.freeC ? ` Free roll at ${r.freeC}c or less on the ${other}` : ` No ${other} price makes this a free roll`}
        {r.maxC ? `; inside breakeven up to ${r.maxC}c.` : '; nothing inside breakeven either.'}
        {r.overCap ? ` Both legs together pass the 7.5% cost cap (${money(maxCost)}); the hedge still cuts the worst case, so that is a flag here, not a limit.` : ''}
      </p>
    </>
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
  const [dA, setDA] = useState('');   // dollars in a held over leg
  const [dB, setDB] = useState('');   // dollars in a held under leg
  const [addP, setAddP] = useState('');   // both held: the price to even up the lighter side at ('' = its price paid)
  const [typing, setTyping] = useState(false);   // an input here has focus, so the keyboard may be up
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
        if (s.dA !== undefined) setDA(s.dA);
        if (s.dB !== undefined) setDB(s.dB);
        if (s.addP !== undefined) setAddP(s.addP);
        if (s.budget !== undefined && budgetIn === undefined) setBudgetOwn(s.budget);
      }
    } catch { /* private mode or blocked storage */ }
    setLoaded(true);
  }, [storeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!storeKey || !loaded) return;
    try { localStorage.setItem(storeKey, JSON.stringify({ a, b, oFill, uFill, dA, dB, addP, budget })); } catch { /* ignore */ }
  }, [storeKey, loaded, a, b, oFill, uFill, dA, dB, addP, budget]);

  const numbers = Math.round(Number(underLine) - Number(overLine));
  const linesOk = Number(underLine) > Number(overLine) && numbers >= 1;
  const heldA = oFill === 'held', heldB = uFill === 'held';
  const sharesA = heldA && Number(a) > 0 ? Math.floor(Number(dA || 0) / (Number(a) / 100) + 1e-9) : 0;
  const sharesB = heldB && Number(b) > 0 ? Math.floor(Number(dB || 0) / (Number(b) / 100) + 1e-9) : 0;
  // a held leg was bought at the ask, so its fee is in; the other side's fill is whatever its toggle says
  const r = linesOk && !heldA && !heldB ? sizeMiddle({ a: Number(a), b: Number(b), oFill, uFill, numbers, sport, budget: Number(budget) || 0, maxCost, pHit }) : null;
  const h = linesOk && heldA !== heldB ? sizeHeld({
    held: { side: heldA ? 'over' : 'under', paid: heldA ? a : b, fill: 'take', dollars: heldA ? dA : dB },
    other: { price: heldA ? b : a, fill: heldA ? uFill : oFill }, numbers, sport, budget: Number(budget) || 0, maxCost,
  }) : null;
  const two = linesOk && heldA && heldB ? heldOutcomes({ over: { paid: a, fill: 'take', dollars: dA }, under: { paid: b, fill: 'take', dollars: dB }, numbers, sport,
    add: addP !== '' ? { price: addP, fill: 'take' } : undefined }) : null;
  // what the keyboard bar shows for whichever mode is live
  const bar = two ? { free: two.free, verdict: two.verdict, line: `pair ${(100 * two.c).toFixed(1)}c, breakeven ${(100 * two.breakeven).toFixed(1)}c`,
                      finals: [['Over', two.overAlone], ['Middle', two.both], ['Under', two.underAlone]] }
    : h ? { free: h.free, verdict: h.verdict, line: `${h.pick.n} ${heldA ? 'under' : 'over'} at ${heldA ? b : a}c, ${money(h.pick.dollars)}`,
            finals: [[heldA ? 'Over' : 'Under', h.pick.heldAlone], ['Middle', h.pick.both], [heldA ? 'Under' : 'Over', h.pick.otherAlone]] }
    : r ? { free: r.free, verdict: r.verdict, line: `${r.pairs} each side, ${money(r.cost)} in`, finals: [['Hit', r.win], ['Miss', r.lose]] } : null;
  const moved = askA !== undefined && askB !== undefined && (Number(a) !== Number(askA) || Number(b) !== Number(askB));
  const band = [a, b].some((p) => Number(p) < 15 || Number(p) > 85);

  const focusIn = () => setTyping(true);
  const focusOut = (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setTyping(false); };
  return (
    <section className={`mcalc${typing ? ' typing' : ''}`} aria-label="Middle size" onFocusCapture={focusIn} onBlurCapture={focusOut}>
      <div className="mc-row">
        <div className="mc-leg"><span className="mc-name">Over {overLine}</span><Fill name="Over" value={oFill} set={setOFill} /><Price id="mc-a" label={heldA ? 'Over price paid' : 'Over price'} value={a} set={setA} />
          {heldA && <Held id="mc-da" label="Dollars in the over" dollars={dA} set={setDA} shares={sharesA} paid={Number(a)} />}</div>
        <div className="mc-leg"><span className="mc-name">Under {underLine}</span><Fill name="Under" value={uFill} set={setUFill} /><Price id="mc-b" label={heldB ? 'Under price paid' : 'Under price'} value={b} set={setB} />
          {heldB && <Held id="mc-db" label="Dollars in the under" dollars={dB} set={setDB} shares={sharesB} paid={Number(b)} />}</div>
      </div>
      <div className="mc-budget" role="group" aria-label="Most to lose">
        <span>Most I'll lose</span>
        {BUDGETS.map((v) => <button key={v} type="button" className={Number(budget) === v ? 'on' : ''} aria-pressed={Number(budget) === v} onClick={() => setBudget(v)}>${v}</button>)}
        <input id="mc-budget" aria-label="Loss budget in dollars" inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^0-9.]/g, ''))} />
      </div>
      {two ? (
        <>
          <Verdict free={two.free} verdict={two.verdict}>Pair {(100 * two.c).toFixed(1)}c all in at your prices, breakeven {(100 * two.breakeven).toFixed(1)}c</Verdict>
          <p className="mc-note">You hold {two.nA} over at {a}c ({money(two.costA)}) and {two.nB} under at {b}c ({money(two.costB)}), fees in.</p>
          <Finals rows={[['Over wins alone', two.overAlone], ['Both (the middle)', two.both], ['Under wins alone', two.underAlone]]} />
          {two.even ? (
            <p className="mc-note mc-even">
              Even up: <b>{two.even.n}</b> more {two.even.side} at{' '}
              <span className="mc-nowrap"><input className="mc-inline" inputMode="numeric" aria-label={`Price to add ${two.even.side} shares at`} value={addP} placeholder={String(two.even.price)}
                     onChange={(e) => setAddP(e.target.value.replace(/[^0-9]/g, '').slice(0, 2))} />c</span>
              {' '}({money(two.even.dollars)}{two.even.fee ? ` + ${money(two.even.fee)} fee` : ''}): a miss <b>{Math.abs(two.even.miss) < 0.005 ? 'even' : money(two.even.miss)}</b> either way, the middle <b>{money(two.even.both)}</b>.
            </p>
          ) : <p className="mc-note">Even shares each side: a miss costs the same whichever side hits alone.</p>}
        </>
      ) : h ? (
        <HeldReadout r={h} heldName={heldA ? 'Over' : 'Under'} otherName={heldA ? 'Under' : 'Over'} otherPrice={heldA ? b : a} budget={Number(budget) || 0} maxCost={maxCost} />
      ) : (heldA || heldB) ? <p className="hint">{linesOk ? 'Enter the price you paid and the dollars in the leg you hold, and the other side\'s price.' : 'The under line has to sit above the over line. Your prices and budget are kept.'}</p>
      : !r ? <p className="hint">{linesOk ? 'Enter both prices.' : 'The under line has to sit above the over line. Your prices and budget are kept.'}</p> : (
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
      {typing && bar && <KbBar {...bar} />}
    </section>
  );
}
