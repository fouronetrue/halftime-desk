'use client';
import { useCallback, useEffect, useState } from 'react';
import { supabase } from '@/lib/supabase';
import { ago, money, tickerInfo } from '@/lib/desk';
import HeldTotals from '@/components/HeldTotals';

// Bets: what you have on right now. Your totals first (the worker's held summary: each full-game total you own,
// with the strike to pair it on), then every open Kalshi position as the last sync saw it. Nothing here places,
// cancels or changes an order.
export default function Bets() {
  const [held, setHeld] = useState(null);
  const [positions, setPositions] = useState([]);
  const [snap, setSnap] = useState(null);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    const [{ data: hd, error }, { data: ps }, { data: s }] = await Promise.all([
      supabase.from('desk_state').select('state,last_beat').eq('id', 'held').maybeSingle(),
      supabase.from('positions').select('ticker,event_ticker,position,total_traded,exposure,realized_pnl,fees_paid,last_updated,synced_at')
        .eq('settlement_status', 'unsettled').neq('position', 0).order('last_updated', { ascending: false }),
      supabase.from('portfolio_snapshots').select('taken_at,balance,portfolio_value').order('taken_at', { ascending: false }).limit(1),
    ]);
    if (error) { setErr(error.message); return; }
    setErr('');
    setHeld(hd?.state || {});
    setPositions(ps || []);
    setSnap(s?.[0] || null);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(() => { if (document.visibilityState === 'visible') load(); }, 60000);
    const onVis = () => document.visibilityState === 'visible' && load();
    document.addEventListener('visibilitychange', onVis);
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVis); };
  }, [load]);

  if (held === null && !err) return <main />;
  const inPlay = positions.reduce((s, p) => s + Number(p.exposure || 0), 0);
  const synced = positions[0]?.synced_at || snap?.taken_at;
  return (
    <main>
      <header className="top">
        <h1>Bets</h1>
        {snap ? (
          <p className="sub">Bankroll <b className="chalk">{money(Number(snap.balance || 0) + Number(snap.portfolio_value || 0))}</b>: {money(snap.balance)} cash, {money(snap.portfolio_value)} in positions. Synced {ago(synced)}.</p>
        ) : <p className="sub">Waiting for the first Kalshi sync.</p>}
      </header>
      {err && <p className="err">Could not load: {err}</p>}

      <h2>Your totals</h2>
      <HeldTotals held={held} />

      <h2>Open positions{positions.length ? ` (${positions.length}, ${money(inPlay)} at risk)` : ''}</h2>
      {positions.length === 0 ? <p className="empty">Nothing open on Kalshi.</p> : (
        <ul className="poslist">
          {positions.map((p) => {
            const t = tickerInfo(p.ticker, p.position);
            const n = Math.abs(Number(p.position));
            const paid = p.total_traded && n ? Math.round((100 * Number(p.total_traded)) / n) : null;
            return (
              <li key={p.ticker} className={`pos-row ${t.kind || 'other'}`}>
                <span className="what">{t.what}</span>
                <span className="amt">{money(p.exposure)}</span>
                <span className="game">{t.game}{t.date ? `, ${new Date(`${t.date}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })}` : ''}</span>
                <span className="detail">{n} shares{paid ? ` at about ${paid}c` : ''}</span>
              </li>
            );
          })}
        </ul>
      )}
      <p className="sub">Positions and the bankroll come from the read-only Kalshi sync (every 2 minutes on game days, every 30 otherwise). Nothing here places an order; you tap buy.</p>
    </main>
  );
}
