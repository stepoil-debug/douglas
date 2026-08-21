(() => {
  const TRIGGER_URL = 'https://intranet-stepone.netlify.app/api/investbet/analysis-trigger';
  const RAW_STATUS_URL = 'https://raw.githubusercontent.com/stepoil-debug/douglas/main/dashboard/run_status.json';
  const WATCH_KEY = 'investbet_pending_analysis_v2';
  const POLL_MS = 5000;
  const MAX_WAIT_MS = 25 * 60 * 1000;
  const $ = id => document.getElementById(id);

  function formatDate(iso) {
    const [y,m,d] = String(iso || '').split('-');
    return y && m && d ? `${d}/${m}/${y}` : String(iso || '');
  }

  function saoPauloDate(offset = 0) {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'America/Sao_Paulo', year:'numeric', month:'2-digit', day:'2-digit'
    }).formatToParts(new Date());
    const v = Object.fromEntries(parts.filter(p => p.type !== 'literal').map(p => [p.type,p.value]));
    const dt = new Date(Date.UTC(Number(v.year), Number(v.month)-1, Number(v.day)+offset));
    return dt.toISOString().slice(0,10);
  }

  function selectedDate() {
    const select = $('analysisDateSelect');
    return saoPauloDate(select?.value === 'tomorrow' ? 1 : 0);
  }

  function notice(text, type='warn') {
    const n = $('notice');
    if (!n) return;
    n.className = `notice show ${type}`;
    n.textContent = text;
  }

  function setBusy(busy, date='') {
    const btn = $('analyzeBtn');
    const select = $('analysisDateSelect');
    if (select) select.disabled = busy;
    if (!btn) return;
    btn.disabled = busy;
    btn.textContent = busy ? `⏳ Analisando ${formatDate(date)}...` : '🔍 Analisar';
  }

  function setState(text) {
    const el = $('runState');
    if (el) el.textContent = text;
  }

  async function json(url, options={}) {
    const r = await fetch(url, { cache:'no-store', ...options });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(body?.error || `HTTP ${r.status}`), { body, status:r.status });
    return body;
  }

  function saveWatch(date, requestId, startedAt=Date.now()) {
    localStorage.setItem(WATCH_KEY, JSON.stringify({ date, requestId, startedAt }));
  }

  function clearWatch() {
    localStorage.removeItem(WATCH_KEY);
  }

  function readWatch() {
    try { return JSON.parse(localStorage.getItem(WATCH_KEY) || 'null'); } catch { return null; }
  }

  function updateBoardLabels(boardDate) {
    if (!boardDate) return;
    const today = saoPauloDate(0), tomorrow = saoPauloDate(1);
    const suffix = boardDate === today ? 'hoje' : boardDate === tomorrow ? 'amanhã' : formatDate(boardDate);
    const hero = document.querySelector('.hero h1');
    if (hero) hero.textContent = `3 bilhetes para ${suffix}`;
    const nav = document.querySelector('.nav a:first-child span');
    if (nav) nav.textContent = `Bilhetes de ${suffix}`;
    const board = $('boardDate');
    if (board) board.textContent = formatDate(boardDate);
    document.querySelectorAll('.panel li').forEach(li => {
      if (/rep(etir|ete).*partida/i.test(li.textContent || '')) li.textContent = 'Não repete a mesma partida entre os bilhetes do mesmo ciclo.';
    });
  }

  async function publishedStatus() {
    try { return await json(`./run_status.json?t=${Date.now()}`); } catch { return {}; }
  }

  async function rawStatus() {
    try { return await json(`${RAW_STATUS_URL}?t=${Date.now()}`); } catch { return {}; }
  }

  async function trigger(date) {
    setBusy(true, date);
    setState(`Solicitando ${formatDate(date)}...`);
    notice(`Solicitação enviada para ${formatDate(date)}. Acompanhando automaticamente até a publicação.`, 'warn');
    try {
      const payload = await json(TRIGGER_URL, {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ analysis_date:date })
      });
      const state = payload?.state || {};
      saveWatch(date, state.request_id || '', Date.now());
      watch(date, state.request_id || '', Date.now());
    } catch (e) {
      const active = e?.body?.state;
      if (e?.body?.error === 'ANALYSIS_ALREADY_ACTIVE' && active?.analysis_date) {
        saveWatch(active.analysis_date, active.request_id || '', Date.now());
        watch(active.analysis_date, active.request_id || '', Date.now());
        return;
      }
      clearWatch();
      setBusy(false);
      setState('Falha ao iniciar análise');
      notice(`Não foi possível iniciar a análise: ${e?.body?.error || e.message}.`, 'bad');
    }
  }

  let watcherToken = 0;
  async function watch(date, requestId, startedAt) {
    const token = ++watcherToken;
    setBusy(true, date);
    const loop = async () => {
      if (token !== watcherToken) return;
      const elapsed = Date.now() - startedAt;
      if (elapsed > MAX_WAIT_MS) {
        clearWatch(); setBusy(false); setState('Tempo limite excedido');
        notice('A análise não confirmou a publicação dentro de 25 minutos. O botão foi liberado para nova tentativa.', 'bad');
        return;
      }

      let triggerState = null;
      try {
        const t = await json(`${TRIGGER_URL}?t=${Date.now()}`);
        triggerState = t?.state || null;
      } catch {}

      if (triggerState && (!requestId || triggerState.request_id === requestId)) {
        const st = triggerState.status;
        if (st === 'PENDING') { setState(`Na fila • ${formatDate(date)}`); notice(`Solicitação recebida. O executor seguro vai assumir automaticamente; esta tela continuará acompanhando.`, 'warn'); }
        else if (st === 'CLAIMED') { setState(`Executor recebeu • ${formatDate(date)}`); notice('Executor seguro recebeu a solicitação e está preparando o workflow.', 'warn'); }
        else if (st === 'DISPATCHED') { setState(`Análise em execução • ${formatDate(date)}`); notice('Workflow iniciado. Consultando agenda, odds, previsões e montando os bilhetes.', 'warn'); }
        else if (st === 'FAILED') { clearWatch(); setBusy(false); setState('Análise falhou'); notice(`A análise falhou${triggerState.error ? `: ${triggerState.error}` : ''}. O botão foi liberado para tentar novamente.`, 'bad'); return; }
        else if (st === 'COMPLETED') { setState(`Análise concluída • publicando ${formatDate(date)}`); notice('Motor concluído. Aguardando somente a publicação do novo board.', 'good'); }
      }

      const raw = await rawStatus();
      if (raw?.board_date === date && raw?.status === 'SUCCESS') {
        const pub = await publishedStatus();
        if (pub?.board_date === date && pub?.status === 'SUCCESS') {
          clearWatch();
          updateBoardLabels(date);
          setState(`Concluído • ${Number(pub.tickets_ready || 0)}/3 bilhetes`);
          notice(`Análise de ${formatDate(date)} concluída e publicada. Atualizando o painel...`, 'good');
          setTimeout(() => location.reload(), 900);
          return;
        }
        setState(`Concluído • aguardando GitHub Pages`);
        notice('A análise terminou e foi salva. Aguardando a publicação do GitHub Pages; a tela atualizará sozinha.', 'good');
      }

      setTimeout(loop, POLL_MS);
    };
    loop();
  }

  function money(value) {
    return new Intl.NumberFormat('pt-BR', { style:'currency', currency:'BRL' }).format(Number(value || 0));
  }

  function signedMoney(value) {
    const n = Number(value || 0);
    return `${n > 0 ? '+' : ''}${money(n)}`;
  }

  function signedPercent(value) {
    const n = Number(value || 0);
    return `${n > 0 ? '+' : ''}${n.toFixed(2).replace('.', ',')}%`;
  }

  function ensureBankrollStyles() {
    if ($('investbetBankrollStyles')) return;
    const style = document.createElement('style');
    style.id = 'investbetBankrollStyles';
    style.textContent = `
      .bankroll-summary{margin:0 0 30px;border:1px solid rgba(216,168,47,.18);background:linear-gradient(140deg,rgba(11,31,20,.98),rgba(7,22,15,.98));padding:16px 17px}
      .bankroll-summary-head{display:flex;align-items:end;justify-content:space-between;gap:14px;margin-bottom:12px}
      .bankroll-summary-head h2{margin:4px 0 0;font-size:18px}.bankroll-summary-head a{font-size:10px;color:#9bd9b5;text-decoration:none;font-weight:900}
      .bankroll-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
      .bankroll-card{border:1px solid rgba(117,157,130,.14);background:#08180f;padding:13px 14px;display:grid;grid-template-columns:1.25fr repeat(4,1fr);gap:10px;align-items:center}
      .bankroll-card-title small{display:block;color:#6f8877;font-size:8px;text-transform:uppercase;letter-spacing:.08em}.bankroll-card-title b{display:block;font-size:14px;margin-top:3px}
      .bankroll-metric small{display:block;color:#617a69;font-size:7px;text-transform:uppercase}.bankroll-metric b{display:block;font-size:14px;margin-top:3px}
      .bankroll-positive{color:#71e3a1!important}.bankroll-negative{color:#ff7b84!important}.bankroll-gold{color:#f2cc62!important}
      .bankroll-updated{font-size:8px;color:#657d6c;margin-top:9px;text-align:right}
      @media(max-width:1150px){.bankroll-grid{grid-template-columns:1fr}.bankroll-card{grid-template-columns:1.3fr repeat(4,1fr)}}
      @media(max-width:720px){.bankroll-card{grid-template-columns:1fr 1fr}.bankroll-card-title{grid-column:1/-1}.bankroll-summary-head{align-items:flex-start}.bankroll-summary-head h2{font-size:16px}}
    `;
    document.head.appendChild(style);
  }

  function strategyCard(strategy, title, subtitle) {
    const profit = Number(strategy?.profit || 0);
    const roi = Number(strategy?.roi || 0);
    const clsProfit = profit > 0 ? 'bankroll-positive' : profit < 0 ? 'bankroll-negative' : '';
    const clsRoi = roi > 0 ? 'bankroll-positive' : roi < 0 ? 'bankroll-negative' : '';
    return `
      <div class="bankroll-card">
        <div class="bankroll-card-title"><small>${subtitle}</small><b>${title}</b></div>
        <div class="bankroll-metric"><small>Banca atual</small><b class="bankroll-gold">${money(strategy?.bankroll)}</b></div>
        <div class="bankroll-metric"><small>Disponível</small><b>${money(strategy?.available_bankroll)}</b></div>
        <div class="bankroll-metric"><small>Lucro / Prejuízo</small><b class="${clsProfit}">${signedMoney(profit)}</b></div>
        <div class="bankroll-metric"><small>ROI</small><b class="${clsRoi}">${signedPercent(roi)}</b></div>
      </div>`;
  }

  async function loadBankrollSummary() {
    try {
      const data = await json(`./management.json?t=${Date.now()}`);
      const strategies = data?.strategies || {};
      const all = strategies.all_three || {};
      const safest = strategies.safest_only || {};
      ensureBankrollStyles();

      let box = $('bankrollSummary');
      if (!box) {
        box = document.createElement('section');
        box.id = 'bankrollSummary';
        box.className = 'bankroll-summary';
        const ticketsSection = $('tickets');
        const kpis = document.querySelector('.kpis');
        if (ticketsSection?.parentNode) ticketsSection.parentNode.insertBefore(box, ticketsSection);
        else if (kpis?.parentNode) kpis.parentNode.insertBefore(box, kpis.nextSibling);
        else return;
      }

      const updated = data?.updated_at
        ? new Intl.DateTimeFormat('pt-BR', { timeZone:'America/Sao_Paulo', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false }).format(new Date(data.updated_at))
        : '—';
      const stake = money(data?.fixed_stake || 10);
      box.innerHTML = `
        <div class="bankroll-summary-head">
          <div><div class="eyebrow">Gestão simulada • banca inicial ${money(data?.initial_bankroll || 100)}</div><h2>Acompanhamento da banca</h2></div>
          <a href="./gestao.html">Abrir gestão completa →</a>
        </div>
        <div class="bankroll-grid">
          ${strategyCard(all, 'Mão fixa • 3 bilhetes', `${stake} em cada bilhete`)}
          ${strategyCard(safest, 'Entrada mais segura', `${stake} no bilhete de maior probabilidade`)}
        </div>
        <div class="bankroll-updated">Exposição aberta: ${money(all.open_exposure)} / ${money(safest.open_exposure)} • atualizado em ${updated}</div>`;
    } catch (e) {
      console.warn('Resumo da banca indisponível:', e);
    }
  }

  async function boot() {
    const btn = $('analyzeBtn');
    if (!btn) return;

    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopImmediatePropagation();
      trigger(selectedDate());
    }, true);

    const current = await publishedStatus();
    if (current?.board_date) updateBoardLabels(current.board_date);
    loadBankrollSummary();

    const saved = readWatch();
    if (saved?.date && Date.now() - Number(saved.startedAt || 0) < MAX_WAIT_MS) {
      if (current?.board_date === saved.date && current?.status === 'SUCCESS') {
        clearWatch(); setBusy(false); updateBoardLabels(saved.date);
      } else {
        watch(saved.date, saved.requestId || '', Number(saved.startedAt || Date.now()));
        return;
      }
    }

    try {
      const t = await json(`${TRIGGER_URL}?t=${Date.now()}`);
      const s = t?.state;
      if (s?.analysis_date && ['PENDING','CLAIMED','DISPATCHED'].includes(s.status)) {
        if (!(current?.board_date === s.analysis_date && current?.status === 'SUCCESS')) {
          saveWatch(s.analysis_date, s.request_id || '', Date.parse(s.requested_at || '') || Date.now());
          watch(s.analysis_date, s.request_id || '', Date.parse(s.requested_at || '') || Date.now());
        }
      }
    } catch {}

    setInterval(loadBankrollSummary, 60000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => setTimeout(boot, 0));
  else setTimeout(boot, 0);
})();
