(() => {
  const ACTIONS_URL = 'https://github.com/stepoil-debug/douglas/actions/workflows/analyze-football.yml';
  const SECRETS_URL = 'https://github.com/stepoil-debug/douglas/settings/secrets/actions/new';
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const refreshBtn = $('refreshBtn');
  const runState = $('runState');
  const ticketList = $('ticketList');
  let currentStatus = null;
  let ticketData = [];

  function setRunState(text) { if (runState) runState.textContent = text; }

  function ensureManagementNav() {
    const nav = document.querySelector('.nav');
    if (!nav || nav.querySelector('[data-management-nav]')) return;
    const link = document.createElement('a');
    link.href = 'gestao.html';
    link.dataset.managementNav = '1';
    link.innerHTML = '📈 <span>Gestão simulada</span>';
    const second = nav.children[1];
    if (second) nav.insertBefore(link, second); else nav.appendChild(link);
  }

  function configureMainButton(state) {
    if (!analyzeBtn) return;
    if (state === 'WAITING_FOR_API_KEY') {
      analyzeBtn.textContent = '🔐 Configurar API';
      analyzeBtn.disabled = false;
      analyzeBtn.onclick = () => window.open(SECRETS_URL, '_blank', 'noopener,noreferrer');
      return;
    }
    analyzeBtn.textContent = state === 'RUNNING' ? '⏳ Analisando...' : state === 'SUCCESS' ? '▶ Rodar novamente' : '▶ Rodar agora';
    analyzeBtn.disabled = state === 'RUNNING';
    analyzeBtn.onclick = () => window.open(ACTIONS_URL, '_blank', 'noopener,noreferrer');
  }

  async function readRunStatus() {
    const response = await fetch(`./run_status.json?t=${Date.now()}`, { cache: 'no-store' });
    return response.ok ? response.json() : null;
  }

  async function readTickets() {
    const response = await fetch(`./data.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) return [];
    const data = await response.json();
    return data.tickets || data.approved || [];
  }

  function addResultStyles() {
    if (document.getElementById('resultBadgeStyles')) return;
    const style = document.createElement('style');
    style.id = 'resultBadgeStyles';
    style.textContent = `
      .settlement-badge{display:inline-flex;align-items:center;justify-content:center;margin:0 16px 12px;padding:8px 10px;border-radius:8px;font-size:10px;font-weight:950;letter-spacing:.05em;text-transform:uppercase}
      .settlement-green{color:#9aefbb;background:rgba(113,227,161,.09);border:1px solid rgba(113,227,161,.25)}
      .settlement-red{color:#ffadb3;background:rgba(255,123,132,.08);border:1px solid rgba(255,123,132,.24)}
      .settlement-pending{color:#ead38a;background:rgba(216,168,47,.08);border:1px solid rgba(216,168,47,.2)}
      .settlement-manual{color:#b8c7bd;background:rgba(129,154,137,.08);border:1px solid rgba(129,154,137,.2)}
    `;
    document.head.appendChild(style);
  }

  function updateResultBadge(card, ticket) {
    const raw = String(ticket.status || 'PENDING').toUpperCase();
    const label = raw === 'GREEN' ? '✓ GREEN' : raw === 'RED' ? '✕ RED' : raw === 'VOID' ? 'VOID' : raw === 'MANUAL' ? 'Conferência manual' : '⏳ Aguardando resultado';
    const kind = raw === 'GREEN' ? 'green' : raw === 'RED' ? 'red' : raw === 'MANUAL' || raw === 'VOID' ? 'manual' : 'pending';
    let badge = card.querySelector('.settlement-badge');
    if (!badge) {
      badge = document.createElement('div');
      const actions = card.querySelector('.ticket-actions-static');
      if (actions) card.insertBefore(badge, actions); else card.appendChild(badge);
    }
    badge.className = `settlement-badge settlement-${kind}`;
    badge.textContent = label;
  }

  function syncTicketBadges() {
    if (!ticketList || !ticketData.length) return;
    addResultStyles();
    const cards = Array.from(ticketList.querySelectorAll('.ticket'));
    cards.forEach(card => {
      const id = (card.querySelector('.ticket-id')?.textContent || '').trim();
      const ticket = ticketData.find(t => String(t.ticket_id || '').trim() === id);
      if (ticket) updateResultBadge(card, ticket);
    });
  }

  async function refreshTicketData() {
    try { ticketData = await readTickets(); syncTicketBadges(); } catch (_) {}
  }

  async function syncState() {
    try {
      const state = await readRunStatus();
      if (!state) return;
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
  if (ticketList) {
    const observer = new MutationObserver(syncTicketBadges);
    observer.observe(ticketList, { childList: true, subtree: true });
  }
  if (analyzeBtn) configureMainButton(null);
  if (refreshBtn) refreshBtn.onclick = () => location.reload();
  syncState();
  refreshTicketData();
  setInterval(syncState, 30000);
  setInterval(refreshTicketData, 30000);
})();
