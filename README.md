# Tennis Quant Engine

Motor quantitativo seletivo para rastrear os ATP Singles do dia, aprofundar os confrontos relevantes para odds **1.50–2.00** e aprovar **no máximo 10** seleções. O sistema nunca força quantidade.

## Champion v0.3.0 — sem API esportiva

A análise não depende de Supabase, API-Tennis, RapidAPI ou qualquer chave de dados esportivos.

### Fontes atuais

- **TennisExplorer**: fonte primária validada para agenda ATP Singles e odds H/A do dia via HTML público (`requests + BeautifulSoup`).
- **OddsHarvester 0.10 + Playwright/OddsPortal e espelhos regionais**: fallback para coleta ao vivo quando o ambiente permitir; IPs de datacenter podem receber proteção anti-bot.
- **Histórico ATP em formato Sackmann**: CSV público via espelho `Kadantte/tennis_atp`, com fallback para a origem Jeff Sackmann; usado para histórico, ranking disponível nos jogos, Elo, superfície, forma, H2H e saque.
- **GitHub Actions**: executa coletores, testes e motor quantitativo e versiona apenas estados/resultados úteis.
- **GitHub Pages**: publica o painel.

Os CSVs públicos grandes e os arquivos temporários ficam no cache/runner e não são versionados no repositório.

## Fluxo validado em produção

1. O runner busca a agenda ATP Singles e as odds H/A no TennisExplorer.
2. Se a fonte primária falhar, tenta OddsPortal e espelhos por OddsHarvester/Playwright.
3. O provider associa nomes abreviados da fonte ao ID histórico do jogador.
4. Antes da primeira previsão, o Elo é reconstruído com até 365 dias de histórico público.
5. Todos os jogos com mercado são triados; somente confrontos com pelo menos um lado entre 1.50 e 2.00 entram na análise profunda.
6. O Selection Engine aplica probabilidade, edge, confiança, qualidade de dados e discordância e libera de 0 a 10 seleções.
7. APPROVED e SHADOW recebem snapshots imutáveis.
8. Rejeições também ficam registradas; `near_misses` é apenas diagnóstico e nunca vira aposta automaticamente.

### Primeira execução real validada — 11/08/2026

- 28 partidas ATP coletadas da fonte ao vivo;
- 24 partidas ainda pré-jogo;
- 24 partidas com odds;
- 11 confrontos dentro do escopo para análise profunda;
- 22 lados avaliados;
- bootstrap Elo construído com 2.249 partidas históricas entre 11/08/2025 e 10/08/2026;
- 1 nome não resolvido automaticamente (`Wolf J.`);
- 0 seleções aprovadas nessa rodada porque nenhuma ultrapassou todos os cortes do Champion.

Zero aprovados é um resultado válido. Os filtros não são relaxados para fabricar uma lista de apostas.

## Sinais do Champion

- mercado H/A e probabilidade *no-vig*;
- Elo global;
- Elo por superfície quando a superfície está resolvida;
- ranking/pontos disponíveis no histórico ATP;
- forma recente com shrinkage para amostras pequenas;
- dominância em sets;
- desempenho de temporada e superfície;
- fadiga aproximada por densidade de partidas;
- estatísticas históricas de primeiro/segundo saque quando disponíveis;
- H2H com peso baixo;
- Model Disagreement Index;
- Data Quality;
- edge contra o mercado;
- Confidence Score.

Se um jogador atual não puder ser associado de forma confiável ao histórico, os sinais dependentes de identidade são removidos e a qualidade dos dados é penalizada. O motor prefere rejeitar uma seleção a inventar histórico.

## Seleção

O Champion atual mantém:

- odd mínima: 1.50;
- odd máxima: 2.00;
- máximo de aprovados: 10;
- Shadow: próximos 10 que já passaram todos os gates, após os aprovados;
- probabilidade mínima: 65%;
- edge mínimo: 3,5 pontos percentuais;
- confiança mínima: 72;
- qualidade de dados mínima: 62%;
- discordância máxima: 12,5 pontos percentuais.

Esses cortes são experimentais e só serão alterados depois de backtest/walk-forward; não serão reduzidos apenas para gerar picks.

## Painel e botão Iniciar análises

O painel continua sem backend. Para o botão **Iniciar análises** disparar o GitHub Action diretamente, configure uma única vez um GitHub token restrito ao repositório com permissão `Actions: Read and write`. O token fica somente no navegador.

Nenhuma chave de API de tênis é necessária.

Também é possível iniciar manualmente em **Actions → Tennis Quant - Analyze → Run workflow** sem configurar token no painel.

O workflow mantém `dashboard/run_status.json` com `RUNNING`, `SUCCESS` ou `FAILED`, além do `run_id` e do link do log.

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
export PYTHONPATH=src:.
python -m tennis_quant.cli
```

## Segurança contra viés

- somente pré-jogo pode virar seleção;
- iniciados/finalizados/cancelados/retired/walkover ficam fora do Top 10;
- prediction snapshots são imutáveis;
- o Elo é idempotente;
- mudança da fonte/identidade dos jogadores invalida e reconstrói automaticamente o bootstrap antigo;
- nenhuma derrota altera diretamente o Champion;
- coleta com zero eventos não pode ser registrada como falso sucesso.

## Pós-jogo e aprendizado

O projeto mantém a estrutura para:

- reconciliação de resultados quando a fonte pública conseguir observar o encerramento;
- Weighted Elo;
- GOOD_WIN, LUCKY_WIN, GOOD_LOSS e BAD_LOSS;
- Failure Intelligence (`ERR-*`);
- métricas móveis 10/50/100/500;
- Shadow predictions;
- futuro Champion × Challenger.

## Testes e observabilidade

O CI compila o código e os coletores e executa testes unitários em cada Pull Request. O dashboard mostra fixtures encontrados, ATP pré-jogo, jogos com odds, análise profunda, bootstrap, fontes, jogadores não resolvidos e causas de rejeição.

O motor também grava `rejection_summary` e os até 10 `near_misses` mais próximos dos gates, sem alterar a decisão original.

## Regras científicas

1. A meta é **máximo 10**, não exatamente 10.
2. A faixa permanece 1.50–2.00; não reduziremos artificialmente a odd para elevar a taxa de acerto.
3. Ajustes derivados de derrotas viram Challengers e precisam vencer validação temporal antes de promoção.
4. Acurácia, ROI, Brier Score, calibração, closing line e desempenho por rank/faixa serão medidos separadamente.
5. A meta de 90% é experimental e só poderá ser declarada com amostra fora da amostra grande o suficiente.

## Licenças e uso

O OddsHarvester é open source sob licença MIT. O histórico em formato Sackmann deve ser tratado conforme a licença da fonte original/espelho e, nesta fase, é usado para pesquisa individual. Para eventual produto comercial, a camada histórica deve ser substituída ou licenciada adequadamente. O scraping deve respeitar os termos aplicáveis a cada site de origem.

## Próximas evoluções

- enriquecer TennisExplorer com odds por várias casas na página de detalhe;
- integrar Tennis-Data como dataset de odds históricas para backtests;
- snapshots opening/T-6h/T-3h/T-1h/T-15min e Market Movement;
- Return Rating;
- matchup serve × return;
- Failure Intelligence com dados pós-jogo mais completos;
- Champion × Challenger + walk-forward;
- ML tabular calibrado;
- performance Top 1–3, 4–5, 6–10 e Shadow 11–20.
