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

// Middle breakeven from the project rules: pair cost under 0.97 plus 3.5c per winning number (NFL), 2.4c (CFB)
export const perNumber = (sport) => (sport === 'nfl' ? 0.035 : 0.024);

export function phaseLabel(g) {
  switch (g.phase) {
    case 'half': return 'HALF';
    case 'early3': return 'Q3';
    case 'approaching': return 'Q2 late';
    case 'live': return g.detail || 'Live';
    case 'post': return 'Final';
    default: return etTime(g.start_utc);
  }
}

export const isHalfish = (g) => ['approaching', 'half', 'early3'].includes(g.phase);

export function spreadText(g) {
  const s = g.pre_home_spread;
  if (s === null || s === undefined) return null;
  const v = Number(s);
  if (v === 0) return 'Pick';
  return v < 0 ? `${g.home_abbr} ${v}` : `${g.away_abbr} -${v}`;
}

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

export function seriesOf(eventTicker) {
  return (eventTicker || '').split('-')[0].toLowerCase();
}
