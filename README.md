# Tennis Quant Engine

Motor quantitativo seletivo para analisar todas as partidas ATP Singles elegíveis e aprovar **no máximo 10** seleções por rodada. O sistema não força quantidade: se nenhuma partida atingir os critérios, publica zero.

## V1 implementada

- API-Tennis como provider desacoplado para fixtures, H2H e odds.
- Consenso de odds por bookmaker e probabilidade *no-vig*.
- Elo global e Elo de superfície persistentes.
- Elo aprende automaticamente com partidas finalizadas e não contabiliza o mesmo jogo duas vezes.
- Forma recente e H2H com influência controlada.
- Ensemble V1 (market + Elo + surface Elo + recent form).
- `Model Disagreement Index`, data quality, edge e confidence score.
- Filtros de odd 1.50–2.00, probabilidade, edge, confiança e discordância.
- Ranking com `APPROVED` (0–10), `SHADOW` (próximos 10) e `REJECTED`.
- Prediction snapshots imutáveis por partida + jogador selecionado.
- Reconciliação automática dos resultados recentes.
- Classificação pós-jogo: `GOOD_WIN`, `LUCKY_WIN`, `GOOD_LOSS`, `BAD_LOSS`.
- Failure Intelligence V1 com taxonomia de hipóteses (`ERR-*`).
- Métricas móveis das últimas 10/50/100/500 seleções aprovadas.
- Dashboard estático para GitHub Pages.
- GitHub Actions para testes, análise automática, aprendizado de Elo e publicação do dashboard.

## Configuração

1. Em **Settings → Secrets and variables → Actions**, crie `API_TENNIS_KEY`.
2. Em **Settings → Pages**, selecione **GitHub Actions** como source.
3. Execute manualmente o workflow `Tennis Quant - Analyze` para validar a primeira coleta.

Sem `API_TENNIS_KEY`, o workflow continua executando os testes e apenas pula a análise ao vivo, sem quebrar o repositório. A chave é consumida apenas no runner do GitHub e nunca é enviada ao dashboard.

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
export PYTHONPATH=src
export API_TENNIS_KEY='...'
python -m tennis_quant.cli --date 2026-08-11
```

## Regras científicas do projeto

1. Prediction snapshots são congelados antes da partida e nunca sobrescritos.
2. A meta é **máximo 10**, não exatamente 10.
3. Ajustes sugeridos por derrotas viram hipóteses/challengers; não alteram automaticamente o Champion.
4. Acurácia, ROI, Brier Score, calibração e desempenho por faixa/rank serão acompanhados separadamente.
5. A meta de pesquisa de 90% não será declarada como atingida sem amostra fora da amostra suficientemente grande.

## Próximas etapas técnicas

- Bootstrap histórico para iniciar Elo com grande massa de jogos em vez de aprender apenas a partir da ativação.
- Estatísticas avançadas de saque/devolução e fadiga.
- Captura de snapshots de odds para opening/closing line e market movement.
- Failure Intelligence contextual com estatísticas pós-jogo.
- Champion vs Challenger + walk-forward.
- ML tabular e calibração probabilística.
- Relatórios de Top 1–3, 4–5, 6–10 e Shadow 11–20.
