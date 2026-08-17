(() => {
  const TRIGGER_URL = 'https://intranet-stepone.netlify.app/api/investbet/analysis-trigger';
  const ANALYZE_LABEL = '▶ Analisar jogos';
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const runState = $('runState');
  if (!analyzeBtn) return;

  // Remove credentials from any legacy browser storage. API keys must stay server-side.
  for (const key of ['tqe_github_token', 'tqe_tennis_key', 'investbet_api_key', 'api_football_key']) {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  }

  analyzeBtn.textContent = ANALYZE_LABEL;
  analyzeBtn.title = 'Buscar agenda de futebol, odds e previsões e executar o motor seletivo';

  function setRunState(text) {
    if (runState) runState.textContent = text;
  }

  function setBusy(busy) {
    analyzeBtn.disabled = busy;
    analyzeBtn.textContent = busy ? '⏳ Analisando futebol...' : ANALYZE_LABEL;
  }

  async function readRunStatus() {
    const response = await fetch(`./run_status.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) return null;
    return response.json();
  }

  async function readTriggerState() {
    const response = await fetch(`${TRIGGER_URL}?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) return null;
    return response.json();
  }

  async function waitForAnalysis(requestedAt, alreadyRunning = false) {
    const started = Date.parse(requestedAt || new Date().toISOString());
    let sawRunning = alreadyRunning;

    for (let i = 0; i < 180; i++) {
      await sleep(5000);
      try {
        const status = await readRunStatus();
        if (status?.status === 'RUNNING') {
          sawRunning = true;
          setRunState('Analisando futebol • agenda, odds e previsões...');
          continue;
        }
        if ((sawRunning || status?.status === 'SUCCESS') && status?.status === 'SUCCESS') {
          const updated = Date.parse(status.updated_at || '');
          if (!Number.isFinite(updated) || updated >= started) {
            setRunState('Análise concluída • painel atualizado');
            await sleep(900);
            location.reload();
            return;
          }
        }
        if (status?.status === 'WAITING_FOR_API_KEY') {
          setRunState('API-Football aguardando configuração segura');
          return;
        }
        if (sawRunning && status?.status === 'FAILED') {
          setRunState('Falha na análise • consulte a execução do GitHub Actions');
          return;
        }

        const queue = await readTriggerState();
        const state = queue?.state;
        if (state?.status === 'PENDING') setRunState('Solicitação recebida • aguardando execução...');
        else if (state?.status === 'CLAIMED') setRunState('Preparando motor de futebol...');
        else if (state?.status === 'DISPATCHED' && !sawRunning) setRunState('Motor iniciado • buscando jogos...');
      } catch (_) {}
    }
    setRunState('Análise solicitada • acompanhamento continua ativo');
  }

  async function startAnalysis() {
    setBusy(true);
    try {
      const current = await readRunStatus().catch(() => null);
      if (current?.status === 'RUNNING') {
        setRunState('Já existe uma análise em andamento • acompanhando...');
        await waitForAnalysis(current.updated_at || new Date().toISOString(), true);
        return;
      }

      setRunState('Solicitando análise completa do futebol...');
      const response = await fetch(TRIGGER_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: 'investbet-football-dashboard',
          action: 'analyze-football',
          scope: 'all-eligible-football-games',
          board_mode: 'D+1'
        })
      });

      let data = null;
      try { data = await response.json(); } catch (_) {}
      if (!response.ok || !data?.ok || !data?.accepted) {
        throw new Error(data?.error || `BACKEND_${response.status}`);
      }
      const state = data.state || {};
      setRunState('Solicitação recebida • iniciando motor de futebol...');
      await waitForAnalysis(state.requested_at);
    } catch (error) {
      console.error('[InvestBet Football] manual analysis trigger failed', error);
      setRunState('Não foi possível solicitar a análise');
      alert('Não foi possível iniciar a análise agora. O agendamento automático do GitHub Actions continuará tentando normalmente.');
    } finally {
      setBusy(false);
    }
  }

  analyzeBtn.onclick = startAnalysis;
})();
