'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { supabase } from '@/lib/supabase';
import { ago, etTime, gradeSheet, sheetFromSuggestion, kalshiUrl } from '@/lib/desk';

// Every push, graded on its own text. A PLAY is graded on what it led with (the first single, or the middle when
// it led with one, or the reverse middle when it was all that cleared); the other lines in the push are backups and are graded as what they would have done. An
// UPDATE named no play, so it shows the final and nothing else. The grade comes from the push's own sheet
// (alerts.sheet), rebuilt from its suggestions row for pushes sent before sheets were kept.
const signed = (v) => `${v >= 0 ? '+' : '-'}$${Math.abs(v).toFixed(Math.abs(v) >= 100 ? 0 : 2)}`;

function Grade({ a, g, final }) {
  if (!final) return <span className="grade">Not final yet</span>;
  if (a.kind !== 'play') return <span className="grade">Final {final.text}. No play named.</span>;
  if (!g) return <span className="grade">Final {final.text}. Could not grade this push.</span>;
  if (!g.play) return <span className="grade">Final {final.text}. Nothing to grade.</span>;
  return (
    <span className={`grade call ${g.play.win ? 'win' : 'loss'}`}>
      <b>{g.play.label}</b> {signed(g.play.pnl)} on {g.play.what}. Final {final.text}.
    </span>
  );
}

function Detail({ a, g, final }) {
  if (!g || !final) return null;
  const backups = g.options.filter((o) => !o.play);
  return (
    <ul className="gradelist">
      {g.options.filter((o) => o.play).map((o, i) => (
        <li key={`p${i}`} className={o.win ? 'win' : 'loss'}><b>{o.win ? 'WIN' : 'LOSS'}</b> {o.kind === 'over' ? 'Over' : 'Under'} {Number(o.line)} at {o.price_c}c, {o.contracts} shares: {signed(o.pnl)}. The play.</li>
      ))}
      {backups.map((o, i) => (
        <li key={`b${i}`} className={`alt ${o.win ? 'win' : 'loss'}`}><b>{o.win ? 'would have won' : 'would have lost'}</b> {o.kind === 'over' ? 'Over' : 'Under'} {Number(o.line)} at {o.price_c}c: {signed(o.pnl)}. Backup, not a stack.</li>
      ))}
      {g.mid && (
        <li className={g.mid.hit ? 'win' : 'loss'}><b>{g.mid.hit ? 'HIT' : 'MISS'}</b> Middle O{Number(g.mid.a_line)} at {g.mid.a_price}c + U{Number(g.mid.b_line)} at {g.mid.b_price}c, {g.mid.pairs} pairs: {signed(g.mid.pnl)}.{g.lead === 'mid' ? ' The play.' : ' Alternative to the single, not on top of it.'}</li>
      )}
      {g.rev && (
        <li className={g.rev.hole ? 'loss' : 'win'}><b>{g.rev.hole ? 'HOLE' : 'WIN'}</b> Reverse middle U{Number(g.rev.a_line)} at {g.rev.a_price}c + O{Number(g.rev.b_line)} at {g.rev.b_price}c, {g.rev.pairs} pairs: {signed(g.rev.pnl)}.{g.lead === 'rev' ? ' The play.' : ' Alternative to the above, not on top of it.'}</li>
      )}
      {g.rest && (
        <li className="alt"><b>what-if</b> Resting middle O{Number(g.rest.a_line)} at {g.rest.a_price}c + U{Number(g.rest.b_line)} at {g.rest.b_price}c: {g.rest.hit ? 'final inside the window' : 'missed'}, {signed(g.rest.pnl)} if both sides had filled.</li>
      )}
      {a.sheet?.rebuilt || (!a.sheet && g) ? <li className="alt note">Graded from the prices this push was priced at; the push itself was sent before sheets were kept.</li> : null}
    </ul>
  );
}

