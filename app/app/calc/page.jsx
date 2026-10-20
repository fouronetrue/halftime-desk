'use client';
import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import MiddleCalc from '@/components/MiddleCalc';

// Standalone middle calculator: works with no game loaded. The Desk links here with ?s=&o=&u=&a=&b= to carry a pick over.
function CalcView() {
  const q = useSearchParams();
  const [sport, setSport] = useState(q.get('s') === 'cfb' ? 'cfb' : 'nfl');
  const [o, setO] = useState(q.get('o') || '48.5');
  const [u, setU] = useState(q.get('u') || '51.5');
  const ok = Number(u) > Number(o);
  return (
    <main>
      {q.get('o') && <p className="back"><Link href="/desk/">Back to the Desk</Link></p>}
      <h1>Middle calc</h1>
      <p className="sub">Two lines, two prices, a loss budget. Pair cost against the breakeven, shares each side, what both pay.</p>
      <span className="seg" role="group" aria-label="Sport">
        {['nfl', 'cfb'].map((s) => <button key={s} className={sport === s ? 'on' : ''} aria-pressed={sport === s} onClick={() => setSport(s)}>{s.toUpperCase()}</button>)}
      </span>
      <div className="mc-lines">
        <label htmlFor="mc-o">Over line<input id="mc-o" inputMode="decimal" value={o} onChange={(e) => setO(e.target.value)} /></label>
        <label htmlFor="mc-u">Under line<input id="mc-u" inputMode="decimal" value={u} onChange={(e) => setU(e.target.value)} /></label>
      </div>
      {ok ? (
        <MiddleCalc sport={sport} overLine={o} underLine={u} askA={q.get('a') || 53} askB={q.get('b') || 51} budget0={Number(q.get('l')) || 10} maxCost={0} />
      ) : <p className="err">The under line has to sit above the over line.</p>}
    </main>
  );
}

export default function Calc() {
  return <Suspense fallback={<main />}><CalcView /></Suspense>;
}
