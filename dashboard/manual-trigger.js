(() => {
  const ACTIONS_URL = 'https://github.com/stepoil-debug/douglas/actions/workflows/analyze-football.yml';
  const SECRETS_URL = 'https://github.com/stepoil-debug/douglas/settings/secrets/actions/new';
  const BETANO_URL = 'https://www.betano.bet.br/sport/futebol/jogos-de-hoje/';
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const refreshBtn = $('refreshBtn');
  const runState = $('runState');
  const ticketList = $('ticketList');
  let currentStatus = null;
  let ticketData = [];

  function setRunState(text) {
    if (runState) runState.textContent = text;
  }

  function configureMainButton(state) {
    if (!analyzeBtn) return;
    if (state === 'WAITING_FOR_API_KEY') {
      analyzeBtn.textContent = '🔐 Configurar API';
      analyzeBtn.title = 'Abrir a criação do Secret da API no próprio repositório GitHub';
      analyzeBtn.disabled = false;
      analyzeBtn.onclick = () => window.open(SECRETS_URL, '_blank', 'noopener,noreferrer');
      return;
    }
    if (state === 'SUCCESS') {
      analyzeBtn.textContent = '▶ Rodar novamente';
      analyzeBtn.disabled = false;
      analyzeBtn.title = 'Abrir o workflow InvestBet Football no GitHub Actions';
      analyzeBtn.onclick = () => window.open(ACTIONS_URL, '_blank', 'noopener,noreferrer');
      return;
    }
    analyzeBtn.textContent = state === 'RUNNING' ? '⏳ Analisando...' : '▶ Rodar agora';
    analyzeBtn.disabled = state === 'RUNNING';
    analyzeBtn.title = 'Abrir o workflow InvestBet Football no GitHub Actions';
    analyzeBtn.onclick = () => window.open(ACTIONS_URL, '_blank', 'noopener,noreferrer');
  }

  async function readRunStatus() {
    const response = await fetch(`./run_status.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) return null;
    return response.json();
  }

  async function readTickets() {
    const response = await fetch(`./data.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) return [];
    const data = await response.json();
    return data.tickets || data.approved || [];
  }

  function moneyOdd(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) && n > 0 ? n.toFixed(2).replace('.', ',') : '—';
  }

  function betanoPriceForLeg(leg) {
    const quotes = leg && leg.bookmaker_quotes ? leg.bookmaker_quotes : {};
    const exact = Object.entries(quotes).find(([name]) => String(name).trim().toLowerCase() === 'betano');
    if (!exact) return null;
    const odd = Number(exact[1]);
    return Number.isFinite(odd) && odd > 1 ? odd : null;
  }

  function betanoExecution(ticket) {
    const legs = Array.isArray(ticket.legs) ? ticket.legs : [];
    if (!legs.length) return null;
    const priced = [];
    let total = 1;
    for (const leg of legs) {
      const odd = betanoPriceForLeg(leg);
      if (!odd) return null;
      total *= odd;
      priced.push({ ...leg, execution_odd: odd });
    }
    return { total, legs: priced };
  }

  function ticketText(ticket, execution) {
    const lines = [
      `INVESTBET • ${ticket.ticket_id || 'BILHETE'} • ${ticket.profile || 'SELETIVO'}`,
      `Casa: Betano`,
      `Odd de referência na Betano: ${moneyOdd(execution.total)}`,
      ''
    ];
    execution.legs.forEach((leg, index) => {
      lines.push(`${index + 1}. ${leg.match}`);
      lines.push(`   ${leg.market}: ${leg.selection}`);
      lines.push(`   Odd Betano: ${moneyOdd(leg.execution_odd)}`);
    });
    lines.push('', `Gerado em ${new Date().toLocaleString('pt-BR')}`);
    lines.push('Confira as odds e o mercado na casa antes de confirmar.');
    return lines.join('\n');
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.focus();
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (_) {}
      area.remove();
      return ok;
    }
  }

  function addExecutorStyles() {
    if (document.getElementById('executorStyles')) return;
    const style = document.createElement('style');
    style.id = 'executorStyles';
    style.textContent = `
      .execution-box{margin:0 16px 16px;padding:12px;border:1px solid rgba(242,204,98,.22);background:linear-gradient(135deg,rgba(216,168,47,.09),rgba(7,24,15,.92));border-radius:10px}
      .execution-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}
      .execution-title{font-size:10px;font-weight:950;text-transform:uppercase;letter-spacing:.08em;color:#f2cc62}
      .execution-house{font-size:10px;color:#9aefbb;font-weight:900}
      .execution-summary{font-size:10px;color:#829989;line-height:1.5;margin-bottom:10px}
      .execution-summary b{color:#f4f0e4}
      .execution-actions{display:grid;grid-template-columns:1fr auto;gap:8px}
      .execution-open,.execution-copy{border-radius:9px;padding:10px 12px;font-size:11px;font-weight:950;cursor:pointer;border:1px solid}
      .execution-open{background:linear-gradient(135deg,#f0ca60,#c8921b);color:#1c1605;border-color:#d1a12c}
      .execution-copy{background:#091911;color:#d9e4dc;border-color:#294735}
      .execution-open:hover{filter:brightness(1.06)}
      .execution-copy:hover{border-color:#4f795f}
      .execution-unavailable{margin:0 16px 16px;padding:10px 12px;border:1px dashed #304d3a;color:#758b7c;font-size:10px}
      @media(max-width:720px){.execution-actions{grid-template-columns:1fr}.execution-copy{width:100%}}
    `;
    document.head.appendChild(style);
  }

  function enhanceTickets() {
    if (!ticketList || !ticketData.length) return;
    addExecutorStyles();
    const cards = Array.from(ticketList.querySelectorAll('.ticket'));
    cards.forEach(card => {
      if (card.dataset.executionReady === '1') return;
      const id = (card.querySelector('.ticket-id')?.textContent || '').trim();
      const ticket = ticketData.find(t => String(t.ticket_id || '').trim() === id);
      if (!ticket) return;
      card.dataset.executionReady = '1';
      const execution = betanoExecution(ticket);
      if (!execution) {
        const unavailable = document.createElement('div');
        unavailable.className = 'execution-unavailable';
        unavailable.textContent = 'Este bilhete não possui cotação Betano em todas as seleções. Mantido apenas para auditoria.';
        card.appendChild(unavailable);
        return;
      }

      const box = document.createElement('div');
      box.className = 'execution-box';
      const selections = execution.legs.map(leg => `${leg.selection} @${moneyOdd(leg.execution_odd)}`).join(' + ');
      box.innerHTML = `
        <div class="execution-head"><span class="execution-title">Executar bilhete</span><span class="execution-house">BETANO</span></div>
        <div class="execution-summary"><b>Odd Betano ${moneyOdd(execution.total)}</b><br>${selections}</div>
        <div class="execution-actions">
          <button type="button" class="execution-open">🎯 Abrir bilhete na Betano</button>
          <button type="button" class="execution-copy">Copiar</button>
        </div>`;

      const text = ticketText(ticket, execution);
      const openBtn = box.querySelector('.execution-open');
      const copyBtn = box.querySelector('.execution-copy');

      openBtn.addEventListener('click', async () => {
        await copyText(text);
        const original = openBtn.textContent;
        openBtn.textContent = '✓ Bilhete copiado • abrindo Betano';
        window.open(BETANO_URL, '_blank', 'noopener,noreferrer');
        setTimeout(() => { openBtn.textContent = original; }, 2400);
      });

      copyBtn.addEventListener('click', async () => {
        const ok = await copyText(text);
        const original = copyBtn.textContent;
        copyBtn.textContent = ok ? '✓ Copiado' : 'Copiar manualmente';
        setTimeout(() => { copyBtn.textContent = original; }, 1800);
      });

      card.appendChild(box);
    });
  }

  async function refreshTicketData() {
    try {
      ticketData = await readTickets();
      enhanceTickets();
    } catch (_) {}
  }

  async function syncState() {
    try {
      const state = await readRunStatus();
      if (!state) return;
      currentStatus = state.status || null;
      configureMainButton(currentStatus);
      if (currentStatus === 'RUNNING') setRunState('Analisando jogos de hoje...');
      else if (currentStatus === 'SUCCESS') {
        const count = Number(state.tickets_ready || 0);
        setRunState(`API ativa • ${count}/3 bilhetes prontos`);
      } else if (currentStatus === 'WAITING_FOR_API_KEY') {
        setRunState('Falta configurar a API no GitHub');
      } else if (currentStatus === 'FAILED') setRunState('Última análise falhou • ver Actions');
      else setRunState('Motor GitHub ativo');
    } catch (_) {
      setRunState('Motor GitHub ativo');
      configureMainButton(currentStatus);
    }
  }

  if (ticketList) {
    const observer = new MutationObserver(() => enhanceTickets());
    observer.observe(ticketList, { childList: true, subtree: true });
  }

  if (analyzeBtn) configureMainButton(null);
  if (refreshBtn) refreshBtn.onclick = () => location.reload();

  syncState();
  refreshTicketData();
  setInterval(syncState, 30000);
  setInterval(refreshTicketData, 30000);
})();
