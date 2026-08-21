(() => {
  const ACTIONS_URL = 'https://github.com/stepoil-debug/douglas/actions/workflows/analyze-football.yml';
  const SETTLE_ACTIONS_URL = 'https://github.com/stepoil-debug/douglas/actions/workflows/settle-football.yml';
  const SECRETS_URL = 'https://github.com/stepoil-debug/douglas/settings/secrets/actions/new';
  const TRIGGER_URL = 'https://intranet-stepone.netlify.app/api/investbet/analysis-trigger';
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const refreshBtn = $('refreshBtn');
  const runState = $('runState');
  const ticketList = $('ticketList');
  const notice = $('notice');
  let currentStatus = null;
  let verifyBtn = null;
  let analysisDateSelect = null;

  function setRunState(text) {
    if (runState && runState.textContent !== text) runState.textContent = text;
  }

  function showNotice(message, type = 'good') {
    if (!notice) return;
    notice.className = `notice show ${type}`;
    notice.textContent = message;
  }

  function saoPauloDate(offsetDays = 0) {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'America/Sao_Paulo',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit'
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
    const date = new Date(Date.UTC(Number(values.year), Number(values.month) - 1, Number(values.day) + offsetDays));
    return date.toISOString().slice(0, 10);
  }

  function formatAnalysisDate(iso) {
    const [year, month, day] = String(iso || '').split('-');
    return year && month && day ? `${day}/${month}/${year}` : iso;
  }

  function selectedAnalysisDate() {
    return saoPauloDate(analysisDateSelect?.value === 'tomorrow' ? 1 : 0);
  }

  function ensureAnalysisDateSelector() {
    const actions = document.querySelector('.actions');
    if (!actions || !analyzeBtn) return null;
    let select = $('analysisDateSelect');
    if (!select) {
      select = document.createElement('select');
      select.id = 'analysisDateSelect';
      select.className = 'btn secondary';
      select.setAttribute('aria-label', 'Data da análise');
      select.title = 'Selecione se deseja analisar os jogos de hoje ou de amanhã';
      actions.insertBefore(select, analyzeBtn);
    }
    select.innerHTML = `
      <option value="today">📅 Hoje • ${formatAnalysisDate(saoPauloDate(0))}</option>
      <option value="tomorrow">📅 Amanhã • ${formatAnalysisDate(saoPauloDate(1))}</option>
    `;
    analysisDateSelect = select;
    return select;
  }

  async function triggerAnalysis() {
    if (!analyzeBtn) return;
    const analysisDate = selectedAnalysisDate();
    const label = analysisDateSelect?.value === 'tomorrow' ? 'amanhã' : 'hoje';
    const originalText = analyzeBtn.textContent;
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = `⏳ Analisando ${label}...`;
    setRunState(`Solicitando análise de ${formatAnalysisDate(analysisDate)}...`);
    showNotice(`Solicitando ao motor a análise dos jogos de ${label} (${formatAnalysisDate(analysisDate)}).`, 'warn');

    try {
      const response = await fetch(TRIGGER_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis_date: analysisDate })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload?.ok === false) {
        throw new Error(payload?.error || `HTTP ${response.status}`);
      }

      if (payload?.mode === 'queue') {
        showNotice(`A solicitação para ${formatAnalysisDate(analysisDate)} foi recebida e está aguardando o executor seguro.`, 'warn');
        setRunState(`Análise ${formatAnalysisDate(analysisDate)} na fila`);
      } else {
        showNotice(`Análise de ${formatAnalysisDate(analysisDate)} iniciada com sucesso. O painel será atualizado assim que o GitHub concluir o processamento.`, 'good');
        setRunState(`Analisando jogos de ${formatAnalysisDate(analysisDate)}...`);
      }

      currentStatus = 'RUNNING';
      setTimeout(syncState, 3500);
      setTimeout(syncState, 12000);
    } catch (error) {
      console.error('Falha ao disparar análise:', error);
      showNotice('Não foi possível iniciar a análise pelo painel. O workflow continua disponível no GitHub Actions.', 'bad');
      setRunState('Falha ao iniciar análise');
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = originalText || '🔍 Analisar';
      return;
    }

    setTimeout(() => {
      if (currentStatus !== 'RUNNING') configureMainButton(currentStatus);
    }, 1500);
  }

  function ensureCleanNavigation() {
    const nav = document.querySelector('.nav');
    if (!nav) return;

    if (!document.getElementById('investbetNavStyles')) {
      const style = document.createElement('style');
      style.id = 'investbetNavStyles';
      style.textContent = `
        .nav-config{margin-top:2px;border:1px solid transparent;border-radius:9px;overflow:hidden}
        .nav-config[open]{border-color:rgba(216,168,47,.12);background:rgba(216,168,47,.025)}
        .nav-config summary{list-style:none;cursor:pointer;padding:11px 12px;color:#88a08f;font-size:13px;font-weight:850;display:flex;align-items:center;justify-content:space-between;gap:8px;border-radius:9px}
        .nav-config summary::-webkit-details-marker{display:none}
        .nav-config summary:hover,.nav-config[open] summary{color:#f4e8c7;background:rgba(216,168,47,.05)}
        .nav-config summary .chevron{font-size:9px;color:#60796a;transition:transform .16s ease}
        .nav-config[open] summary .chevron{transform:rotate(180deg)}
        .nav-sub{display:grid;gap:2px;padding:2px 6px 8px 16px;margin-left:13px;border-left:1px solid rgba(216,168,47,.12)}
        .nav-sub a{padding:8px 9px!important;font-size:11px!important;font-weight:750!important;color:#718979!important}
        .nav-sub a:hover{color:#f4e8c7!important}
        @media(max-width:1150px){.nav-config summary{justify-content:center}.nav-config summary span,.nav-config summary .chevron,.nav-sub{display:none}.nav-config[open] .nav-sub{display:none}}
      `;
      document.head.appendChild(style);
    }

    nav.innerHTML = `
      <a href="#tickets">🎟️ <span>Bilhetes de hoje</span></a>
      <a href="./bilhetes.html">📚 <span>Histórico de bilhetes</span></a>
      <details class="nav-config">
        <summary>⚙️ <span>Configurações</span><span class="chevron">⌄</span></summary>
        <div class="nav-sub">
          <a href="./gestao.html">📈 <span>Gestão simulada</span></a>
          <a href="#games">⚽ <span>Jogos analisados</span></a>
          <a href="#method">⌁ <span>Motor de análise</span></a>
          <a href="#history">◷ <span>Desempenho</span></a>
        </div>
      </details>
    `;
  }

  function ensureVerifyButton() {
    const actions = document.querySelector('.actions');
    if (!actions) return null;
    let button = $('verifyTicketsBtn');
    if (!button) {
      button = document.createElement('button');
      button.id = 'verifyTicketsBtn';
      button.type = 'button';
      button.className = 'btn secondary';
      button.textContent = '✓ Verificar bilhetes';
      button.title = 'Conferir GREEN/RED dos bilhetes com o último settlement da API-Football';
      if (refreshBtn) actions.insertBefore(button, refreshBtn);
      else actions.appendChild(button);
    }
    verifyBtn = button;
    return button;
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
        ? '🔍 Analisar novamente'
        : '🔍 Analisar';
    if (analyzeBtn.textContent !== nextText) analyzeBtn.textContent = nextText;
    analyzeBtn.disabled = state === 'RUNNING';
    analyzeBtn.onclick = triggerAnalysis;
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

  function formatDateTime(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '—';
    return new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo',
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }).format(date);
  }

  function estimatedResultTime(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '—';
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
      .leg-time{display:flex;align-items:center;gap:7px;margin:0 0 7px;color:#f2cc62;font-size:10px;font-weight:900;flex-wrap:wrap}
      .leg-time .result-at{color:#86a28f;font-weight:750}
      .ticket-schedule{margin:0 16px 12px;padding:10px 11px;border:1px solid rgba(115,183,255,.17);background:rgba(30,73,112,.08);border-radius:8px;color:#9ab5a3;font-size:10px;line-height:1.5}
      .ticket-schedule b{color:#dce9df}
      .ticket-schedule .settle{color:#f2cc62;font-weight:900}
      .ticket-result-badge{display:inline-flex;margin:0 16px 10px;padding:7px 9px;border-radius:7px;font-size:9px;font-weight:950;letter-spacing:.04em;text-transform:uppercase}
      .ticket-result-badge.pending,.leg-result.pending{color:#ead38a;border:1px solid rgba(216,168,47,.2);background:rgba(216,168,47,.07)}
      .ticket-result-badge.green,.leg-result.green{color:#9aefbb;border:1px solid rgba(113,227,161,.25);background:rgba(113,227,161,.08)}
      .ticket-result-badge.red,.leg-result.red{color:#ffadb3;border:1px solid rgba(255,123,132,.24);background:rgba(255,123,132,.07)}
      .ticket-result-badge.manual,.leg-result.manual{color:#b6d8ff;border:1px solid rgba(115,183,255,.24);background:rgba(115,183,255,.07)}
      .leg-result{display:flex;align-items:flex-start;gap:7px;margin-top:8px;padding:7px 8px;border-radius:7px;font-size:9px;font-weight:850;line-height:1.45}
      .verify-helper{font-size:9px;color:#718a79;margin-left:4px}
    `;
    document.head.appendChild(style);
  }

  function statusBadge(item) {
    const raw = String(item?.status || 'PENDING').toUpperCase();
    if (raw === 'GREEN' || raw === 'HIT') return { cls: 'green', text: '✓ GREEN' };
    if (raw === 'RED' || raw === 'MISS') return { cls: 'red', text: '✕ RED' };
    if (raw === 'MANUAL') return { cls: 'manual', text: '◷ CONFERÊNCIA MANUAL' };
    if (raw === 'VOID') return { cls: 'manual', text: '↺ VOID' };
    return { cls: 'pending', text: '⏳ Aguardando resultado' };
  }

  function settlementSummary(data) {
    const tickets = data?.tickets || data?.approved || [];
    let green = 0;
    let red = 0;
    let pending = 0;
    let manual = 0;
    tickets.forEach(ticket => {
      const status = String(ticket?.status || 'PENDING').toUpperCase();
      if (status === 'GREEN' || status === 'HIT') green += 1;
      else if (status === 'RED' || status === 'MISS') red += 1;
      else if (status === 'MANUAL' || status === 'VOID') manual += 1;
      else pending += 1;
    });
    return { total: tickets.length, green, red, pending, manual };
  }

  async function loadData() {
    const response = await fetch(`./data.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function enhanceTicketTimes(inputData = null) {
    if (!ticketList) return null;
    try {
      const data = inputData || await loadData();
      const tickets = data.tickets || data.approved || [];
      if (!tickets.length) return data;
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
          if (!leg) return;
          if (leg.kickoff_iso) {
            let time = node.querySelector('.leg-time');
            if (!time) {
              time = document.createElement('div');
              time.className = 'leg-time';
              node.insertBefore(time, node.firstChild);
            }
            time.innerHTML = `🕒 Início ${formatTime(leg.kickoff_iso)} <span class="result-at">• resultado ~${estimatedResultTime(leg.kickoff_iso)}</span>`;
          }

          const legBadgeState = statusBadge(leg);
          let legResult = node.querySelector('.leg-result');
          if (!legResult) {
            legResult = document.createElement('div');
            legResult.className = 'leg-result';
            node.appendChild(legResult);
          }
          legResult.className = `leg-result ${legBadgeState.cls}`;
          const score = leg.result_score ? ` • placar ${leg.result_score}` : '';
          const reason = leg.result_reason ? ` • ${leg.result_reason}` : '';
          legResult.textContent = `${legBadgeState.text}${score}${reason}`;
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
          const checked = data?.settlement?.checked_at
            ? `<br>Última conferência da API: <b>${formatDateTime(data.settlement.checked_at)}</b>`
            : '';
          summary.innerHTML = `<b>⏱ Fechamento do bilhete</b><br>Último jogo começa às <b>${formatTime(lastIso)}</b> • resultado completo esperado por volta de <span class="settle">${estimatedResultTime(lastIso)}</span> (Brasília)${checked}`;
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
      return data;
    } catch (_) {
      return null;
    }
  }

  async function verifyTickets() {
    ensureVerifyButton();
    if (!verifyBtn) return;
    const original = verifyBtn.textContent;
    verifyBtn.disabled = true;
    verifyBtn.textContent = '⏳ Verificando...';
    try {
      const data = await loadData();
      await enhanceTicketTimes(data);
      const summary = settlementSummary(data);
      const checkedAt = data?.settlement?.checked_at ? ` • API conferida em ${formatDateTime(data.settlement.checked_at)}` : '';
      if (!summary.total) {
        showNotice('Ainda não existem bilhetes oficiais para conferir.', 'warn');
      } else if (summary.pending > 0 || summary.manual > 0) {
        showNotice(`Bilhetes: ${summary.green} GREEN • ${summary.red} RED • ${summary.pending} pendente(s)${summary.manual ? ` • ${summary.manual} manual/void` : ''}${checkedAt}. A conferência automática roda de hora em hora.`, 'warn');
      } else {
        const type = summary.red > 0 ? 'warn' : 'good';
        showNotice(`Conferência concluída: ${summary.green} GREEN • ${summary.red} RED${checkedAt}. Os placares e o resultado de cada perna estão exibidos nos bilhetes.`, type);
      }
      setRunState(`Bilhetes conferidos • ${summary.green} GREEN / ${summary.red} RED`);
    } catch (error) {
      showNotice('Não foi possível carregar a última conferência agora. Você pode abrir o settlement manual no GitHub Actions.', 'bad');
      verifyBtn.onclick = () => window.open(SETTLE_ACTIONS_URL, '_blank', 'noopener,noreferrer');
    } finally {
      verifyBtn.disabled = false;
      verifyBtn.textContent = original;
    }
  }

  async function syncState() {
    try {
      const response = await fetch(`./run_status.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) return;
      const state = await response.json();
      currentStatus = state.status || null;
      configureMainButton(currentStatus);
      if (currentStatus === 'RUNNING') setRunState('Analisando jogos...');
      else if (currentStatus === 'SUCCESS') setRunState(`API ativa • ${Number(state.tickets_ready || 0)}/3 bilhetes oficiais`);
      else if (currentStatus === 'WAITING_FOR_API_KEY') setRunState('Falta configurar a API no GitHub');
      else if (currentStatus === 'FAILED') setRunState('Última análise falhou • ver Actions');
      else setRunState('Motor GitHub ativo');
    } catch (_) {
      setRunState('Motor GitHub ativo');
      configureMainButton(currentStatus);
    }
  }

  ensureCleanNavigation();
  ensureAnalysisDateSelector();
  ensureVerifyButton();
  if (verifyBtn) verifyBtn.onclick = verifyTickets;
  if (analyzeBtn) configureMainButton(null);
  if (refreshBtn) refreshBtn.onclick = () => location.reload();

  syncState();
  setTimeout(enhanceTicketTimes, 600);
  setTimeout(enhanceTicketTimes, 1800);
  setInterval(syncState, 120000);
  setInterval(enhanceTicketTimes, 120000);
})();
