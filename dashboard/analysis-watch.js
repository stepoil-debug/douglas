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
    if (nav) nav.textContent = `3 bilhetes de ${suffix}`;
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
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => setTimeout(boot, 0));
  else setTimeout(boot, 0);
})();
