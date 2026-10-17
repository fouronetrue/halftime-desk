'use client';
import { useEffect, useMemo, useState } from 'react';
import { money, sizeMiddle } from '@/lib/desk';

// The two strikes on each side of the fair total, priced at what you type (prefilled with the watcher's asks),
// each pairing sized to the most shares that keep a miss under the loss cap.
export default function FairMiddle({ rows, fair, sport, maxCost, mids, takenAt, onPick }) {
  const [cap, setCap] = useState(15);
  const [px, setPx] = useState({});        // your typed prices, keyed 'o 58.5' / 'u 61.5'
  const [edited, setEdited] = useState(false);

  const strikes = rows.map((r) => Number(r.strike)).sort((a, b) => a - b);
  const below = strikes.filter((k) => k < fair).slice(-2).reverse();   // nearest first
  const above = strikes.filter((k) => k > fair).slice(0, 2);
  const row = (k) => rows.find((r) => Number(r.strike) === k);

  // a fresh watcher price resets the boxes unless you have typed over them
  useEffect(() => {
    if (edited) return;
    const next = {};
    for (const k of below) next[`o ${k}`] = row(k)?.yes_ask ?? '';
    for (const k of above) next[`u ${k}`] = row(k)?.no_ask ?? '';
    setPx(next);
  }, [takenAt, fair, strikes.join(',')]); // eslint-disable-line react-hooks/exhaustive-deps

  const reset = () => { setEdited(false); const next = {}; for (const k of below) next[`o ${k}`] = row(k)?.yes_ask ?? ''; for (const k of above) next[`u ${k}`] = row(k)?.no_ask ?? ''; setPx(next); };
  const set = (key, v) => { setEdited(true); setPx((p) => ({ ...p, [key]: v })); };
  const bump = (key, d) => set(key, String(Math.min(99, Math.max(1, (Number(px[key]) || 50) + d))));

  const pairs = useMemo(() => {
    const out = [];
    for (const lo of below) for (const hi of above) {
      const a = Number(px[`o ${lo}`]), b = Number(px[`u ${hi}`]);
      const o = row(lo), u = row(hi);
      if (!a || !b || !o || !u) continue;
      const known = (mids || []).find((x) => Number(x.a.line) === lo && Number(x.b.line) === hi);
      const pHit = known ? known.p_mid : Math.max(0, o.p_over - u.p_over - u.p_push);
      const r = sizeMiddle({ a, b, numbers: Math.round(hi - lo), sport, budget: Number(cap) || 0, maxCost, pHit });
      if (!r) continue;
      const band = [a, b].some((p) => p < 15 || p > 85);
      const ratio = r.lose < 0 ? r.win / -r.lose : Infinity;
      out.push({ lo, hi, a, b, band, ratio, pHit, ...r });
    }
    const good = (x) => x.verdict !== 'pass' && !x.band && x.pairs > 0;
    return out.sort((x, y) => (good(y) - good(x)) || (y.ratio - x.ratio));
  }, [px, cap, sport, maxCost, mids, rows]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!below.length || !above.length) return null;
  const best = pairs[0];
  const bestOk = best && best.verdict !== 'pass' && !best.band && best.pairs > 0;

  const box = (k, side) => {
    const key = `${side} ${k}`;
    return (
      <div className="fm-box" key={key}>
        <span>{side === 'o' ? 'Over' : 'Under'} {k}</span>
        <div className="mc-step">
          <button type="button" onClick={() => bump(key, -1)} aria-label={`${side === 'o' ? 'Over' : 'Under'} ${k} down a cent`}>&minus;</button>
          <input id={`fm-${side}-${k}`} aria-label={`${side === 'o' ? 'Over' : 'Under'} ${k} price in cents`} inputMode="numeric" value={px[key] ?? ''} onChange={(e) => set(key, e.target.value.replace(/[^0-9]/g, ''))} />
          <button type="button" onClick={() => bump(key, 1)} aria-label={`${side === 'o' ? 'Over' : 'Under'} ${k} up a cent`}>+</button>
        </div>
      </div>
    );
  };

  return (
    <section className="fairmid" aria-label="Fair middle">
      <div className="mhead">
        <h3>Around fair {fair}</h3>
        <span className="fm-cap">
          <label htmlFor="fm-cap">Max loss $</label>
          <input id="fm-cap" inputMode="decimal" value={cap} onChange={(e) => setCap(e.target.value.replace(/[^0-9.]/g, ''))} />
        </span>
      </div>
      <div className="fm-grid">
        <div className="fm-col"><b>Buy Yes below</b>{below.map((k) => box(k, 'o'))}</div>
        <div className="fm-col"><b>Buy No above</b>{above.map((k) => box(k, 'u'))}</div>
      </div>
      <p className="fm-src">{edited ? <>Your prices. <button type="button" className="link" onClick={reset}>Reset to watcher</button></> : 'Watcher asks, up to 15 seconds old. Type over any box with what Kalshi shows.'}</p>

      {best && (
        <button type="button" className={`fm-best ${bestOk ? best.verdict : 'pass'}`} onClick={() => onPick(best.lo, best.hi)}>
          <span className="fm-verdict">{bestOk ? (best.verdict === 'thin' ? 'Thin play' : 'Play') : 'Pass'}</span>
          <span className="fm-line">Yes {best.lo} at {best.a}c + No {best.hi} at {best.b}c</span>
          <span className="fm-shares">{best.pairs} <small>shares each side</small></span>
          <span className="fm-row"><span>${best.dollarsA.toFixed(2)} + ${best.dollarsB.toFixed(2)}</span><span className="neg">miss {money(best.lose)}</span><span className="pos">hit {money(best.win)}</span></span>
          <span className="fm-row"><span>{Number.isFinite(best.ratio) ? `${best.ratio.toFixed(1)} to 1` : 'Lock'}</span><span>hits {Math.round(100 * best.pHit)}%</span><span className={best.ev >= 0.03 ? 'pos' : 'neg'}>edge {money(best.pairs * best.ev)}</span></span>
        </button>
      )}
      {pairs.length > 1 && (
        <ul className="fm-alts">
          {pairs.slice(1).map((x) => {
            const ok = x.verdict !== 'pass' && !x.band && x.pairs > 0;
            return (
              <li key={`${x.lo}-${x.hi}`}>
                <button type="button" className={ok ? '' : 'pass'} onClick={() => onPick(x.lo, x.hi)}>
                  <span>o{x.lo} / u{x.hi}</span><span>{ok ? `${x.pairs} sh` : x.band ? 'band' : 'pass'}</span><span className="neg">{money(x.lose)}</span><span className="pos">{money(x.win)}</span><span>{Number.isFinite(x.ratio) ? `${x.ratio.toFixed(1)}:1` : 'lock'}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
