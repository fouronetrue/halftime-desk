'use client';
import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabase';
import { ago, etTime, money } from '@/lib/desk';

const SOURCES = [['all', 'All'], ['halftime', 'Halftime'], ['sharp', 'Sharp'], ['personal', 'Personal']];

export default function Ledger() {
  const [snap, setSnap] = useState(null);
  const [fills, setFills] = useState([]);
  const [src, setSrc] = useState('all');

  useEffect(() => {
    (async () => {
      const [{ data: s }, { data: f }] = await Promise.all([
        supabase.from('portfolio_snapshots').select('*').order('taken_at', { ascending: false }).limit(1),
        supabase.from('bets').select('fill_id,ticker,outcome_side,count,price_c,cost,fee,filled_at,source').order('filled_at', { ascending: false }).limit(200),
      ]);
      setSnap(s?.[0] || null);
      setFills(f || []);
    })();
  }, []);

  const shown = fills.filter((f) => src === 'all' || f.source === src);
  const total = snap ? Number(snap.balance || 0) + Number(snap.portfolio_value || 0) : null;
  return (
    <main>
      <header className="top">
        <h1>Ledger</h1>
        {snap && <p className="sub">Synced from Kalshi {ago(snap.taken_at)}</p>}
      </header>
      {snap && (
        <div className="board">
          <div><span>Cash</span><b>{money(snap.balance)}</b></div>
          <div><span>Positions</span><b>{money(snap.portfolio_value)}</b></div>
          <div><span>Bankroll</span><b>{money(total)}</b></div>
        </div>
      )}
      <div className="seg" role="tablist" aria-label="Source">
        {SOURCES.map(([k, l]) => <button key={k} role="tab" aria-selected={src === k} className={src === k ? 'on' : ''} onClick={() => setSrc(k)}>{l}</button>)}
      </div>
      <ul className="fills">
        {shown.map((f) => (
          <li key={f.fill_id}>
            <span className="tk">{f.ticker}</span>
            <span className="what">{f.outcome_side === 'yes' ? 'Yes' : 'No'} {Number(f.count)} at {Number(f.price_c)}c</span>
            <span className="amt">{money(f.cost)}</span>
            <span className="when">{etTime(f.filled_at)} {f.filled_at ? new Date(f.filled_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' }) : ''}</span>
            <span className={`src ${f.source}`}>{f.source}</span>
          </li>
        ))}
      </ul>
      {shown.length === 0 && <p className="empty">No {src === 'all' ? '' : `${src} `}fills in the last 200.</p>}
      <p className="sub">Retagging, notes and ROI by tier arrive with the full Ledger in week 3.</p>
    </main>
  );
}
