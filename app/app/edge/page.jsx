'use client';
import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabase';

const GATE = 250;

export default function Edge() {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    supabase.from('results').select('model_err,mkt_err,plays_cost,plays_pnl,mid_pnl').then(({ data }) => setRows(data || []));
  }, []);
  if (rows === null) return <main />;
  const n = rows.length;
  const both = rows.filter((r) => r.model_err !== null && r.mkt_err !== null);
  const closer = both.filter((r) => Number(r.model_err) < Number(r.mkt_err)).length;
  const cost = rows.reduce((s, r) => s + Number(r.plays_cost || 0), 0);
  const pnl = rows.reduce((s, r) => s + Number(r.plays_pnl || 0), 0);
  return (
    <main>
      <header className="top"><h1>Edge</h1><p className="sub">Whether the model beats the market. The full scorecard lands in week 4.</p></header>
      <div className="progress" role="img" aria-label={`${n} of ${GATE} halftimes graded`}>
        <div className="fill" style={{ width: `${Math.min(100, (100 * n) / GATE)}%` }} />
      </div>
      <p className="gaugetext"><b>{n}</b> of {GATE} halftimes graded.</p>
      {n > 0 && (
        <div className="board">
          <div><span>Model closer</span><b>{both.length ? `${closer} of ${both.length}` : 'n/a'}</b></div>
          <div><span>Plays P&amp;L</span><b className={pnl >= 0 ? 'pos' : 'neg'}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(0)}</b></div>
          <div><span>ROI</span><b>{cost ? `${((100 * pnl) / cost).toFixed(1)}%` : 'n/a'}</b></div>
        </div>
      )}
    </main>
  );
}