export default function Alerts() {
  const [alerts, setAlerts] = useState(null);
  const [finals, setFinals] = useState({});
  const [sugs, setSugs] = useState({});
  const [open, setOpen] = useState(null);
  const [only, setOnly] = useState('all');

  useEffect(() => {
    (async () => {
      const { data } = await supabase.from('alerts').select('*').order('sent_at', { ascending: false }).limit(120);
      const list = data || [];
      setAlerts(list);
      const ids = [...new Set(list.map((a) => a.game_id))];
      if (!ids.length) return;
      const [{ data: gs }, { data: ss }] = await Promise.all([
        supabase.from('games').select('id,away_abbr,home_abbr,final_away,final_home').in('id', ids),
        supabase.from('suggestions').select('game_id,taken_at,total,home_spread,half_away,half_home,fair_line,market_line,singles,mids')
          .in('game_id', list.filter((a) => !a.sheet).map((a) => a.game_id)),
      ]);
      const f = {};
      for (const g of gs || []) if (g.final_away !== null && g.final_away !== undefined) f[g.id] = { T: Number(g.final_away) + Number(g.final_home), text: `${g.away_abbr} ${g.final_away}, ${g.home_abbr} ${g.final_home}` };
      setFinals(f);
      const s = {};
      for (const x of ss || []) s[`${x.game_id}|${x.taken_at}`] = x;
      setSugs(s);
    })();
  }, []);

  if (alerts === null) return <main />;
  const shown = only === 'plays' ? alerts.filter((a) => a.kind === 'play') : alerts;
  const graded = shown.map((a) => {
    const final = finals[a.game_id];
    const sheet = a.sheet || sheetFromSuggestion(sugs[`${a.game_id}|${a.suggestion_at}`]);
    return { a, final, g: final && sheet ? gradeSheet(sheet, final.T) : null };
  });
  const plays = graded.filter((x) => x.a.kind === 'play' && x.g?.play);
  const wins = plays.filter((x) => x.g.play.win).length;
  const pnl = plays.reduce((s, x) => s + x.g.play.pnl, 0);
  return (
    <main>
      <header className="top">
        <h1>Alerts</h1>
        <div className="seg" role="tablist" aria-label="Which pushes">
          {[['all', 'All'], ['plays', 'Plays only']].map(([k, l]) => <button key={k} role="tab" aria-selected={only === k} className={only === k ? 'on' : ''} onClick={() => setOnly(k)}>{l}</button>)}
        </div>
        <p className="sub">
          {only === 'plays' ? 'Every PLAY the watcher pushed, newest first, each graded on what it led with.' : 'Every push the watcher sent, newest first.'}
          {plays.length ? <> Graded PLAY pushes here: <b className={pnl >= 0 ? 'pos' : 'neg'}>{wins}-{plays.length - wins}, {signed(pnl)}</b> at the sizes pushed.</> : null}
        </p>
      </header>
      {alerts.length === 0 && <p className="empty">No pushes yet. The first one goes out at the next half where the watcher finds a Kalshi total.</p>}
      {alerts.length > 0 && shown.length === 0 && <p className="empty">No PLAY pushes in the last {alerts.length}.</p>}
      <ul className="feed">
        {graded.map(({ a, g, final }) => (
          <li key={a.id} className={`alert ${a.kind} ${g?.play ? (g.play.win ? 'won' : 'lost') : ''}`}>
            <button onClick={() => setOpen(open === a.id ? null : a.id)} aria-expanded={open === a.id}>
              <span className="kind">{a.kind === 'play' ? 'PLAY' : 'UPDATE'}</span>
              <span className="title">{a.title.replace(/^(PLAY|UPDATE):\s*/, '')}</span>
              <span className="when">{etTime(a.sent_at)}, {ago(a.sent_at)}</span>
              <Grade a={a} g={g} final={final} />
            </button>
            {open === a.id && (
              <>
                <Detail a={a} g={g} final={final} />
                <pre>{a.body}</pre>
                <div className="actions">
                  {kalshiUrl(a.event_ticker) && !final && <a className="act primary" href={kalshiUrl(a.event_ticker)} target="_blank" rel="noopener">Open on Kalshi</a>}
                  <Link className="act" href={`/desk/?g=${a.game_id}`}>Open the desk</Link>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </main>
  );
}
