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
    return selected === winner ? 'HIT' : 'MISS';
  };
  const outcomeTag = value => {
    const cls = value === 'HIT' ? 'hit' : value === 'MISS' ? 'miss' : 'pending';
    return `<span class="tag ${cls}">${esc(value)}</span>`;
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
      const modelResolved = s.resolved_model_picks ?? 0;
      const modelHits = s.model_hits ?? 0;
      const modelMisses = s.model_misses ?? 0;
      const suffix = modelResolved ? ` • ${modelHits}H/${modelMisses}M` : ` • ${s.games || 0} jogos`;
      return `<option value="${esc(x.date)}" ${preferred === x.date ? 'selected' : ''}>${br(x.date)}${suffix}</option>`;
    }).join('');
    sel.onchange = () => loadHistory(sel.value);
    if (sel.value) await loadHistory(sel.value);
  };

  loadHistory = async function(day) {
    let x;
    try { x = await j(`history/${day}.json`); }
    catch { $('historyBox').textContent = 'Sem registro para esta data.'; return; }

    const games = x.games || [];
    const analyzed = games.filter(g => primaryAnalysis(g));
    const resolved = analyzed.filter(g => ['HIT', 'MISS'].includes(outcome(g, primaryAnalysis(g))));
    const hits = resolved.filter(g => outcome(g, primaryAnalysis(g)) === 'HIT').length;
    const misses = resolved.length - hits;
    const officialApproved = games.reduce((n, g) => n + (g.analyses || []).filter(a => a.status === 'APPROVED').length, 0);
    const officialResolved = games.reduce((n, g) => n + (g.analyses || []).filter(a => a.status === 'APPROVED' && g.result?.resolved).length, 0);
    const officialHits = games.reduce((n, g) => {
      const winner = g.result?.winner?.key;
      return n + (g.analyses || []).filter(a => a.status === 'APPROVED' && g.result?.resolved && a.selected_player?.key === winner).length;
    }, 0);
    const officialMisses = Math.max(0, officialResolved - officialHits);

    const rows = games.map(g => {
      const a = primaryAnalysis(g);
      const result = outcome(g, a);
      const prediction = a ? `${esc(a.selected_player?.name)} para vencer` : 'Fora da análise profunda';
      const match = `${esc(g.player_a?.name)} vs ${esc(g.player_b?.name)}`;
      const winner = g.result?.winner?.name ? `${esc(g.result.winner.name)}${g.result?.score ? ` • ${esc(g.result.score)}` : ''}` : 'Aguardando resultado';
      return `<tr><td><b>${br(g.date || x.date)}</b><div class="mini">${esc(g.time || 'horário n/d')}</div></td><td><div class="pred">${prediction}</div><div class="mini">${match} • ${esc(g.tournament || 'ATP')}</div></td><td>${a ? statusTag(a.status) : '<span class="tag pending">SEM ANÁLISE</span>'}</td><td>${a ? num(a.odd, 2) : '—'}</td><td>${a ? pct(a.final_probability) : '—'}</td><td>${outcomeTag(result)}</td><td><div class="pred">${winner}</div>${a ? `<div class="mini">Conf. ${num(a.confidence)} • Edge ${num(a.edge_pp)} pp</div>` : ''}</td></tr>`;
    }).join('');

    $('historyBox').innerHTML = `
      <div class="learning-kpis">
        <div class="learn"><small>Jogos salvos</small><b>${games.length}</b></div>
        <div class="learn"><small>Previsões do motor</small><b>${analyzed.length}</b></div>
        <div class="learn"><small>HIT / MISS modelo</small><b class="gold">${hits} / ${misses}</b></div>
        <div class="learn"><small>Acerto do modelo</small><b class="gold">${resolved.length ? (hits / resolved.length * 100).toFixed(1) + '%' : '—'}</b></div>
      </div>
      <div class="mini" style="margin:12px 0 16px">Entradas oficiais aprovadas: <b>${officialApproved}</b> • resolvidas: <b>${officialResolved}</b> • ${officialHits} WIN / ${officialMisses} LOSS. As demais linhas servem para auditoria e aprendizado do modelo, não significam aposta recomendada.</div>
      <div class="card" style="overflow:auto"><table class="table"><thead><tr><th>Data</th><th>Jogo / previsão salva</th><th>Decisão</th><th>Odd</th><th>Prob.</th><th>Resultado</th><th>Vencedor / placar</th></tr></thead><tbody>${rows || '<tr><td colspan="7">Nenhum jogo registrado.</td></tr>'}</tbody></table></div>`;
  };

  // The original page may have started its first request before this enhancement
  // loaded. Refresh once so dates and the detailed history are immediately visible.
  setTimeout(() => refreshAll().catch(console.error), 50);
})();
