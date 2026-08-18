(() => {
  const ACTIONS_URL = 'https://github.com/stepoil-debug/douglas/actions/workflows/analyze-football.yml';
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const refreshBtn = $('refreshBtn');
  const runState = $('runState');

  function setRunState(text) {
    if (runState) runState.textContent = text;
  }

  async function readRunStatus() {
    const response = await fetch(`./run_status.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) return null;
    return response.json();
  }

  async function syncState() {
    try {
      const state = await readRunStatus();
      if (!state) return;
      if (state.status === 'RUNNING') setRunState('Analisando jogos de hoje...');
      else if (state.status === 'SUCCESS') {
        const count = Number(state.tickets_ready || 0);
        setRunState(`${count}/3 bilhetes prontos • GitHub Actions`);
      } else if (state.status === 'WAITING_FOR_API_KEY') setRunState('API-Football aguardando Secret no GitHub');
      else if (state.status === 'FAILED') setRunState('Última análise falhou • ver Actions');
      else setRunState('Motor GitHub ativo');
    } catch (_) {
      setRunState('Motor GitHub ativo');
    }
  }

  if (analyzeBtn) {
    analyzeBtn.textContent = '▶ Rodar agora';
    analyzeBtn.title = 'Abrir o workflow InvestBet Football no GitHub Actions';
    analyzeBtn.onclick = () => {
      window.open(ACTIONS_URL, '_blank', 'noopener,noreferrer');
    };
  }

  if (refreshBtn) {
    refreshBtn.onclick = () => location.reload();
  }

  syncState();
  setInterval(syncState, 30000);
})();
