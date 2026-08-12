(() => {
  const $ = id => document.getElementById(id);
  const box = $('historyBox');
  const select = $('historySelect');
  if (!box || !select) return;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = value => value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`;
  const num = (value, digits = 1) => value == null ? '—' : Number(value).toFixed(digits);
  const br = value => {
    if (!value) return '—';
    const [y,m,d] = String(value).slice(0,10).split('-');
    return `${d}/${m}/${y}`;
  };
  const priority = name => {
    const preferred = ['bet365','betano','betfair','superbet','sportingbet','kto','novibet','pixbet','estrelabet','rivalo'];
    const n = String(name || '').toLowerCase().replace(/\s+/g, '');
    const i = preferred.findIndex(x => n.includes(x));
    return i < 0 ? 999 : i;
  };
  const getJson = async url => {
    const r = await fetch(`${url}${url.includes('?') ? '&' : '?'}v=${Date.now()}`, {cache:'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  };

  const style = document.createElement('style');
  style.textContent = `
    .audit-summary{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;margin-bottom:14px}
    .audit-stat{padding:13px;border:1px solid rgba(117,157,130,.12);background:#08170f}.audit-stat small{display:block;font-size:8px;color:#6c8373;text-transform:uppercase;letter-spacing:.08em}.audit-stat b{display:block;font-size:20px;margin-top:5px}
    .audit-note{padding:12px 14px;margin-bottom:12px;border:1px solid rgba(216,168,47,.17);background:rgba(216,168,47,.05);color:#a9b9ad;font-size:11px;line-height:1.55}
    .audit-list{display:grid;gap:10px}.audit-game{border:1px solid rgba(117,157,130,.14);background:linear-gradient(150deg,#0c1e15,#07150e);overflow:hidden}.audit-game-head{display:flex;justify-content:space-between;gap:18px;padding:15px 17px;border-bottom:1px solid rgba(117,157,130,.09)}
    .audit-date{display:inline-block;color:#f0cb67;font-weight:900;font-size:10px;letter-spacing:.06em;margin-bottom:4px}.audit-match{font-size:15px;font-weight:900}.audit-meta{font-size:10px;color:#738a7b;margin-top:4px}.audit-outcome{align-self:flex-start;padding:7px 9px;border-radius:8px;font-size:10px;font-weight:900;white-space:nowrap}.audit-outcome.hit{color:#91efb8;background:rgba(117,229,166,.11)}.audit-outcome.miss{color:#ffa0a7;background:rgba(255,119,128,.1)}.audit-outcome.pending{color:#e9ca75;background:rgba(216,168,47,.08)}.audit-outcome.final{color:#b7c5bc;background:rgba(117,157,130,.08)}
    .audit-pred{padding:14px 17px}.audit-pred-title{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.audit-pred-title b{font-size:14px}.audit-grid{display:grid;grid-template-columns:repeat(6,minmax(85px,1fr));gap:9px;margin-top:12px}.audit-metric{padding:9px 10px;border:1px solid rgba(117,157,130,.1);background:#08170f}.audit-metric small{display:block;font-size:8px;color:#667e6e;text-transform:uppercase;letter-spacing:.07em}.audit-metric b{display:block;font-size:13px;margin-top:4px}
    .audit-signals{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.audit-chip{padding:5px 7px;border-radius:7px;background:#0d2619;border:1px solid #244331;color:#9cb0a1;font-size:9px}.audit-chip strong{color:#f0e9d4;margin-left:3px}.audit-reasons{margin-top:9px;color:#d6a6aa;font-size:10px}.audit-books{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}.audit-book{padding:5px 7px;border:1px solid #294a35;background:#0b2116;color:#9eb3a4;font-size:9px;border-radius:7px}.audit-book.priority{border-color:rgba(216,168,47,.38);color:#f1d887;background:rgba(216,168,47,.07)}
    @media(max-width:950px){.audit-summary{grid-template-columns:repeat(3,1fr)}.audit-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:620px){.audit-summary,.audit-grid{grid-template-columns:1fr 1fr}.audit-game-head{display:block}.audit-outcome{display:inline-block;margin-top:9px}}
  `;
  document.head.appendChild(style);

  function selectedAnalysis(game) {
    const rows = game?.analyses || [];
    if (!rows.length) return null;
    return [...rows].sort((a,b) => Number(b.final_probability || 0) - Number(a.final_probability || 0))[0];
  }

  function outcome(game, analysis) {
    const result = game?.result || {};
    if (!result.resolved) return {label:'PENDENTE', cls:'pending'};
    if (!analysis?.selected_player?.key) return {label:'FINALIZADO', cls:'final'};
    return String(analysis.selected_player.key) === String(result.winner?.key)
      ? {label:'HIT', cls:'hit'}
      : {label:'MISS', cls:'miss'};
  }

  function signalChips(signals = {}) {
    const labels = {market:'Mercado',elo:'Elo',surface_elo:'Elo superfície',ranking:'Ranking',recent_form:'Forma',season_profile:'Temporada',fatigue:'Fadiga',serve:'Saque',return:'Retorno',h2h:'H2H'};
    return Object.entries(signals).map(([k,v]) => `<span class="audit-chip">${esc(labels[k] || k)} <strong>${pct(v)}</strong></span>`).join('');
  }

  function bookmakerChips(game, analysis) {
    if (!analysis?.selected_player?.key) return '';
    const key = String(analysis.selected_player.key);
    const aKey = String(game?.player_a?.key || '');
    const rows = key === aKey ? (game?.market?.home || []) : (game?.market?.away || []);
    return [...rows]
      .sort((a,b) => priority(a.bookmaker)-priority(b.bookmaker) || Number(b.odd || 0)-Number(a.odd || 0))
      .slice(0,10)
      .map(b => `<span class="audit-book ${priority(b.bookmaker)<999?'priority':''}">${esc(b.bookmaker)} <b>${num(b.odd,2)}</b></span>`).join('');
  }

  function gameCard(game) {
    const a = selectedAnalysis(game);
    const o = outcome(game, a);
    const r = game.result || {};
    const decision = a?.status || 'SEM ANÁLISE PROFUNDA';
    const prediction = a?.selected_player?.name ? `${esc(a.selected_player.name)} para vencer` : 'Jogo registrado sem previsão profunda';
    const reasons = (a?.reject_reasons || []).join(' • ');
    return `<article class="audit-game">
      <div class="audit-game-head">
        <div>
          <span class="audit-date">${br(game.date)}</span>
          <div class="audit-match">${esc(game.player_a?.name)} <span style="color:#6f8878">vs</span> ${esc(game.player_b?.name)}</div>
          <div class="audit-meta">${esc(game.tournament || 'ATP')} • ${esc(game.time || 'horário n/d')} • ${esc(game.surface || 'superfície n/d')}</div>
          <div class="audit-meta">${r.resolved ? `Vencedor: ${esc(r.winner?.name || '—')} • Placar final: ${esc(r.score || '—')}` : 'Resultado ainda não reconciliado'}</div>
        </div>
        <span class="audit-outcome ${o.cls}">${o.label}</span>
      </div>
      <div class="audit-pred">
        <div class="audit-pred-title"><span class="status ${(decision || '').toLowerCase()}">${esc(decision)}</span><b>${prediction}</b></div>
        ${a ? `<div class="audit-grid">
          <div class="audit-metric"><small>Odd analisada</small><b>${num(a.odd,2)}</b></div>
          <div class="audit-metric"><small>Probabilidade</small><b>${pct(a.final_probability)}</b></div>
          <div class="audit-metric"><small>Confiança</small><b>${num(a.confidence)}</b></div>
          <div class="audit-metric"><small>Edge</small><b>${num(a.edge_pp)} pp</b></div>
          <div class="audit-metric"><small>Qualidade dados</small><b>${pct(a.data_quality)}</b></div>
          <div class="audit-metric"><small>Discordância</small><b>${num(a.disagreement_pp)} pp</b></div>
        </div>
        <div class="audit-signals">${signalChips(a.signals || {})}</div>
        ${reasons ? `<div class="audit-reasons"><b>Motivos da decisão:</b> ${esc(reasons)}</div>` : '<div class="audit-reasons" style="color:#8fdcab">Passou pelos filtros registrados.</div>'}
        <div class="audit-books">${bookmakerChips(game,a)}</div>` : '<div class="audit-meta" style="margin-top:9px">O confronto ficou salvo no ledger, porém não chegou à análise profunda do modelo nessa rodada.</div>'}
      </div>
    </article>`;
  }

  async function renderDay(day) {
    box.innerHTML = '<div class="empty">Carregando auditoria completa...</div>';
    let ledger;
    try { ledger = await getJson(`history/${day}.json`); }
    catch { box.innerHTML = '<div class="empty">Sem histórico publicado para esta data.</div>'; return; }
    const games = ledger.games || [];
    const analyzed = games.filter(g => (g.analyses || []).length > 0);
    const resolvedAnalyzed = analyzed.filter(g => g.result?.resolved);
    const hits = resolvedAnalyzed.filter(g => outcome(g, selectedAnalysis(g)).label === 'HIT').length;
    const misses = resolvedAnalyzed.length - hits;
    const accuracy = resolvedAnalyzed.length ? `${(hits / resolvedAnalyzed.length * 100).toFixed(1)}%` : '—';
    const approved = analyzed.filter(g => (g.analyses || []).some(a => a.status === 'APPROVED')).length;
    box.innerHTML = `
      <div class="audit-summary">
        <div class="audit-stat"><small>Jogos salvos</small><b>${games.length}</b></div>
        <div class="audit-stat"><small>Analisados</small><b>${analyzed.length}</b></div>
        <div class="audit-stat"><small>Resolvidos</small><b>${resolvedAnalyzed.length}</b></div>
        <div class="audit-stat"><small>HIT</small><b class="good">${hits}</b></div>
        <div class="audit-stat"><small>MISS</small><b class="bad">${misses}</b></div>
        <div class="audit-stat"><small>Acerto modelo</small><b class="gold">${accuracy}</b></div>
      </div>
      <div class="audit-note"><b>${br(day)}:</b> esta tela preserva o que o robô analisou antes do jogo. Resultado e placar são acrescentados depois, sem reescrever probabilidade, confiança, edge ou sinais originais.</div>
      <div class="audit-list">${games.length ? games.map(gameCard).join('') : '<div class="empty">Nenhum jogo salvo.</div>'}</div>`;
  }

  async function boot() {
    let data, index;
    try { [data,index] = await Promise.all([getJson('data.json'), getJson('history/index.json')]); }
    catch { return; }
    const dates = index.dates || [];
    if (!dates.length) return;
    const operational = data.operational_date || new Date().toISOString().slice(0,10);
    const previousDates = dates.map(x => x.date).filter(d => d < operational).sort().reverse();
    const preferred = previousDates[0] || dates[0].date;
    select.innerHTML = dates.map(x => `<option value="${esc(x.date)}" ${x.date===preferred?'selected':''}>${br(x.date)} • ${x.summary?.games || 0} jogos</option>`).join('');
    select.onchange = () => renderDay(select.value);
    await renderDay(preferred);
  }

  // v2 renders a compact history first; replace it with the complete audit after load.
  setTimeout(() => boot().catch(console.error), 250);
})();
