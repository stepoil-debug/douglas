(() => {
  const OWNER = 'stepoil-debug';
  const REPO = 'douglas';
  const WORKFLOW = 'analyze.yml';
  const REF = 'main';
  const API = 'https://api.github.com';
  const TOKEN_KEY = 'tqe_github_token';
  const API_VERSION = '2026-03-10';
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  const $ = id => document.getElementById(id);
  const analyzeBtn = $('analyzeBtn');
  const actions = analyzeBtn?.parentElement;
  const runState = $('runState');
  const oldTip = $('manualTip');
  if (!analyzeBtn || !actions) return;
  if (oldTip) oldTip.remove();

  function token() {
    return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || '';
  }

  function setRunState(text) {
    if (runState) runState.textContent = text;
  }

  function setBusy(busy) {
    analyzeBtn.disabled = busy;
    analyzeBtn.textContent = busy ? '⏳ Analisando...' : '▶ Fazer análise agora';
    if (configBtn) configBtn.disabled = busy;
  }

  function ensureDialog() {
    let dialog = $('githubTokenDialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'githubTokenDialog';
    dialog.innerHTML = `
      <form method="dialog" style="margin:0">
        <div class="token-modal-head">
          <div><div class="token-eyebrow">Execução direta</div><h2>Conectar ao GitHub Actions</h2></div>
          <button value="cancel" class="token-close" aria-label="Fechar">×</button>
        </div>
        <div class="token-modal-body">
          <label class="token-field">GitHub token
            <input id="githubTokenInput" type="password" autocomplete="off" placeholder="github_pat_... ou ghp_...">
          </label>
          <p>Use um token restrito ao repositório <b>stepoil-debug/douglas</b> com permissão <b>Actions: Read and write</b>. Ele é usado somente pelo seu navegador para iniciar o workflow.</p>
          <label class="token-check"><input id="rememberGithubToken" type="checkbox" checked> Salvar neste navegador</label>
          <div id="tokenModalError" class="token-error"></div>
        </div>
        <div class="token-modal-actions">
          <button id="clearGithubToken" type="button" class="token-btn secondary">Limpar</button>
          <button value="cancel" class="token-btn secondary">Cancelar</button>
          <button id="saveGithubToken" type="button" class="token-btn primary">Salvar e analisar</button>
        </div>
      </form>`;
    document.body.appendChild(dialog);

    const style = document.createElement('style');
    style.textContent = `
      #githubTokenDialog{width:min(590px,calc(100% - 28px));padding:0;border:1px solid rgba(216,168,47,.32);border-radius:18px;background:#08170f;color:#f5f2e8;box-shadow:0 30px 90px rgba(0,0,0,.68)}
      #githubTokenDialog::backdrop{background:rgba(1,8,5,.78);backdrop-filter:blur(5px)}
      .token-modal-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:22px 24px;border-bottom:1px solid rgba(216,168,47,.14);background:linear-gradient(120deg,rgba(216,168,47,.08),transparent)}
      .token-modal-head h2{margin:4px 0 0;font-size:21px}.token-eyebrow{font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:#d8a82f;font-weight:900}.token-close{border:0;background:transparent;color:#8ca696;font-size:28px;cursor:pointer;line-height:1}
      .token-modal-body{padding:22px 24px}.token-field{display:grid;gap:8px;font-size:12px;font-weight:900;color:#dfe8e1}.token-field input{width:100%;padding:12px 13px;border-radius:10px;border:1px solid #294735;background:#06110b;color:#f5f2e8;font:inherit}.token-modal-body p{font-size:11px;line-height:1.6;color:#8ca696;margin:13px 0}.token-check{display:flex;align-items:center;gap:8px;font-size:11px;color:#a9bdaf}.token-error{min-height:18px;margin-top:10px;color:#ff8f98;font-size:11px}
      .token-modal-actions{display:flex;justify-content:flex-end;gap:9px;padding:0 24px 22px}.token-btn{padding:10px 13px;border-radius:10px;border:1px solid #294735;font-weight:900;cursor:pointer}.token-btn.primary{color:#1b1606;border-color:rgba(216,168,47,.42);background:linear-gradient(135deg,#f0cb67,#c7941e)}.token-btn.secondary{color:#d7e4da;background:#0a1a12}
      .manual-config-btn{padding:10px 11px!important;min-width:42px}
      @media(max-width:720px){.token-modal-actions{flex-wrap:wrap}.token-btn{flex:1}.manual-config-btn{display:none}}
    `;
    document.head.appendChild(style);

    $('clearGithubToken').onclick = () => {
      localStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem(TOKEN_KEY);
      $('githubTokenInput').value = '';
      $('tokenModalError').textContent = 'Token removido deste navegador.';
    };
    $('saveGithubToken').onclick = async () => {
      const value = $('githubTokenInput').value.trim();
      if (!value) {
        $('tokenModalError').textContent = 'Informe o token do GitHub.';
        return;
      }
      const remember = $('rememberGithubToken').checked;
      const store = remember ? localStorage : sessionStorage;
      const other = remember ? sessionStorage : localStorage;
      other.removeItem(TOKEN_KEY);
      store.setItem(TOKEN_KEY, value);
      dialog.close();
      await startAnalysis();
    };
    return dialog;
  }

  function openConfig() {
    const dialog = ensureDialog();
    $('githubTokenInput').value = token();
    $('tokenModalError').textContent = '';
    dialog.showModal();
    setTimeout(() => $('githubTokenInput')?.focus(), 20);
  }

  const configBtn = document.createElement('button');
  configBtn.id = 'manualConfigBtn';
  configBtn.type = 'button';
  configBtn.className = 'btn secondary manual-config-btn';
  configBtn.title = 'Configurar token do GitHub';
  configBtn.textContent = '⚙';
  configBtn.onclick = openConfig;
  actions.insertBefore(configBtn, $('refreshBtn'));

  async function gh(path, options = {}) {
    const value = token();
    if (!value) throw new Error('TOKEN_MISSING');
    const headers = {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${value}`,
      'X-GitHub-Api-Version': API_VERSION,
      ...(options.headers || {})
    };
    const response = await fetch(`${API}${path}`, {...options, headers});
    if (!response.ok) {
      let message = response.statusText;
      try { message = (await response.json()).message || message; } catch {}
      throw new Error(`GITHUB_${response.status}:${message}`);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function findRecentRun(startedAt) {
    for (let i = 0; i < 10; i++) {
      await sleep(1500);
      const data = await gh(`/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/runs?event=workflow_dispatch&branch=${REF}&per_page=10`);
      const run = (data.workflow_runs || []).find(r => new Date(r.created_at).getTime() >= startedAt - 5000);
      if (run) return run;
    }
    throw new Error('RUN_NOT_FOUND');
  }

  async function pollRun(run) {
    let current = run;
    for (let i = 0; i < 240; i++) {
      if (current.status === 'completed') return current;
      setRunState(current.status === 'queued' ? 'Análise na fila...' : 'Análise em andamento...');
      await sleep(3000);
      current = await gh(`/repos/${OWNER}/${REPO}/actions/runs/${current.id}`);
    }
    throw new Error('RUN_TIMEOUT');
  }

  async function waitForPublishedData(previousRunAt) {
    for (let i = 0; i < 30; i++) {
      await sleep(2500);
      try {
        const response = await fetch(`./data.json?t=${Date.now()}`, {cache:'no-store'});
        if (!response.ok) continue;
        const data = await response.json();
        if (!previousRunAt || (data.last_run_at && data.last_run_at !== previousRunAt)) return true;
      } catch {}
    }
    return false;
  }

  async function startAnalysis() {
    if (!token()) {
      openConfig();
      return;
    }
    setBusy(true);
    const startedAt = Date.now();
    let previousRunAt = null;
    try {
      try {
        const response = await fetch(`./data.json?t=${Date.now()}`, {cache:'no-store'});
        if (response.ok) previousRunAt = (await response.json()).last_run_at || null;
      } catch {}

      setRunState('Disparando análise...');
      const dispatch = await gh(`/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ref: REF})
      });

      let run;
      if (dispatch?.workflow_run_id) {
        run = await gh(`/repos/${OWNER}/${REPO}/actions/runs/${dispatch.workflow_run_id}`);
      } else {
        run = await findRecentRun(startedAt);
      }
      run = await pollRun(run);
      if (run.conclusion !== 'success') throw new Error(`RUN_${String(run.conclusion || 'UNKNOWN').toUpperCase()}`);

      setRunState('Publicando resultados...');
      await waitForPublishedData(previousRunAt);
      if (typeof window.refreshAll === 'function') await window.refreshAll();
      else location.reload();
      setRunState('Análise concluída');
    } catch (error) {
      const text = String(error?.message || error);
      if (text === 'TOKEN_MISSING') {
        openConfig();
      } else if (text.startsWith('GITHUB_401')) {
        setRunState('Token inválido');
        openConfig();
        $('tokenModalError').textContent = 'Token inválido. Confira e salve novamente.';
      } else if (text.startsWith('GITHUB_403')) {
        setRunState('Token sem permissão');
        openConfig();
        $('tokenModalError').textContent = 'O token precisa de Actions: Read and write neste repositório.';
      } else if (text.startsWith('RUN_')) {
        setRunState('Análise não concluída');
        alert(`A execução terminou sem sucesso: ${text.replace('RUN_','')}`);
      } else {
        setRunState('Falha ao analisar');
        alert(`Não foi possível iniciar/concluir a análise: ${text}`);
      }
    } finally {
      setBusy(false);
    }
  }

  analyzeBtn.onclick = startAnalysis;
})();
