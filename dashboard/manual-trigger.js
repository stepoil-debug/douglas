(() => {
  const TRIGGER_URL = 'https://intranet-stepone.netlify.app/api/investbet/analysis-trigger';
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const runState = $('runState');
  const oldTip = $('manualTip');
  if (!analyzeBtn) return;
  if (oldTip) oldTip.remove();

  // Remove credentials left by the former browser-token implementation.
  for (const key of ['tqe_github_token', 'tqe_tennis_key']) {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  }

  function setRunState(text) {
    if (runState) runState.textContent = text;
  }

  function setBusy(busy) {
    analyzeBtn.disabled = busy;
    analyzeBtn.textContent = busy ? '⏳ Solicitando...' : '▶ Fazer análise agora';
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

  async function waitForAnalysis(requestedAt) {
    const started = Date.parse(requestedAt || new Date().toISOString());
    let sawRunning = false;

    for (let i = 0; i < 180; i++) {
      await sleep(5000);
      try {
        const status = await readRunStatus();
        if (status?.status === 'RUNNING') {
          sawRunning = true;
          setRunState('Análise em andamento...');
          continue;
        }

        if (sawRunning && status?.status === 'SUCCESS') {
          const updated = Date.parse(status.updated_at || '');
          if (!Number.isFinite(updated) || updated >= started) {
            setRunState('Análise concluída');
            await sleep(1200);
            location.reload();
            return;
          }
        }

        if (sawRunning && status?.status === 'FAILED') {
          setRunState('Análise falhou • nova tentativa automática');
          return;
        }

        const queue = await readTriggerState();
        const state = queue?.state;
        if (state?.status === 'PENDING') setRunState('Solicitação recebida • aguardando início...');
        else if (state?.status === 'CLAIMED') setRunState('Preparando análise...');
        else if (state?.status === 'DISPATCHED' && !sawRunning) setRunState('Análise iniciada...');
      } catch {
        // Keep watching run_status.json on the next cycle.
      }
    }

    setRunState('Solicitação registrada • automação continuará acompanhando');
  }

  async function startAnalysis() {
    setBusy(true);
    try {
      setRunState('Solicitando nova análise...');
      const response = await fetch(TRIGGER_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: 'investbet-dashboard' })
      });

      let data = null;
      try { data = await response.json(); } catch {}
      if (!response.ok || !data?.ok || !data?.accepted) {
        throw new Error(data?.error || `BACKEND_${response.status}`);
      }

      const state = data.state || {};
      if (data.mode === 'direct') {
        setRunState('Análise iniciada...');
      } else {
        setRunState('Solicitação recebida • início automático em até 5 min');
      }

      setBusy(false);
      await waitForAnalysis(state.requested_at);
    } catch (error) {
      console.error('[InvestBet] manual analysis trigger failed', error);
      setRunState('Não foi possível solicitar a análise');
      alert('Não foi possível iniciar a análise agora. A automação de 30 minutos continua ativa e tentará normalmente.');
    } finally {
      setBusy(false);
    }
  }

  analyzeBtn.onclick = startAnalysis;
})();
