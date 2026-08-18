(() => {
  const ACTIONS_URL = 'https://github.com/stepoil-debug/douglas/actions/workflows/analyze-football.yml';
  const SECRETS_URL = 'https://github.com/stepoil-debug/douglas/settings/secrets/actions/new';
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const refreshBtn = $('refreshBtn');
  const runState = $('runState');
  let currentStatus = null;

  function setRunState(text) {
    if (runState) runState.textContent = text;
  }

  function configureMainButton(state) {
    if (!analyzeBtn) return;
    if (state === 'WAITING_FOR_API_KEY') {
      analyzeBtn.textContent = '🔐 Configurar API';
      analyzeBtn.title = 'Abrir a criação do Secret API_FOOTBALL_KEY no próprio repositório GitHub';
      analyzeBtn.onclick = () => window.open(SECRETS_URL, '_blank', 'noopener,noreferrer');
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

  async function syncState() {
    try {
      const state = await readRunStatus();
      if (!state) return;
      currentStatus = state.status || null;
      configureMainButton(currentStatus);
      if (currentStatus === 'RUNNING') setRunState('Analisando jogos de hoje...');
      else if (currentStatus === 'SUCCESS') {
        const count = Number(state.tickets_ready || 0);
        setRunState(`${count}/3 bilhetes prontos • GitHub Actions`);
      } else if (currentStatus === 'WAITING_FOR_API_KEY') {
        setRunState('Falta configurar API_FOOTBALL_KEY no GitHub');
      } else if (currentStatus === 'FAILED') setRunState('Última análise falhou • ver Actions');
      else setRunState('Motor GitHub ativo');
    } catch (_) {
      setRunState('Motor GitHub ativo');
      configureMainButton(currentStatus);
    }
  }

  if (analyzeBtn) configureMainButton(null);
  if (refreshBtn) refreshBtn.onclick = () => location.reload();

  syncState();
  setInterval(syncState, 30000);
})();
