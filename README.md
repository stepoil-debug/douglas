# Tennis Quant Engine

Motor quantitativo seletivo para rastrear todos os fixtures ATP Singles do dia, aprofundar apenas os confrontos relevantes para a faixa de odd **1.50–2.00** e aprovar **no máximo 10** seleções. O sistema nunca força quantidade.

## Champion v0.2.0 — análise real

A versão atual consulta dados reais da API-Tennis e executa duas etapas:

1. **Screening de todos os ATP Singles do dia**: fixture, estado pré-jogo e mercado/odds.
2. **Deep Analysis** dos jogos em que pelo menos um lado está entre 1.50 e 2.00.

O Deep Analysis combina:

- consenso de várias casas com remoção da margem (*no-vig*);
- Elo global construído com até 365 dias de partidas históricas;
- Elo de superfície quando a fonte fornece superfície;
- ATP ranking/points;
- forma recente com decaimento temporal e shrinkage para amostras pequenas;
- dominância em sets;
- desempenho da temporada e por superfície quando disponível;
- fadiga por densidade de partidas em 1/3/7 dias;
- estatísticas de saque dos fixtures históricos quando a API as fornece;
- H2H com peso deliberadamente baixo;
- `Model Disagreement Index`;
- `Data Quality`;
- edge contra a probabilidade *fair* do mercado;
- `Confidence Score`.

O ranking final gera `APPROVED` (0–10), `SHADOW` (próximos 10 elegíveis) e `REJECTED`, guardando os motivos de rejeição.

## Segurança contra viés

- Apenas partidas **pré-jogo** podem virar seleção.
- Fixtures ao vivo, finalizados, cancelados, retired/walkover e similares ficam fora da seleção.
- Qualificatórios são rastreados, mas não aprovados no Champion atual.
- Prediction snapshots são imutáveis por partida + jogador selecionado.
- O Elo é idempotente: uma partida encerrada nunca é contabilizada duas vezes.
- O bootstrap histórico acontece antes da primeira previsão sempre que a fonte permite o intervalo solicitado.

## Pós-jogo e aprendizado

- Reconciliação automática de resultados.
- Weighted Elo atualizado por margem de sets.
- `GOOD_WIN`, `LUCKY_WIN`, `GOOD_LOSS`, `BAD_LOSS`.
- Failure Intelligence V1 com taxonomia `ERR-*`.
- Métricas móveis de 10/50/100/500 seleções aprovadas.
- Shadow predictions são preservadas para avaliar se o ranking realmente separa qualidade.

## Configuração obrigatória

1. Crie/obtenha uma chave da **API-Tennis**.
2. No repositório, abra **Settings → Secrets and variables → Actions**.
3. Crie o Repository Secret `API_TENNIS_KEY` com a chave.
4. Em **Settings → Pages**, mantenha `Source = GitHub Actions`.
5. Execute **Actions → Tennis Quant - Analyze → Run workflow**.

Se `API_TENNIS_KEY` estiver ausente, o workflow agora **falha explicitamente**; ele não simula sucesso nem publica uma análise vazia.

## Automação

O workflow roda uma vez por hora e também pode ser iniciado manualmente. Na primeira execução real ele pode demorar mais porque constrói o bootstrap histórico e o cache de enriquecimento. Execuções seguintes reutilizam o estado persistido no GitHub.

## Regras científicas

1. A meta é **máximo 10**, não exatamente 10.
2. A faixa permanece 1.50–2.00; não reduziremos artificialmente a odd para elevar a taxa de acerto.
3. Ajustes derivados de derrotas devem virar Challengers e ser validados antes de promover o Champion.
4. Acurácia, ROI, Brier Score, calibração, closing line e desempenho por rank/faixa devem ser acompanhados separadamente.
5. A meta de 90% é uma meta experimental e só poderá ser declarada com amostra fora da amostra suficientemente grande.

## Próximas evoluções

- snapshots de opening/closing line e `Market Movement`;
- Return Rating e matchup serve × return mais completo;
- classificação automática de causa raiz usando estatísticas pós-jogo;
- Champion × Challenger com walk-forward;
- ML tabular calibrado;
- relatório de performance Top 1–3, 4–5, 6–10 e Shadow 11–20.
