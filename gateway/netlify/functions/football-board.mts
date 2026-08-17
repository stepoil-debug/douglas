const API_BASE = 'https://v3.football.api-sports.io';
const TIMEZONE = 'America/Sao_Paulo';
const MAX_ODDS_PAGES = 6;
const MAX_ENRICHED = 18;

const headers = {
  'Content-Type': 'application/json; charset=utf-8',
  'Cache-Control': 'public, max-age=60, s-maxage=5400, stale-while-revalidate=600',
  'Netlify-CDN-Cache-Control': 'public, s-maxage=5400, stale-while-revalidate=600',
  'Access-Control-Allow-Origin': 'https://stepoil-debug.github.io',
  'X-Content-Type-Options': 'nosniff'
};
const noStore = { ...headers, 'Cache-Control': 'no-store, max-age=0', 'Netlify-CDN-Cache-Control': 'no-store' };
const PRIORITY_COUNTRIES = new Set(['England','Spain','Italy','Germany','France','Portugal','Netherlands','Belgium','Brazil','Argentina','USA','Mexico','Turkey','Greece','Scotland','Switzerland','Austria','Denmark','Norway','Sweden']);
const PRIORITY_TERMS = ['premier league','la liga','serie a','bundesliga','ligue 1','primeira liga','eredivisie','champions league','europa league','conference league','copa','brasileirao','brasileirão','paulista','carioca','mls','liga profesional','super lig'];

function env(name: string) {
  return String((globalThis as any).Netlify?.env?.get?.(name) || process.env[name] || '').trim();
}
function json(body: Record<string, unknown>, status = 200, h = headers) { return Response.json(body, { status, headers: h }); }
function validDate(v: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
  const d = new Date(`${v}T12:00:00Z`);
  return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === v;
}
function fixtureId(row: any) { return Number(row?.fixture?.id || 0); }
function prematch(row: any) { return ['NS','TBD'].includes(String(row?.fixture?.status?.short || '')); }
function leaguePriority(row: any) {
  const league = row?.league || {};
  const name = String(league.name || '').toLowerCase();
  const country = String(league.country || '');
  let score = 0;
  if (PRIORITY_COUNTRIES.has(country)) score += 2;
  if (PRIORITY_TERMS.some((term) => name.includes(term))) score += 3;
  if (String(league.type || '').toLowerCase() === 'league') score += 1;
  return score;
}
function prices(row: any) {
  const best: Record<string, number | null> = { home: null, draw: null, away: null };
  for (const bookmaker of row?.bookmakers || []) for (const bet of bookmaker.bets || []) {
    if (!['match winner','1x2','winner'].includes(String(bet.name || '').trim().toLowerCase())) continue;
    for (const item of bet.values || []) {
      const odd = Number(item.odd); if (!Number.isFinite(odd) || odd <= 1) continue;
      const label = String(item.value || '').trim().toLowerCase();
      const side = label === 'home' || label === '1' ? 'home' : label === 'draw' || label === 'x' ? 'draw' : label === 'away' || label === '2' ? 'away' : '';
      if (side && (best[side] === null || odd > Number(best[side]))) best[side] = odd;
    }
  }
  return best;
}
function quality(fixture: any, odds: any) {
  const p = prices(odds);
  const favorite = Math.min(p.home || 99, p.away || 99);
  let score = leaguePriority(fixture) * 10;
  if (favorite >= 1.5 && favorite <= 2.0) score += 40;
  else if (favorite >= 1.4 && favorite <= 2.2) score += 20;
  if (p.draw && p.draw >= 3) score += 4;
  return score;
}
async function apiGet(key: string, endpoint: string, params: Record<string, string | number>) {
  const qs = new URLSearchParams(); Object.entries(params).forEach(([k,v]) => qs.set(k, String(v)));
  const res = await fetch(`${API_BASE}${endpoint}?${qs}`, { headers: { 'x-apisports-key': key, Accept: 'application/json', 'User-Agent': 'InvestBet-Football-Gateway/1.0' }, signal: AbortSignal.timeout(12000) });
  const body: any = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`API-Football HTTP ${res.status}`);
  if (body?.errors && Object.keys(body.errors).length) throw new Error(`API-Football: ${JSON.stringify(body.errors)}`);
  return body;
}
async function oddsForDate(key: string, date: string) {
  const first = await apiGet(key, '/odds', { date, bet: 1, page: 1 });
  const rows: any[] = [...(first.response || [])];
  const total = Math.max(1, Number(first?.paging?.total || 1));
  const count = Math.min(total, MAX_ODDS_PAGES);
  if (count > 1) {
    const rest = await Promise.all(Array.from({ length: count - 1 }, (_, i) => apiGet(key, '/odds', { date, bet: 1, page: i + 2 })));
    rest.forEach((p) => rows.push(...(p.response || [])));
  }
  return { rows, total, count };
}
async function predictions(key: string, ids: number[]) {
  const map = new Map<number, any>();
  for (let i = 0; i < ids.length; i += 6) {
    const batch = await Promise.all(ids.slice(i, i + 6).map(async (id) => {
      try { const p = await apiGet(key, '/predictions', { fixture: id }); return [id, (p.response || [])[0] || null] as const; }
      catch { return [id, null] as const; }
    }));
    batch.forEach(([id,p]) => map.set(id,p));
  }
  return map;
}

export default async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers });
  if (req.method !== 'GET') return json({ error: 'Method not allowed' }, 405, noStore);
  const url = new URL(req.url);
  const date = String(url.searchParams.get('date') || '').trim();
  if (!validDate(date)) return json({ error: 'Informe date no formato YYYY-MM-DD.' }, 400, noStore);
  const key = env('API_FOOTBALL_KEY');
  if (!key) return json({ error: 'API-Football não configurada no servidor.', configured: false }, 503, noStore);
  try {
    const fixturesPayload = await apiGet(key, '/fixtures', { date, timezone: TIMEZONE });
    const fixtures: any[] = (fixturesPayload.response || []).filter(prematch);
    const oddsBundle = await oddsForDate(key, date);
    const oddsById = new Map<number, any>();
    oddsBundle.rows.forEach((row) => { const id = fixtureId(row); if (id) oddsById.set(id,row); });
    const candidates = fixtures.filter((row) => oddsById.has(fixtureId(row))).sort((a,b) => quality(b, oddsById.get(fixtureId(b))) - quality(a, oddsById.get(fixtureId(a))) || leaguePriority(b) - leaguePriority(a) || String(a?.fixture?.date || '').localeCompare(String(b?.fixture?.date || ''))).slice(0, MAX_ENRICHED);
    const pred = await predictions(key, candidates.map(fixtureId).filter(Boolean));
    const enriched = candidates.map((fixture) => { const id = fixtureId(fixture); const odds = oddsById.get(id); return { fixture, odds: odds ? [odds] : [], prediction: pred.get(id) || null }; });
    return json({ ok: true, sport: 'football', provider: 'API-Football', date, timezone: TIMEZONE, fetched_at: new Date().toISOString(), fixtures, enriched, meta: { fixtures_found: fixtures.length, odds_rows: oddsBundle.rows.length, odds_pages_fetched: oddsBundle.count, odds_pages_available: oddsBundle.total, enriched_candidates: enriched.length, max_enriched: MAX_ENRICHED } });
  } catch (error) {
    const detail = error instanceof Error ? error.message : 'Falha desconhecida';
    console.error('[football-board]', detail);
    return json({ error: 'Falha ao consultar dados de futebol.', detail, configured: true }, 502, noStore);
  }
};

export const config = { path: '/api/football-board' };
