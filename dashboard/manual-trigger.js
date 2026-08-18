(() => {
  const ACTIONS_URL = 'https://github.com/stepoil-debug/douglas/actions/workflows/analyze-football.yml';
  const SECRETS_URL = 'https://github.com/stepoil-debug/douglas/settings/secrets/actions/new';
  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const refreshBtn = $('refreshBtn');
  const runState = $('runState');
  let currentStatus = null;

  function setRunState(text) {
    if (runState && runState.textContent !== text) runState.textContent = text;
  }

  function ensureManagementNav() {
    const nav = document.querySelector('.nav');
    if (!nav || nav.querySelector('[data-management-nav]')) return;
    const link = document.createElement('a');
    link.href = 'gestao.html';
    link.dataset.managementNav = '1';
    link.innerHTML = '📈 <span>Gestão simulada</span>';
    const second = nav.children[1];
    if (second) nav.insertBefore(link, second);
    else nav.appendChild(link);
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
        ? '▶ Rodar novamente'
        : '▶ Rodar agora';
    if (analyzeBtn.textContent !== nextText) analyzeBtn.textContent = nextText;
    analyzeBtn.disabled = state === 'RUNNING';
    analyzeBtn.onclick = () => window.open(ACTIONS_URL, '_blank', 'noopener,noreferrer');
  }

  async function syncState() {
    try {
      const response = await fetch(`./run_status.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) return;
      const state = await response.json();
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
  if (analyzeBtn) configureMainButton(null);
  if (refreshBtn) refreshBtn.onclick = () => location.reload();

  // Sem MutationObserver: ele causava um ciclo de DOM que podia travar o navegador.
  syncState();
  setInterval(syncState, 120000);
})();
