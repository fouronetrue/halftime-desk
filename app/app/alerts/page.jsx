'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { supabase } from '@/lib/supabase';
import { ago, etTime } from '@/lib/desk';

export default function Alerts() {
  const [alerts, setAlerts] = useState(null);
  const [graded, setGraded] = useState({});
  const [open, setOpen] = useState(null);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.from('alerts').select('*').order('sent_at', { ascending: false }).limit(60);
      setAlerts(data || []);
      const ids = [...new Set((data || []).map((a) => a.game_id))];
      if (ids.length) {
        const { data: r } = await supabase.from('results').select('game_id,final,plays_pnl,mid_pnl,n_plays').in('game_id', ids);
        setGraded(Object.fromEntries((r || []).map((x) => [x.game_id, x])));
      }
    })();
  }, []);

  if (alerts === null) return <main />;
  return (
    <main>
      <header className="top"><h1>Alerts</h1><p className="sub">Every push the watcher sent, newest first.</p></header>
      {alerts.length === 0 && <p className="empty">No pushes yet. The first one goes out at the next half where the watcher finds a Kalshi total.</p>}
      <ul className="feed">
        {alerts.map((a) => {
          const r = graded[a.game_id];
          const pnl = r ? Number(r.plays_pnl || 0) + Number(r.mid_pnl || 0) : null;
          return (
            <li key={a.id} className={`alert ${a.kind}`}>
              <button onClick={() => setOpen(open === a.id ? null : a.id)} aria-expanded={open === a.id}>
                <span className="kind">{a.kind === 'play' ? 'PLAY' : 'UPDATE'}</span>
                <span className="title">{a.title}</span>
                <span className="when">{etTime(a.sent_at)}, {ago(a.sent_at)}</span>
                {r && <span className={`grade ${pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : ''}`}>Final {r.final}{a.kind === 'play' ? `, ${pnl >= 0 ? '+' : ''}${pnl.toFixed(0)}` : ''}</span>}
              </button>
              {open === a.id && (<><pre>{a.body}</pre><Link className="link" href={`/desk/?g=${a.game_id}`}>Open the desk</Link></>)}
            </li>
          );
        })}
      </ul>
    </main>
  );
}
