// Pure helpers shared by the screens. The pricing math mirrors engine.py so the Desk shows the same numbers
// the push did. Nothing in this app places, cancels or changes an order.

export const TZ = 'America/New_York';

export function etDate(d = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
}

export function etTime(iso) {
  if (!iso) return '';
  return new Intl.DateTimeFormat('en-US', { timeZone: TZ, hour: 'numeric', minute: '2-digit' }).format(new Date(iso));
}

export function etDay(d = new Date()) {
  return new Intl.DateTimeFormat('en-US', { timeZone: TZ, weekday: 'long', month: 'short', day: 'numeric' }).format(d);
}

export function ago(iso, now = Date.now()) {
  if (!iso) return null;
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

// Kalshi taker fee per contract at price p (dollars), and the rounded-up fee on n contracts: engine.fee_per / order_fee
export const feePer = (p) => 0.07 * p * (1 - p);
export const orderFee = (n, p) => Math.ceil(n * feePer(p) * 100 - 1e-9) / 100;

// Middle breakeven from the project rules: pair cost under 0.97 plus 3.5c per winning number (NFL), 2.4c (CFB), 2.9c (NBA)
export const perNumber = (sport) => (sport === 'nfl' ? 0.035 : sport === 'nba' ? 0.029 : 0.024);

export function phaseLabel(g) {
  switch (g.phase) {
    case 'half': return 'HALF';
    case 'early3': return 'Q3';
    case 'approaching': return 'Q2 late';
    case 'approaching3': return 'Q3 late';
    case 'q3end': return 'END 3RD';
    case 'early4': return 'Q4';
    case 'live': return g.detail || 'Live';
    case 'post': return 'Final';
    default: return etTime(g.start_utc);
  }
}

export const isHalfish = (g) => ['approaching', 'half', 'early3', 'approaching3', 'q3end', 'early4'].includes(g.phase);

// A suggestions row is priced off the halftime score. Once the games row shows a different live score, the
// row is stale: the watcher stops writing new rows at that moment, so the newest one is the last good one and
// this is what tells the screens not to show it as a bet (desk-issues-oct17 #3).
export function scoreMoved(g, sug) {
  if (!g || !sug || g.away_score === null || g.away_score === undefined || sug.half_away === null || sug.half_away === undefined) return false;
  return Number(g.away_score) !== Number(sug.half_away) || Number(g.home_score) !== Number(sug.half_home);
}

export function spreadText(g) {
  const s = g.pre_home_spread;
  if (s === null || s === undefined) return null;
  const v = Number(s);
  if (v === 0) return 'Pick';
  return v < 0 ? `${g.home_abbr} ${v}` : `${g.away_abbr} -${v}`;
}

// The Kalshi page for a totals event: kalshi.com/markets/<series>/event/<event ticker>, lower case. Opens the
// Kalshi app on a phone that has it. (Oct 23: the one-tap path from a push or a card to the market.)
export function kalshiUrl(eventTicker) {
  if (!eventTicker) return null;
  const t = String(eventTicker).toLowerCase();
  return `https://kalshi.com/markets/${t.split('-')[0]}/event/${t}`;
}

// How long a break lasts from the watcher's first look at it, by sport: the halftime window the push prices.
export const BREAK_MIN = { nfl: 13, cfb: 20, nba: 15 };

export function money(x) {
  const v = Number(x || 0);
  return `${v < 0 ? '-' : ''}$${Math.abs(v).toFixed(Math.abs(v) >= 100 ? 0 : 2)}`;
}

// Price a middle from two ladder rows, the way engine.suggest() sizes one. over = row bought YES, under = row bought NO.
export function middle(over, under, sport, sizing, pMidOverride) {
  if (!over || !under || !(under.strike > over.strike)) return null;
  const a = over.yes_ask, b = under.no_ask;
  if (!a || !b) return { missing: true };
  const pa = a / 100, pb = b / 100;
  const c = pa + feePer(pa) + pb + feePer(pb);              // all-in cost of one pair
  const numbers = Math.round(under.strike - over.strike);   // finals that win both legs
  const breakeven = 0.97 + perNumber(sport) * numbers;
  const pModel = Math.max(0, over.p_over - under.p_over - under.p_push);
  const pHit = pMidOverride ?? pModel;
  const loss = c - 1;
  const maxRisk = Number(sizing?.max_risk || 0), maxCost = Number(sizing?.max_cost || 0);
  const ok = 1 - c + pHit >= 0.03 - 1e-9;                  // the 3-cent margin, same gate as engine.suggest()
  let pairs = !ok ? 0 : loss > 0 ? Math.min(Math.floor(maxRisk / loss + 1e-9), Math.floor(maxCost / c + 1e-9)) : Math.floor(maxCost / c + 1e-9);
  pairs = Math.max(0, pairs);
  const cost = pairs ? Math.round((pairs * (pa + pb) + orderFee(pairs, pa) + orderFee(pairs, pb)) * 100) / 100 : 0;
  return {
    a, b, c, numbers, breakeven, pHit, pModel, pairs, cost,
    lo: over.strike + 0.5, hi: under.strike - 0.5,
    win: Math.round((2 * pairs - cost) * 100) / 100,
    lose: Math.round((pairs - cost) * 100) / 100,
    ev: 1 - c + pHit,
    under: c < breakeven,
    ok,
  };
}

// Price a reverse middle from two ladder rows, the way engine.suggest() scores one: under = the row bought NO
// (the lower strike), over = the row bought YES (the higher one). One leg pays on any final outside the hole
// between them, both lose inside it, so the edge a pair is 1 minus cost minus P(hole), the same numbers the
// middle wins on. Sized as one bet: quarter Kelly on the pair with the hole loss as the risk, under the single
// caps (max_risk, max_cost), never the middle's loss cap.
export function reverse(under, over, sport, sizing, pHoleOverride) {
  if (!under || !over || !(over.strike > under.strike)) return null;
  const a = under.no_ask, b = over.yes_ask;
  if (!a || !b) return { missing: true };
  const pa = a / 100, pb = b / 100;
  const c = pa + feePer(pa) + pb + feePer(pb);
  const numbers = Math.round(over.strike - under.strike);
  const pModel = Math.max(0, under.p_over - over.p_over - over.p_push);
  const pHole = pHoleOverride ?? pModel;
  const ev = 1 - c - pHole;
  const breakeven = 1 - pHole - 0.03;                     // the most a pair may cost, fees in, to clear the 3c margin
  const bankroll = Number(sizing?.bankroll || 0), maxRisk = Number(sizing?.max_risk || 0), maxCost = Number(sizing?.max_cost || 0);
  let pairs = 0;
  if (ev >= 0.03 - 1e-9 && c < 1) {
    const f = Math.max(0, 0.25 * ev / (1 - c));
    pairs = Math.min(Math.floor(Math.min(f * bankroll, maxRisk) / c + 1e-9), Math.floor(maxCost / c + 1e-9));
  }
  const ok = pairs >= 1;
  const cost = pairs ? Math.round((pairs * (pa + pb) + orderFee(pairs, pa) + orderFee(pairs, pb)) * 100) / 100 : 0;
  return {
    kind: 'rev', a, b, c, numbers, breakeven, pHole, pModel, pairs, cost, ev, ok,
    lo: under.strike + 0.5, hi: over.strike - 0.5,
    win: Math.round((pairs - cost) * 100) / 100,
    lose: Math.round(-cost * 100) / 100,
    under: c < breakeven,
  };
}

// The same reverse middle at a share count you pick: the win is one leg paid, the loss is the whole pair.
export function reverseAt(r, pairs) {
  const pa = r.a / 100, pb = r.b / 100;
  const n = Math.max(0, Math.floor(Number(pairs) || 0));
  const cost = n ? Math.round((n * (pa + pb) + orderFee(n, pa) + orderFee(n, pb)) * 100) / 100 : 0;
  return { pairs: n, cost, win: Math.round((n - cost) * 100) / 100, lose: Math.round(-cost * 100) / 100, dollarsA: Math.round(n * pa * 100) / 100, dollarsB: Math.round(n * pb * 100) / 100 };
}

export function seriesOf(eventTicker) {
  return (eventTicker || '').split('-')[0].toLowerCase();
}

const MONTHS = { JAN: 1, FEB: 2, MAR: 3, APR: 4, MAY: 5, JUN: 6, JUL: 7, AUG: 8, SEP: 9, OCT: 10, NOV: 11, DEC: 12 };

// What a Kalshi market ticker is, in words. KXNFLTOTAL-26OCT19WSHSF-45 with a positive position is
// "Over 44.5" on the WSH/SF total (the suffix is the strike rounded up; the market is over N minus a half).
// Spread tickers end in TEAM plus the whole-number spread; anything else (props) keeps its suffix as the name.
export function tickerInfo(ticker, position) {
  const m = /^(KX[A-Z]+)-(\d\d)([A-Z]{3})(\d\d)([A-Z0-9]+)-(.+)$/.exec(ticker || '');
  if (!m) return { what: ticker || '', game: '', sport: '', date: '' };
  const [, series, yy, mon, dd, teams, tail] = m;
  const sport = series.includes('NCAAF') ? 'cfb' : series.includes('NFL') ? 'nfl' : series.includes('NBA') ? 'nba' : '';
  const date = MONTHS[mon] ? `20${yy}-${String(MONTHS[mon]).padStart(2, '0')}-${dd}` : '';
  const yes = Number(position) >= 0;
  if (series.endsWith('TOTAL') && /^\d+$/.test(tail)) {
    return { what: `${yes ? 'Over' : 'Under'} ${Number(tail) - 0.5}`, game: `${teams} total`, sport, date, kind: 'total' };
  }
  const sp = /^([A-Z]+?)(\d+)$/.exec(tail);
  if (series.endsWith('SPREAD') && sp) {
    return { what: `${sp[1]} ${yes ? 'wins by over' : 'does not win by'} ${Number(sp[2]) - 0.5}`, game: `${teams} spread`, sport, date, kind: 'spread' };
  }
  return { what: `${yes ? 'Yes' : 'No'} ${tail}`, game: teams, sport, date, kind: 'other' };
}

// Size a middle from the prices you actually see, against a loss budget you pick. a, b in cents; fills 'take' or 'rest'.
// Taker fees use orderFee (rounded up per order); a resting fill pays none. budget and maxCost in dollars.
export function sizeMiddle({ a, b, oFill = 'take', uFill = 'take', numbers, sport, budget, maxCost, pHit }) {
  if (!(a > 0 && a < 100 && b > 0 && b < 100) || !(numbers >= 1)) return null;
  const pa = a / 100, pb = b / 100;
  const fa = oFill === 'take' ? feePer(pa) : 0, fb = uFill === 'take' ? feePer(pb) : 0;
  const c = pa + fa + pb + fb;                              // all-in cost of one pair, dollars
  const over = c - 1;                                       // lost per pair when the total misses the window
  const breakeven = 0.97 + perNumber(sport) * numbers;
  let pairs = over > 0 ? Math.floor(budget / over + 1e-9) : Math.floor(maxCost / c + 1e-9);
  let costCapped = over <= 0;
  if (maxCost > 0 && pairs * c > maxCost) { pairs = Math.floor(maxCost / c + 1e-9); costCapped = true; }
  pairs = Math.max(0, pairs);
  const costOf = (n) => Math.round((n * (pa + pb) + (oFill === 'take' ? orderFee(n, pa) : 0) + (uFill === 'take' ? orderFee(n, pb) : 0)) * 100) / 100;
  // fee rounding can push the real loss a cent past the budget: step down until it fits
  while (over > 0 && pairs > 0 && costOf(pairs) - pairs > budget + 1e-9) pairs -= 1;
  const feeA = oFill === 'take' ? orderFee(pairs, pa) : 0, feeB = uFill === 'take' ? orderFee(pairs, pb) : 0;
  const cost = costOf(pairs);
  return {
    c, over, breakeven, pairs, cost, costCapped,
    dollarsA: Math.round(pairs * pa * 100) / 100,
    dollarsB: Math.round(pairs * pb * 100) / 100,
    fees: Math.round((feeA + feeB) * 100) / 100,
    win: Math.round((2 * pairs - cost) * 100) / 100,
    lose: Math.round((pairs - cost) * 100) / 100,
    verdict: c >= breakeven ? 'pass' : c > breakeven - 0.03 ? 'thin' : 'play',
    // a free roll: the pair costs no more than it pays back on a miss, so no final loses
    free: over <= 0 && pairs > 0,
    // most the under can cost on screen once the over has filled at a, still inside the breakeven
    maxB: Math.floor(100 * (breakeven - pa - fa - (uFill === 'take' ? feePer(pb) : 0))),
    // most the under can cost for the pair to be a free roll (a miss pays for itself), fees in
    freeB: freeUnder(pa, fa, uFill),
    ev: pHit === undefined ? null : 1 - c + pHit,
  };
}

// Size the other side of a middle when one leg is already held (a pregame Sharp play, say): held = { side, paid (c),
// fill, dollars or shares }, other = { price (c), fill }. Two sizes, every fee in:
//   protect: the held leg's win pays for the new leg all in, so the held side winning alone nets about even (held.py);
//   even: as many shares as you hold, so a miss costs the same whichever side hits alone. That is the smallest worst
//   case any size can reach: fewer shares shrink one miss and grow the other, more than you hold is a naked bet.
// free: the pair costs under 100c all in, so up to the protect size no final loses; pick is protect then, even otherwise.
// The verdict scores the pair the way sizeMiddle does, with the held leg at the price it was paid. maxCost (the 7.5%
// cost cap) only flags here: trimming a hedge would raise the worst case, the opposite of what the cap is for.
export function sizeHeld({ held, other, numbers, sport, budget, maxCost }) {
  const pa = Number(held.paid) / 100, pb = Number(other.price) / 100;
  if (!(pa > 0 && pa < 1 && pb > 0 && pb < 1) || !(numbers >= 1)) return null;
  const nA = held.shares !== undefined && held.shares !== '' ? Math.floor(Number(held.shares)) : Math.floor(Number(held.dollars || 0) / pa + 1e-9);
  if (!(nA >= 1)) return null;
  const feeA = held.fill === 'take' ? orderFee(nA, pa) : 0;
  const costA = Math.round((nA * pa + feeA) * 100) / 100;
  const win = nA * (1 - pa) - feeA;                                    // the held leg's net if it wins, before any hedge
  const fb = other.fill === 'take' ? feePer(pb) : 0;
  const feeB = (n) => (other.fill === 'take' ? orderFee(n, pb) : 0);
  const at = (n) => ({
    n, dollars: Math.round(n * pb * 100) / 100, fee: feeB(n),
    heldAlone: Math.round((win - n * pb - feeB(n)) * 100) / 100,
    both: Math.round((win + n * (1 - pb) - feeB(n)) * 100) / 100,
    otherAlone: Math.round((n * (1 - pb) - feeB(n) - costA) * 100) / 100,
  });
  let nP = Math.floor(win / (pb + fb) + 1e-9);
  while (nP > 0 && nP * pb + feeB(nP) > win + 1e-9) nP -= 1;
  const protect = at(Math.max(0, nP));
  const even = at(nA);
  const c = pa + (held.fill === 'take' ? feePer(pa) : 0) + pb + fb;   // all-in cost of one pair, the held leg at its price
  const breakeven = 0.97 + perNumber(sport) * numbers;
  const free = protect.n >= 1 && protect.heldAlone >= -1e-9 && protect.otherAlone >= -1e-9;
  const pick = free ? protect : even;
  const overCap = maxCost > 0 && costA + pick.dollars + pick.fee > maxCost + 1e-9;
  // the most the other side can cost for a free roll, and to stay inside breakeven, both with its fee in
  let freeC = 0, maxC = 0;
  for (let cc = 99; cc >= 1; cc--) {
    const q = cc / 100, all = pa + (held.fill === 'take' ? feePer(pa) : 0) + q + (other.fill === 'take' ? feePer(q) : 0);
    if (!maxC && all <= breakeven + 1e-9) maxC = cc;
    if (all <= 1 + 1e-9) { freeC = cc; break; }
  }
  return {
    nA, costA, feeA, win: Math.round(win * 100) / 100, protect, even, pick, c, breakeven, free, freeC, maxC, overCap,
    verdict: c >= breakeven ? 'pass' : c > breakeven - 0.03 ? 'thin' : 'play',
    // the even miss is the floor on the worst case; over the loss budget means no size gets inside it
    overBudget: !free && Number(budget) > 0 && even.heldAlone < -Number(budget) - 1e-9,
  };
}

// Both legs held: the three finals on what is in, fees in, and the pair scored at the prices paid (verdict and
// free the way sizeMiddle scores them). add = { price (c), fill } sizes the top-up that evens the two legs: as
// many shares of the lighter side as it is short, so a miss costs the same whichever side hits alone.
export function heldOutcomes({ over, under, numbers, sport, add }) {
  const pa = Number(over.paid) / 100, pb = Number(under.paid) / 100;
  const nA = over.shares !== undefined && over.shares !== '' ? Math.floor(Number(over.shares)) : Math.floor(Number(over.dollars || 0) / pa + 1e-9);
  const nB = under.shares !== undefined && under.shares !== '' ? Math.floor(Number(under.shares)) : Math.floor(Number(under.dollars || 0) / pb + 1e-9);
  if (!(pa > 0 && pa < 1 && pb > 0 && pb < 1) || !(nA >= 1 && nB >= 1)) return null;
  const feeA = over.fill === 'take' ? orderFee(nA, pa) : 0, feeB = under.fill === 'take' ? orderFee(nB, pb) : 0;
  const costA = nA * pa + feeA, costB = nB * pb + feeB;
  const r = (x) => Math.round(x * 100) / 100;
  const c = pa + (over.fill === 'take' ? feePer(pa) : 0) + pb + (under.fill === 'take' ? feePer(pb) : 0);
  const breakeven = numbers >= 1 ? 0.97 + perNumber(sport) * numbers : null;
  const out = { nA, nB, costA: r(costA), costB: r(costB), overAlone: r(nA - costA - costB), both: r(nA + nB - costA - costB), underAlone: r(nB - costA - costB),
                c, breakeven, free: c <= 1 + 1e-9, verdict: breakeven === null ? null : c >= breakeven ? 'pass' : c > breakeven - 0.03 ? 'thin' : 'play', even: null };
  if (nA !== nB) {
    const side = nA > nB ? 'under' : 'over', m = Math.abs(nA - nB);
    const q = Number(add?.price ?? (side === 'under' ? under.paid : over.paid)) / 100;
    if (q > 0 && q < 1) {
      const fee = (add?.fill ?? 'take') === 'take' ? orderFee(m, q) : 0, costX = m * q + fee;
      const all = costA + costB + costX, hi = Math.max(nA, nB);
      out.even = { side, n: m, price: Math.round(q * 100), dollars: r(m * q), fee: r(fee), miss: r(hi - all), both: r(nA + nB + m - all) };
    }
  }
  return out;
}


// The highest under price, in cents, at which over at pa (fee fa paid) plus the under costs no more than 100c
// all in, so a miss either way loses nothing. 0 when no price under 100c does it.
export function freeUnder(pa, fa, uFill = 'take') {
  for (let c = 99; c >= 1; c--) {
    const pb = c / 100;
    if (pa + fa + pb + (uFill === 'take' ? feePer(pb) : 0) <= 1 + 1e-9) return c;
  }
  return 0;
}

// Height of the app shell. iOS lays a home-screen web app out short by the status bar: innerHeight, 100dvh and the
// visual viewport all read screen minus status bar while the web view fills the screen, and 100lvh alone reads the
// full height (a 16 Pro Max: 894 against 956). The difference is added back in the home-screen app only; a
// browser tab (toolbars come and go, the visual viewport is right) and Android are left alone. vis is the visual
// viewport height, which shrinks under the keyboard, so the shell follows the keyboard either way.
export function shellHeight({ vis, inner, large, standalone }) {
  let delta = 0;
  if (standalone && large > inner) {
    const d = large - inner;
    if (d <= 120) delta = d;   // status bar sized; anything bigger is something else, leave it
  }
  return Math.round(vis + delta);
}

// Grade a push's sheet against the final total, the same rule as watch.py grade_sheet(): the play is what the
// push led with (the first single, or the middle when the push led with one), the other singles are backups
// (one or the other, never a stack), the middle is also graded on its own, and a read's resting middle is a
// what-if only. Every screen uses this so Alerts, Record and the results table agree.
export function gradeSheet(sh, T) {
  if (!sh || T === null || T === undefined) return null;
  const singles = sh.singles || [];
  const lead = sh.lead || (singles.length ? 'single' : sh.mid ? 'mid' : 'rest');
  const options = singles.map((x, i) => {
    const win = x.kind === 'over' ? T > Number(x.line) : T < Number(x.line);
    const pnl = Math.round((win ? Number(x.contracts) - Number(x.cost) : -Number(x.cost)) * 100) / 100;
    return { ...x, win, pnl, play: i === 0 && lead === 'single' };
  });
  let mid = null;
  if (sh.mid) {
    const m = sh.mid, hit = Number(m.a_line) < T && T < Number(m.b_line);
    mid = { ...m, hit, pnl: Math.round((hit ? 2 * m.pairs - m.cost : m.pairs - m.cost) * 100) / 100 };
  }
  // the reverse middle: one leg pays on any final outside the hole (a_line is the under's strike, b_line the over's), both lose inside it
  let rev = null;
  if (sh.rev) {
    const m = sh.rev, hole = Number(m.a_line) < T && T < Number(m.b_line);
    rev = { ...m, hole, pnl: Math.round((hole ? -m.cost : m.pairs - m.cost) * 100) / 100 };
  }
  let rest = null;
  if (sh.rest_mid) {
    const m = sh.rest_mid, hit = Number(m.a_line) < T && T < Number(m.b_line);
    rest = { ...m, hit, pnl: Math.round((hit ? 2 * m.pairs - m.cost : m.pairs - m.cost) * 100) / 100 };
  }
  let play = null;
  if (lead === 'mid' && mid) play = { what: `Middle O${Number(mid.a_line)} at ${mid.a_price}c + U${Number(mid.b_line)} at ${mid.b_price}c, ${mid.pairs} pairs`, win: mid.hit, pnl: mid.pnl, cost: mid.cost, label: mid.hit ? 'HIT' : 'MISS' };
  else if (lead === 'single' && options.length) {
    const o = options[0];
    play = { what: `${o.kind === 'over' ? 'Over' : 'Under'} ${Number(o.line)} at ${o.price_c}c, ${o.contracts} shares`, win: o.win, pnl: o.pnl, cost: o.cost, label: o.win ? 'WIN' : 'LOSS' };
  } else if (lead === 'rev' && rev) play = { what: `Reverse middle U${Number(rev.a_line)} at ${rev.a_price}c + O${Number(rev.b_line)} at ${rev.b_price}c, ${rev.pairs} pairs`, win: !rev.hole, pnl: rev.pnl, cost: rev.cost, label: rev.hole ? 'HOLE' : 'WIN' };
  return { lead, play, options, mid, rev, rest, T };
}

// The plays a push named, for an alert sent before sheets were kept: the first three cleared singles (one per
// line, best first) and the best cleared middle from its suggestions row. Mirrors engine.chosen().
export function sheetFromSuggestion(s) {
  if (!s) return null;
  const seen = new Set(), singles = [];
  for (const x of (s.singles || []).filter((x) => x.ok)) {
    if (seen.has(Number(x.line))) continue;
    seen.add(Number(x.line)); singles.push(x);
    if (singles.length >= 3) break;
  }
  const m = (s.mids || []).find((x) => x.ok);
  return {
    rebuilt: true, lead: singles.length ? 'single' : m ? 'mid' : 'rest',
    total: s.total, spread: s.home_spread, h1a: s.half_away, h1h: s.half_home, fair: s.fair_line, mkt: s.market_line,
    singles: singles.map((x) => ({ kind: x.kind, line: x.line, price_c: x.price_c, contracts: x.contracts, cost: x.cost })),
    mid: m ? { a_line: m.a.line, a_price: m.a.price_c, b_line: m.b.line, b_price: m.b.price_c, pairs: m.pairs, cost: m.cost } : null,
    rest_mid: null,
  };
}
