'use client';
import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import MiddleCalc from '@/components/MiddleCalc';
import { supabase } from '@/lib/supabase';

const LINES_KEY = 'hd-calc-lines';

// Standalone middle calculator: works with no game loaded. The Desk links here with ?s=&o=&u=&a=&b= to carry a
// pick over. Nothing resets while you work: the calculator stays mounted while a line is mid-edit, and the
// lines, sport, prices, fills and budget are remembered on this phone until you change them.
function CalcView() {
  const q = useSearchParams();
  const fromDesk = Boolean(q.get('o'));
  const [sport, setSport] = useState(['cfb', 'nba'].includes(q.get('s')) ? q.get('s') : 'nfl');
  const [o, setO] = useState(q.get('o') || '48.5');
  const [u, setU] = useState(q.get('u') || '51.5');
  const [loaded, setLoaded] = useState(false);
  // A free roll (a miss loses nothing) is sized by the project's cost cap, 7.5% of bankroll a game, not by the
  // loss budget. The bankroll comes from the last Kalshi sync; $250 until it answers.
  const [maxCost, setMaxCost] = useState(250);
  useEffect(() => {
    supabase?.from('portfolio_snapshots').select('balance,portfolio_value').order('taken_at', { ascending: false }).limit(1)
      .then(({ data }) => { const s = data?.[0]; if (s) setMaxCost(Math.round(0.075 * (Number(s.balance || 0) + Number(s.portfolio_value || 0)))); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!fromDesk) {
      try {
        const s = JSON.parse(localStorage.getItem(LINES_KEY) || 'null');
        if (s) { if (s.sport) setSport(s.sport); if (s.o !== undefined) setO(s.o); if (s.u !== undefined) setU(s.u); }
      } catch { /* private mode */ }
    }
    setLoaded(true);
  }, [fromDesk]);
  useEffect(() => {
    if (!loaded) return;
    try { localStorage.setItem(LINES_KEY, JSON.stringify({ sport, o, u })); } catch { /* ignore */ }
  }, [loaded, sport, o, u]);

  return (
    <main>
      {fromDesk && <p className="back"><Link href="/desk/">Back to the Desk</Link></p>}
      <h1>Middle calc</h1>
      <p className="sub">Two lines, two prices, a loss budget. Pair cost against the breakeven, shares each side, what both pay.</p>
      <span className="seg" role="group" aria-label="Sport">
        {['nfl', 'cfb', 'nba'].map((s) => <button key={s} className={sport === s ? 'on' : ''} aria-pressed={sport === s} onClick={() => setSport(s)}>{s.toUpperCase()}</button>)}
      </span>
      <div className="mc-lines">
        <label htmlFor="mc-o">Over line<input id="mc-o" inputMode="decimal" value={o} onChange={(e) => setO(e.target.value)} /></label>
        <label htmlFor="mc-u">Under line<input id="mc-u" inputMode="decimal" value={u} onChange={(e) => setU(e.target.value)} /></label>
      </div>
      <MiddleCalc sport={sport} overLine={o} underLine={u} askA={q.get('a') || 53} askB={q.get('b') || 51} budget0={Number(q.get('l')) || 10} maxCost={maxCost} storeKey="hd-calc" restore={!fromDesk} />
    </main>
  );
}

export default function Calc() {
  return <Suspense fallback={<main />}><CalcView /></Suspense>;
}
