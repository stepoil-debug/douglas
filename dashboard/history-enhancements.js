(() => {
  const dateOf = (row, fallback) => row?.date || row?.match?.date || fallback || '';
  const primaryAnalysis = game => {
    const rows = game?.analyses || [];
    if (!rows.length) return null;
    return [...rows].sort((a, b) => Number(b.final_probability || 0) - Number(a.final_probability || 0))[0];
  };
  const outcome = (game, analysis) => {
    if (!analysis) return 'SEM PREVISÃO';
    const result = game?.result || {};
    if (!result.resolved) return 'PENDING';
    const selected = analysis?.selected_player?.key;
    const winner = result?.winner?.key;
    if (!selected || !winner) return 'PENDING';
    return String(selected) === String(winner) ? 'HIT' : 'MISS';
  };
  const outcomeTag = value => {
    const cls = value === 'HIT' ? 'hit' : value === 'MISS' ? 'miss' : 'pending';
    return `<span class="tag ${cls}">${esc(value)}</span>`;
  };
  const priorityBook = name => {
    const preferred = ['bet365','betano','betfair','superbet','sportingbet','kto','novibet','pixbet','estrelabet','rivalo'];
    const n = String(name || '').toLowerCase().replace(/\s+/g, '');
    const i = preferred.findIndex(x => n.includes(x));
    return i < 0 ? 999 : i;
  };
  const sideBooks = (game, analysis) => {
    if (!analysis?.selected_player?.key) return [];
    const selected = String(analysis.selected_player.key);
    const aKey = String(game?.player_a?.key || '');
    const rows = selected === aKey ? (game?.market?.home || []) : (game?.market?.away || []);
    return [...rows].sort((a,b) => priorityBook(a.bookmaker)-priorityBook(b.bookmaker) || Number(b.odd || 0)-Number(a.odd || 0));
  };
  const signalLabels = {market:'Mercado',elo:'Elo',surface_elo:'Elo superfície',ranking:'Ranking ATP',recent_form:'Forma recente',season_profile:'Temporada',fatigue:'Fadiga',serve:'Saque',return:'Retorno',h2h:'H2H'};

  const style = document.createElement('style');
  style.textContent = `
    .history-audit-summary{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;margin-bottom:14px}
    .history-audit-stat{padding:13px;border:1px solid rgba(117,157,130,.12);background:#08170f}.history-audit-stat small{display:block;font-size:8px;color:#6c8373;text-transform:uppercase;letter-spacing:.08em}.history-audit-stat b{display:block;font-size:20px;margin-top:5px}
    .history-audit-note{padding:12px 14px;margin-bottom:12px;border:1px solid rgba(216,168,47,.17);background:rgba(216,168,47,.05);color:#a9b9ad;font-size:11px;line-height:1.55}
    .history-audit-list{display:grid;gap:10px}.history-audit-game{border:1px solid rgba(117,157,130,.14);background:linear-gradient(150deg,#0c1e15,#07150e);overflow:hidden}.history-audit-head{display:flex;justify-content:space-between;gap:18px;padding:15px 17px;border-bottom:1px solid rgba(117,157,130,.09)}
    .history-audit-date{display:inline-block;color:#f0cb67;font-weight:900;font-size:10px;letter-spacing:.06em;margin-bottom:4px}.history-audit-match{font-size:15px;font-weight:900}.history-audit-meta{font-size:10px;color:#738a7b;margin-top:4px}.history-audit-result{align-self:flex-start;padding:7px 9px;border-radius:8px;font-size:10px;font-weight:900;white-space:nowrap}.history-audit-result.hit{color:#91efb8;background:rgba(117,229,166,.11)}.history-audit-result.miss{color:#ffa0a7;background:rgba(255,119,128,.1)}.history-audit-result.pending{color:#e9ca75;background:rgba(216,168,47,.08)}.history-audit-result.final{color:#b7c5bc;background:rgba(117,157,130,.08)}
    .history-audit-body{padding:14px 17px}.history-audit-title{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.history-audit-title b{font-size:14px}.history-audit-grid{display:grid;grid-template-columns:repeat(6,minmax(85px,1fr));gap:9px;margin-top:12px}.history-audit-metric{padding:9px 10px;border:1px solid rgba(117,157,130,.1);background:#08170f}.history-audit-metric small{display:block;font-size:8px;color:#667e6e;text-transform:uppercase;letter-spacing:.07em}.history-audit-metric b{display:block;font-size:13px;margin-top:4px}
    .history-audit-signals,.history-audit-books{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.history-audit-chip{padding:5px 7px;border-radius:7px;background:#0d2619;border:1px solid #244331;color:#9cb0a1;font-size:9px}.history-audit-chip strong{color:#f0e9d4;margin-left:3px}.history-audit-reasons{margin-top:9px;color:#d6a6aa;font-size:10px}.history-audit-book{padding:5px 7px;border:1px solid #294a35;background:#0b2116;color:#9eb3a4;font-size:9px;border-radius:7px}.history-audit-book.priority{border-color:rgba(216,168,47,.38);color:#f1d887;background:rgba(216,168,47,.07)}
    @media(max-width:950px){.history-audit-summary{grid-template-columns:repeat(3,1fr)}.history-audit-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:620px){.history-audit-summary,.history-audit-grid{grid-template-columns:1fr 1fr}.history-audit-head{display:block}.history-audit-result{display:inline-block;margin-top:9px}}
  `;
  document.head.appendChild(style);

  const signalChips = signals => Object.entries(signals || {}).map(([k,v]) => `<span class="history-audit-chip">${esc(signalLabels[k] || k)} <strong>${pct(v)}</strong></span>`).join('');
  const bookmakerChips = (game, analysis) => sideBooks(game, analysis).slice(0,10).map(b => `<span class="history-audit-book ${priorityBook(b.bookmaker)<999?'priority':''}">${esc(b.bookmaker)} <b>${num(b.odd,2)}</b></span>`).join('');

  const auditGame = (g, day) => {
    const a = primaryAnalysis(g);
    const result = outcome(g, a);
    const cls = result === 'HIT' ? 'hit' : result === 'MISS' ? 'miss' : result === 'PENDING' ? 'pending' : 'final';
    const final = g.result || {};
    const prediction = a ? `${esc(a.selected_player?.name)} para vencer` : 'Jogo salvo sem análise profunda';
    const decision = a?.status || 'SEM ANÁLISE';
    const reasons = (a?.reject_reasons || []).join(' • ');
    return `<article class="history-audit-game">
      <div class="history-audit-head">
        <div>
          <span class="history-audit-date">📅 ${br(g.date || day)}</span>
          <div class="history-audit-match">${esc(g.player_a?.name)} <span style="color:#6f8878">vs</span> ${esc(g.player_b?.name)}</div>
          <div class="history-audit-meta">${esc(g.tournament || 'ATP')} • ${esc(g.time || 'horário n/d')} • ${esc(g.surface || 'superfície n/d')}</div>
          <div class="history-audit-meta">${final.resolved ? `Vencedor: ${esc(final.winner?.name || '—')} • Placar final: ${esc(final.score || '—')}` : 'Resultado ainda não reconciliado'}</div>
        </div>
        <span class="history-audit-result ${cls}">${esc(result)}</span>
      </div>
      <div class="history-audit-body">
        <div class="history-audit-title">${a ? statusTag(decision) : '<span class="tag pending">SEM ANÁLISE</span>'}<b>${prediction}</b></div>
        ${a ? `<div class="history-audit-grid">
          <div class="history-audit-metric"><small>Odd analisada</small><b>${num(a.odd,2)}</b></div>
          <div class="history-audit-metric"><small>Probabilidade</small><b>${pct(a.final_probability)}</b></div>
          <div class="history-audit-metric"><small>Confiança</small><b>${num(a.confidence)}</b></div>
          <div class="history-audit-metric"><small>Edge</small><b>${num(a.edge_pp)} pp</b></div>
          <div class="history-audit-metric"><small>Qualidade dados</small><b>${pct(a.data_quality)}</b></div>
          <div class="history-audit-metric"><small>Discordância</small><b>${num(a.disagreement_pp)} pp</b></div>
        </div>
        <div class="history-audit-signals">${signalChips(a.signals)}</div>
        <div class="history-audit-reasons">${reasons ? `<b>Motivos da decisão:</b> ${esc(reasons)}` : '<span style="color:#8fdcab">Passou pelos filtros registrados.</span>'}</div>
        <div class="history-audit-books">${bookmakerChips(g,a) || '<span class="mini">Sem casas detalhadas nessa coleta.</span>'}</div>` : '<div class="history-audit-meta" style="margin-top:9px">O confronto foi salvo no dia, mas não passou para a análise profunda do modelo.</div>'}
      </div>
    </article>`;
  };

  // Keep the date visible inside every approved card, not only in the board header.
  pickCard = function(r, ledger) {
    const m = r.match || {}, p = r.selected_player || {}, o = r.opponent || {};
    const g = (ledger?.games || []).find(x => x.match_id === m.match_id);
    const books = marketFor(g, p.key);
    const gameDate = dateOf(m, g?.date || ledger?.date);
    return `<article class="card pick"><div class="pick-top"><div><div class="label">Entrada aprovada</div><div class="pick-name">${esc(p.name)} para vencer</div><div class="meta">📅 ${br(gameDate)} • ${esc(m.time || g?.time || 'horário n/d')} • vs ${esc(o.name)} • ${esc(m.tournament || g?.tournament || 'ATP')}</div></div><span class="status approved">PODE ENTRAR</span></div><div class="pick-grid"><div class="metric"><small>Odd alvo</small><b class="gold">${num(r.selected_market?.best_odd, 2)}</b></div><div class="metric"><small>Probabilidade</small><b>${pct(r.final_probability)}</b></div><div class="metric"><small>Confiança</small><b>${num(r.confidence)}</b></div><div class="metric"><small>Edge</small><b>${num(r.edge_pp)} pp</b></div><div class="metric"><small>Qualidade</small><b>${pct(r.data_quality)}</b></div></div><div class="books">${bookHtml(books)}</div></article>`;
  };

  renderToday = function(x) {
    const rows = x?.matches || [];
    const resolved = rows.filter(r => ['HIT', 'MISS'].includes(r.result?.status));
    const hits = resolved.filter(r => r.result?.status === 'HIT').length;
    $('tResolved').textContent = resolved.length;
    $('tHits').textContent = hits;
    $('tMisses').textContent = resolved.length - hits;
    $('tAcc').textContent = resolved.length ? `${(hits / resolved.length * 100).toFixed(1)}%` : '—';
    $('todayRows').innerHTML = rows.length ? rows.map(r => `<tr><td><div class="pred">${esc(r.predicted_player?.name)} para vencer</div><div class="mini">📅 ${br(dateOf(r, x?.date))} • ${esc(r.time || 'horário n/d')} • vs ${esc(r.opponent?.name)} • ${esc(r.tournament || '')}</div></td><td>${statusTag(r.decision)}</td><td>${outcomeTag(r.result?.status || 'PENDING')}${r.result?.winner?.name ? `<div class="mini">Vencedor: ${esc(r.result.winner.name)}</div>` : ''}</td><td>${esc(r.result?.score || '—')}</td></tr>`).join('') : '<tr><td colspan="4">Ainda não existe board oficial para hoje ou os jogos continuam pendentes.</td></tr>';
  };

  render = async function() {
    const d = await j('data.json');
    $('boardDate').textContent = br(d.board_date || d.date);
    $('todayDate').textContent = br(d.operational_date);
    $('kFixtures').textContent = d.fixtures_analyzed || 0;
    $('kOdds').textContent = d.matches_with_odds || 0;
    $('kDeep').textContent = d.deep_analyzed_matches || 0;
    $('kApproved').textContent = (d.approved || []).length;
    $('kLearn').textContent = d.knowledge?.overall?.n || 0;
    $('model').textContent = d.model_version || '—';

    let ledger = null, learning = null, today = null;
    try { ledger = await j(`history/${d.board_date}.json`); } catch {}
    try { learning = await j(`learning/${d.board_date}.json`); } catch {}
    try { today = await j(`learning/${d.operational_date}.json`); } catch {}

    const aps = d.approved || [];
    $('approvedList').innerHTML = aps.length ? aps.map(x => pickCard(x, ledger)).join('') : '<div class="empty">Nenhuma entrada aprovada até agora. O motor continuará buscando novos jogos e odds de amanhã sem forçar 10 seleções.</div>';

    const rows = learning?.matches || [];
    $('allCount').textContent = `${rows.length} confrontos com opinião do modelo`;
    $('allRows').innerHTML = rows.length ? rows.map(r => `<tr><td><div class="pred">${esc(r.predicted_player?.name)} para vencer</div><div class="mini">📅 ${br(dateOf(r, d.board_date))} • ${esc(r.time || 'horário n/d')} • vs ${esc(r.opponent?.name)} • ${esc(r.tournament || 'ATP')}</div></td><td>${statusTag(r.decision)}</td><td>${num(r.odd, 2)}</td><td>${pct(r.final_probability)}</td><td>${num(r.confidence)}</td><td>${num(r.edge_pp)} pp</td><td><div class="mini">${esc((r.reject_reasons || []).join(' • ') || 'Aprovado')}</div></td></tr>`).join('') : '<tr><td colspan="7">Aguardando jogos de amanhã.</td></tr>';

    renderToday(today);
    renderKnowledge(d.knowledge || {});
    await initHistory(d.operational_date);
    return d;
  };

  initHistory = async function(prefer) {
    let idx;
    try { idx = await j('history/index.json'); }
    catch { $('historyBox').textContent = 'Histórico ainda não publicado.'; return; }
    const dates = idx.dates || [];
    const sel = $('historySelect');
    const old = sel.value;
    const previousCompleted = dates.find(x => x.date < prefer);
    const preferred = old && dates.some(x => x.date === old) ? old : (previousCompleted?.date || prefer || dates[0]?.date || '');
    sel.innerHTML = dates.map(x => {
      const s = x.summary || {};
      const resolved = s.resolved_model_picks ?? 0;
      const suffix = resolved ? ` • ${s.model_hits || 0}H/${s.model_misses || 0}M` : ` • ${s.games || 0} jogos`;
      return `<option value="${esc(x.date)}" ${preferred === x.date ? 'selected' : ''}>${br(x.date)}${suffix}</option>`;
    }).join('');
    sel.onchange = () => loadHistory(sel.value);
    if (sel.value) await loadHistory(sel.value);
  };

  loadHistory = async function(day) {
    let x;
    try { x = await j(`history/${day}.json`); }
    catch { $('historyBox').innerHTML = '<div class="empty">Sem registro para esta data.</div>'; return; }

    const games = x.games || [];
    const analyzed = games.filter(g => primaryAnalysis(g));
    const resolved = analyzed.filter(g => ['HIT', 'MISS'].includes(outcome(g, primaryAnalysis(g))));
    const hits = resolved.filter(g => outcome(g, primaryAnalysis(g)) === 'HIT').length;
    const misses = resolved.length - hits;
    const officialApproved = games.reduce((n, g) => n + (g.analyses || []).filter(a => a.status === 'APPROVED').length, 0);
    const officialResolved = games.reduce((n, g) => n + (g.analyses || []).filter(a => a.status === 'APPROVED' && g.result?.resolved).length, 0);
    const officialHits = games.reduce((n, g) => {
      const winner = g.result?.winner?.key;
      return n + (g.analyses || []).filter(a => a.status === 'APPROVED' && g.result?.resolved && String(a.selected_player?.key) === String(winner)).length;
    }, 0);
    const officialMisses = Math.max(0, officialResolved - officialHits);

    $('historyBox').innerHTML = `
      <div class="history-audit-summary">
        <div class="history-audit-stat"><small>Jogos salvos</small><b>${games.length}</b></div>
        <div class="history-audit-stat"><small>Analisados</small><b>${analyzed.length}</b></div>
        <div class="history-audit-stat"><small>Resolvidos</small><b>${resolved.length}</b></div>
        <div class="history-audit-stat"><small>HIT</small><b class="good">${hits}</b></div>
        <div class="history-audit-stat"><small>MISS</small><b class="bad">${misses}</b></div>
        <div class="history-audit-stat"><small>Acerto modelo</small><b class="gold">${resolved.length ? (hits / resolved.length * 100).toFixed(1) + '%' : '—'}</b></div>
      </div>
      <div class="history-audit-note"><b>${br(day)}:</b> lista permanente do que o robô analisou antes das partidas. Probabilidade, confiança, edge, sinais e decisão ficam congelados; depois acrescentamos apenas vencedor, placar e HIT/MISS. Entradas oficiais: <b>${officialApproved}</b> • resolvidas: <b>${officialResolved}</b> • ${officialHits} WIN / ${officialMisses} LOSS.</div>
      <div class="history-audit-list">${games.length ? games.map(g => auditGame(g, day)).join('') : '<div class="empty">Nenhum jogo registrado.</div>'}</div>`;
  };

  // The original page may have started its first request before this enhancement
  // loaded. Refresh once so dates and the detailed permanent history appear now.
  setTimeout(() => refreshAll().catch(console.error), 50);
})();
