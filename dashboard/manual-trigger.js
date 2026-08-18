(() => {
  const ACTIONS_URL = 'https://github.com/stepoil-debug/douglas/actions/workflows/analyze-football.yml';
  const SECRETS_URL = 'https://github.com/stepoil-debug/douglas/settings/secrets/actions/new';
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const refreshBtn = $('refreshBtn');
  const runState = $('runState');
  const ticketList = $('ticketList');
  let currentStatus = null;

  function setRunState(text) {
    if (runState && runState.textContent !== text) runState.textContent = text;
  }

  function ensureManagementNav() {
    const nav = document.querySelector('.nav');
    if (!nav || nav.querySelector('[data-management-nav]')) return;
    const link = document.createElement('a');
    link.href = 'gestao.html';
    link.dataset.managementNav = '1';
    link.innerHTML = '📈 <span>Gestão simulada</span>';
    const second = nav.children[1];
    if (second) nav.insertBefore(link, second);
    else nav.appendChild(link);
  }

  function configureMainButton(state) {
    if (!analyzeBtn) return;
    if (state === 'WAITING_FOR_API_KEY') {
      analyzeBtn.textContent = '🔐 Configurar API';
      analyzeBtn.disabled = false;
      analyzeBtn.onclick = () => window.open(SECRETS_URL, '_blank', 'noopener,noreferrer');
      return;
    }
    const nextText = state === 'RUNNING'
      ? '⏳ Analisando...'
      : state === 'SUCCESS'
        ? '▶ Rodar novamente'
        : '▶ Rodar agora';
    if (analyzeBtn.textContent !== nextText) analyzeBtn.textContent = nextText;
    analyzeBtn.disabled = state === 'RUNNING';
    analyzeBtn.onclick = () => window.open(ACTIONS_URL, '_blank', 'noopener,noreferrer');
  }

  function formatTime(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '—';
    return new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }).format(date);
  }

  function estimatedResultTime(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '—';
    // Futebol normalmente encerra em cerca de 2h; usamos +2h15 para absorver
    // intervalo, acréscimos e pequeno atraso na atualização oficial da API.
    date.setMinutes(date.getMinutes() + 135);
    return new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }).format(date);
  }

  function addScheduleStyles() {
    if (document.getElementById('scheduleStyles')) return;
    const style = document.createElement('style');
    style.id = 'scheduleStyles';
    style.textContent = `
      .leg-time{display:flex;align-items:center;gap:7px;margin:0 0 7px;color:#f2cc62;font-size:10px;font-weight:900}
      .leg-time .result-at{color:#86a28f;font-weight:750}
      .ticket-schedule{margin:0 16px 12px;padding:10px 11px;border:1px solid rgba(115,183,255,.17);background:rgba(30,73,112,.08);border-radius:8px;color:#9ab5a3;font-size:10px;line-height:1.5}
      .ticket-schedule b{color:#dce9df}
      .ticket-schedule .settle{color:#f2cc62;font-weight:900}
      .ticket-result-badge{display:inline-flex;margin:0 16px 10px;padding:7px 9px;border-radius:7px;font-size:9px;font-weight:950;letter-spacing:.04em;text-transform:uppercase}
      .ticket-result-badge.pending{color:#ead38a;border:1px solid rgba(216,168,47,.2);background:rgba(216,168,47,.07)}
      .ticket-result-badge.green{color:#9aefbb;border:1px solid rgba(113,227,161,.25);background:rgba(113,227,161,.08)}
      .ticket-result-badge.red{color:#ffadb3;border:1px solid rgba(255,123,132,.24);background:rgba(255,123,132,.07)}
    `;
    document.head.appendChild(style);
  }

  function statusBadge(ticket) {
    const raw = String(ticket?.status || 'PENDING').toUpperCase();
    if (raw === 'GREEN' || raw === 'HIT') return { cls: 'green', text: '✓ GREEN' };
    if (raw === 'RED' || raw === 'MISS') return { cls: 'red', text: '✕ RED' };
    return { cls: 'pending', text: '⏳ Aguardando resultado' };
  }

  async function enhanceTicketTimes() {
    if (!ticketList) return;
    try {
      const response = await fetch(`./data.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) return;
      const data = await response.json();
      const tickets = data.tickets || data.approved || [];
      if (!tickets.length) return;
      addScheduleStyles();

      const cards = Array.from(ticketList.querySelectorAll('.ticket'));
      cards.forEach(card => {
        const id = (card.querySelector('.ticket-id')?.textContent || '').trim();
        const ticket = tickets.find(t => String(t.ticket_id || '').trim() === id);
        if (!ticket) return;
        const legs = Array.isArray(ticket.legs) ? ticket.legs : [];
        const legNodes = Array.from(card.querySelectorAll('.leg'));

        legNodes.forEach((node, index) => {
          const leg = legs[index];
          if (!leg?.kickoff_iso) return;
          let time = node.querySelector('.leg-time');
          if (!time) {
            time = document.createElement('div');
            time.className = 'leg-time';
            node.insertBefore(time, node.firstChild);
          }
          time.innerHTML = `🕒 Início ${formatTime(leg.kickoff_iso)} <span class="result-at">• resultado ~${estimatedResultTime(leg.kickoff_iso)}</span>`;
        });

        const validKickoffs = legs
          .map(leg => leg?.kickoff_iso ? new Date(leg.kickoff_iso) : null)
          .filter(date => date && !Number.isNaN(date.getTime()));
        const lastGame = validKickoffs.length
          ? new Date(Math.max(...validKickoffs.map(date => date.getTime())))
          : null;

        let summary = card.querySelector('.ticket-schedule');
        if (!summary) {
          summary = document.createElement('div');
          summary.className = 'ticket-schedule';
          const actions = card.querySelector('.ticket-actions-static');
          if (actions) card.insertBefore(summary, actions);
          else card.appendChild(summary);
        }
        if (lastGame) {
          const lastIso = lastGame.toISOString();
          summary.innerHTML = `<b>⏱ Fechamento do bilhete</b><br>Último jogo começa às <b>${formatTime(lastIso)}</b> • resultado completo esperado por volta de <span class="settle">${estimatedResultTime(lastIso)}</span> (Brasília)`;
        } else {
          summary.textContent = 'Horário dos jogos indisponível para este bilhete.';
        }

        const badgeState = statusBadge(ticket);
        let badge = card.querySelector('.ticket-result-badge');
        if (!badge) {
          badge = document.createElement('div');
          badge.className = 'ticket-result-badge';
          card.insertBefore(badge, summary);
        }
        badge.className = `ticket-result-badge ${badgeState.cls}`;
        badge.textContent = badgeState.text;
      });
    } catch (_) {}
  }

  async function syncState() {
    try {
      const response = await fetch(`./run_status.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) return;
      const state = await response.json();
      currentStatus = state.status || null;
      configureMainButton(currentStatus);
      if (currentStatus === 'RUNNING') setRunState('Analisando jogos de hoje...');
      else if (currentStatus === 'SUCCESS') setRunState(`API ativa • ${Number(state.tickets_ready || 0)}/3 bilhetes oficiais`);
      else if (currentStatus === 'WAITING_FOR_API_KEY') setRunState('Falta configurar a API no GitHub');
      else if (currentStatus === 'FAILED') setRunState('Última análise falhou • ver Actions');
      else setRunState('Motor GitHub ativo');
    } catch (_) {
      setRunState('Motor GitHub ativo');
      configureMainButton(currentStatus);
    }
  }

  ensureManagementNav();
  if (analyzeBtn) configureMainButton(null);
  if (refreshBtn) refreshBtn.onclick = () => location.reload();

  // Sem MutationObserver. Apenas leituras leves em intervalos espaçados.
  syncState();
  setTimeout(enhanceTicketTimes, 600);
  setTimeout(enhanceTicketTimes, 1800);
  setInterval(syncState, 120000);
  setInterval(enhanceTicketTimes, 120000);
})();
