(() => {
  const MIN_SCORE = 84;
  const ELITE_SCORE = 88;

  const esc = value => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

  function timeBR(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo',
      hour: '2-digit', minute: '2-digit', hour12: false
    }).format(d);
  }

  function odd(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 1 ? n.toFixed(2) : '—';
  }

  function pct(value) {
    const n = Number(value);
    return Number.isFinite(n) ? `${Math.round(n * 100)}%` : '—';
  }

  function betanoOdd(leg) {
    const quotes = leg?.bookmaker_quotes || {};
    for (const [name, value] of Object.entries(quotes)) {
      if (String(name).trim().toLowerCase() === 'betano') return value;
    }
    return leg?.odd;
  }

  function collect(data) {
    const byFixture = new Map();
    for (const match of data?.all_matches || []) {
      for (const leg of match?.eligible_legs || []) {
        const rawScore = Number(leg?.pre_guard_score ?? leg?.score ?? 0);
        if (!Number.isFinite(rawScore) || rawScore < MIN_SCORE) continue;
        const row = {
          ...leg,
          rawScore,
          match: leg.match || match.match || `${match.home_team || ''} x ${match.away_team || ''}`,
          league: leg.league || match.league || '—',
          kickoff_iso: leg.kickoff_iso || match.kickoff_iso,
          betano_odd: betanoOdd(leg)
        };
        const key = row.fixture_id ?? row.match;
        const current = byFixture.get(key);
        if (!current || row.rawScore > current.rawScore || (row.rawScore === current.rawScore && Number(row.model_probability || 0) > Number(current.model_probability || 0))) {
          byFixture.set(key, row);
        }
      }
    }
    return [...byFixture.values()].sort((a, b) =>
      b.rawScore - a.rawScore || Number(b.model_probability || 0) - Number(a.model_probability || 0)
    );
  }

  function ensureSection() {
    if (document.getElementById('strongCandidates')) return document.getElementById('strongCandidates');
    const games = document.getElementById('games');
    if (!games) return null;
    const section = document.createElement('section');
    section.className = 'section';
    section.id = 'strongCandidates';
    section.innerHTML = `
      <div class="head">
        <div><div class="eyebrow">Pré-seleção</div><h2>Candidatos fortes 84+</h2></div>
        <div class="sub" id="strongCandidateCount">score bruto individual mínimo 84</div>
      </div>
      <div class="card table-wrap">
        <table class="table">
          <thead><tr><th>Horário</th><th>Jogo</th><th>Liga</th><th>Mercado</th><th>Seleção</th><th>Odd Betano</th><th>Prob.</th><th>Score</th><th>Faixa</th></tr></thead>
          <tbody id="strongCandidateRows"><tr><td colspan="9">Carregando candidatos...</td></tr></tbody>
        </table>
      </div>`;
    games.parentNode.insertBefore(section, games);
    return section;
  }

  async function render() {
    const section = ensureSection();
    if (!section) return;
    try {
      const res = await fetch(`./data.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const rows = collect(data);
      const count = document.getElementById('strongCandidateCount');
      const body = document.getElementById('strongCandidateRows');
      if (count) count.textContent = `${rows.length} jogo(s) com seleção individual score ≥84`;
      if (!body) return;
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="9">Nenhuma seleção individual atingiu score 84 nesta análise. A lista geral permanece disponível abaixo para auditoria.</td></tr>';
        return;
      }
      body.innerHTML = rows.map(row => {
        const elite = row.rawScore >= ELITE_SCORE;
        return `<tr>
          <td><b>${esc(timeBR(row.kickoff_iso))}</b></td>
          <td><b>${esc(row.match)}</b></td>
          <td>${esc(row.league)}</td>
          <td>${esc(row.market || '—')}</td>
          <td>${esc(row.selection || '—')}</td>
          <td>${esc(odd(row.betano_odd))}</td>
          <td>${esc(pct(row.model_probability))}</td>
          <td><b class="${elite ? 'gold' : 'good'}">${row.rawScore.toFixed(1)}</b></td>
          <td><span class="tag ok">${elite ? 'ELITE 88+' : 'STRONG 84–87,9'}</span></td>
        </tr>`;
      }).join('');
    } catch (err) {
      console.error('Falha ao carregar candidatos fortes:', err);
      const body = document.getElementById('strongCandidateRows');
      if (body) body.innerHTML = '<tr><td colspan="9">Não foi possível carregar a pré-seleção.</td></tr>';
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render, { once: true });
  else render();
})();
