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

  function fmtOdd(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) && n > 0 ? n.toFixed(2).replace('.', ',') : '—';
  }

  function ticketText(ticket) {
    const legs = Array.isArray(ticket.legs) ? ticket.legs : [];
    const total = Number(ticket.total_odd || legs.reduce((a, l) => a * Number(l.odd || 1), 1));
    const lines = [
      `INVESTBET • ${ticket.ticket_id || 'BILHETE'} • ${ticket.profile || 'SELETIVO'}`,
      `Odd total: ${fmtOdd(total)}`,
      ''
    ];
    legs.forEach((leg, index) => {
      lines.push(`${index + 1}. ${leg.match}`);
      lines.push(`   ${leg.market}: ${leg.selection}`);
      lines.push(`   Odd: ${fmtOdd(leg.odd)}`);
    });
    lines.push('', 'Ambiente de teste • nenhuma aposta real é enviada.');
    return lines.join('\n');
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (_) {
      const area = document.createElement('textarea'); area.value = text;
      area.style.position = 'fixed'; area.style.opacity = '0'; document.body.appendChild(area);
      area.focus(); area.select(); let ok = false;
      try { ok = document.execCommand('copy'); } catch (_) {}
      area.remove(); return ok;
    }
  }

  function addStyles() {
    if (document.getElementById('executorStyles')) return;
    const style = document.createElement('style');
    style.id = 'executorStyles';
    style.textContent = `
      .execution-box{margin:0 16px 16px;padding:12px;border:1px solid rgba(242,204,98,.22);background:linear-gradient(135deg,rgba(216,168,47,.09),rgba(7,24,15,.92));border-radius:10px}
      .execution-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}.execution-title{font-size:10px;font-weight:950;text-transform:uppercase;letter-spacing:.08em;color:#f2cc62}.execution-house{font-size:10px;color:#9aefbb;font-weight:900}
      .execution-summary{font-size:10px;color:#829989;line-height:1.5;margin-bottom:10px}.execution-summary b{color:#f4f0e4}.execution-actions{display:grid;grid-template-columns:1fr auto;gap:8px}
      .execution-open,.execution-copy{border-radius:9px;padding:10px 12px;font-size:11px;font-weight:950;cursor:pointer;border:1px solid}.execution-open{background:linear-gradient(135deg,#f0ca60,#c8921b);color:#1c1605;border-color:#d1a12c}.execution-copy{background:#091911;color:#d9e4dc;border-color:#294735}
      .execution-open:disabled,.execution-copy:disabled{opacity:.45;cursor:not-allowed}.settlement-badge{display:inline-flex;align-items:center;justify-content:center;margin:0 16px 12px;padding:8px 10px;border-radius:8px;font-size:10px;font-weight:950;letter-spacing:.05em;text-transform:uppercase}
      .settlement-green{color:#9aefbb;background:rgba(113,227,161,.09);border:1px solid rgba(113,227,161,.25)}.settlement-red{color:#ffadb3;background:rgba(255,123,132,.08);border:1px solid rgba(255,123,132,.24)}.settlement-pending{color:#ead38a;background:rgba(216,168,47,.08);border:1px solid rgba(216,168,47,.2)}.settlement-manual{color:#b8c7bd;background:rgba(129,154,137,.08);border:1px solid rgba(129,154,137,.2)}
      @media(max-width:720px){.execution-actions{grid-template-columns:1fr}.execution-copy{width:100%}}
    `;
    document.head.appendChild(style);
  }

  function updateResultBadge(card, ticket) {
    const raw = String(ticket.status || 'PENDING').toUpperCase();
    const label = raw === 'GREEN' ? '✓ GREEN' : raw === 'RED' ? '✕ RED' : raw === 'VOID' ? 'VOID' : raw === 'MANUAL' ? 'Conferência manual' : '⏳ Aguardando resultado';
    const kind = raw === 'GREEN' ? 'green' : raw === 'RED' ? 'red' : raw === 'MANUAL' || raw === 'VOID' ? 'manual' : 'pending';
    let badge = card.querySelector('.settlement-badge');
    if (!badge) { badge = document.createElement('div'); card.appendChild(badge); }
    badge.className = `settlement-badge settlement-${kind}`; badge.textContent = label;
    const settled = ['GREEN','RED','VOID'].includes(raw);
    card.querySelectorAll('.execution-open,.execution-copy').forEach(btn => btn.disabled = settled);
  }

  function enhanceTickets() {
    if (!ticketList || !ticketData.length) return;
    addStyles();
    const cards = Array.from(ticketList.querySelectorAll('.ticket'));
    cards.forEach(card => {
      const id = (card.querySelector('.ticket-id')?.textContent || '').trim();
      const ticket = ticketData.find(t => String(t.ticket_id || '').trim() === id);
      if (!ticket) return;
      updateResultBadge(card, ticket);
      if (card.dataset.executionReady === '1') return;
      card.dataset.executionReady = '1';
      const legs = Array.isArray(ticket.legs) ? ticket.legs : [];
      const total = Number(ticket.total_odd || legs.reduce((a,l)=>a*Number(l.odd||1),1));
      const selections = legs.map(leg => `${leg.selection} @${fmtOdd(leg.odd)}`).join(' + ');
      const box = document.createElement('div'); box.className = 'execution-box';
      box.innerHTML = `<div class="execution-head"><span class="execution-title">Bilhete pronto</span><span class="execution-house">MODO TESTE</span></div><div class="execution-summary"><b>Odd ${fmtOdd(total)}</b><br>${selections}</div><div class="execution-actions"><button type="button" class="execution-open">🎯 Abrir bilhete pronto</button><button type="button" class="execution-copy">Copiar</button></div>`;
      const text = ticketText(ticket);
      box.querySelector('.execution-open').addEventListener('click', () => {
        window.open(`./aposta-teste.html?ticket=${encodeURIComponent(ticket.ticket_id || id)}`, '_blank', 'noopener,noreferrer');
      });
      box.querySelector('.execution-copy').addEventListener('click', async e => {
        const btn = e.currentTarget, original = btn.textContent;
        btn.textContent = await copyText(text) ? '✓ Copiado' : 'Copiar manualmente';
        setTimeout(() => btn.textContent = original, 1800);
      });
      card.appendChild(box); updateResultBadge(card, ticket);
    });
  }

  async function refreshTicketData() { try { ticketData = await readTickets(); enhanceTickets(); } catch (_) {} }
  async function syncState() {
    try {
      const state = await readRunStatus(); if (!state) return;
      currentStatus = state.status || null; configureMainButton(currentStatus);
      if (currentStatus === 'RUNNING') setRunState('Analisando jogos de hoje...');
      else if (currentStatus === 'SUCCESS') setRunState(`API ativa • ${Number(state.tickets_ready || 0)}/3 bilhetes oficiais`);
      else if (currentStatus === 'WAITING_FOR_API_KEY') setRunState('Falta configurar a API no GitHub');
      else if (currentStatus === 'FAILED') setRunState('Última análise falhou • ver Actions');
      else setRunState('Motor GitHub ativo');
    } catch (_) { setRunState('Motor GitHub ativo'); configureMainButton(currentStatus); }
  }

  ensureManagementNav();
  if (ticketList) { const observer = new MutationObserver(enhanceTickets); observer.observe(ticketList, { childList: true, subtree: true }); }
  if (analyzeBtn) configureMainButton(null);
  if (refreshBtn) refreshBtn.onclick = () => location.reload();
  syncState(); refreshTicketData(); setInterval(syncState, 30000); setInterval(refreshTicketData, 30000);
})();
