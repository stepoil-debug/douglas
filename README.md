# Tennis Quant Engine

Motor quantitativo seletivo para rastrear os ATP Singles do dia, aprofundar os confrontos relevantes para odds **1.50–2.00** e aprovar **no máximo 10** seleções. O sistema nunca força quantidade.

## Champion v0.3.0 — sem API esportiva

A análise não depende de Supabase, API-Tennis, RapidAPI ou qualquer chave de dados esportivos.

### Fontes atuais

- **OddsHarvester + Playwright/OddsPortal**: coleta os jogos ATP e as odds Match Winner por bookmaker diretamente das páginas públicas.
- **Jeff Sackmann / tennis_atp**: arquivos CSV públicos usados para histórico ATP, ranking aproximado disponível nos jogos, Elo, superfície, forma, H2H e estatísticas de saque.
- **GitHub Actions**: instala Chromium, executa o scraper, roda o motor e versiona somente os resultados e estados necessários.
- **GitHub Pages**: publica o painel.

Os CSVs públicos grandes e os arquivos temporários do navegador ficam em cache/runner e não são versionados no repositório.

## Fluxo

1. O OddsHarvester abre um Chromium headless e coleta os confrontos e odds do dia.
2. O provider filtra ATP Singles e converte as odds de cada bookmaker para o formato do Market Engine.
3. Nomes abreviados do OddsPortal (ex.: `Djokovic N.`) são associados aos IDs históricos do dataset ATP.
4. Antes da primeira previsão, o Elo é reconstruído com até 365 dias de histórico público.
5. Todos os jogos com mercado são triados; somente confrontos com pelo menos um lado entre 1.50 e 2.00 entram na análise profunda.
6. O Selection Engine aplica probabilidade, edge, confiança, qualidade de dados e discordância e libera de 0 a 10 seleções.
7. APPROVED e SHADOW recebem snapshots imutáveis.

## Sinais do Champion

- consenso de várias casas e probabilidade *no-vig*;
- Elo global;
- Elo por superfície;
- ranking/pontos disponíveis no histórico ATP;
- forma recente com shrinkage para amostras pequenas;
- dominância em sets;
- desempenho de temporada e superfície;
- fadiga aproximada por densidade de partidas;
- estatísticas históricas de saque quando disponíveis;
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
- Shadow: próximos 10 elegíveis;
- probabilidade mínima: 65%;
- edge mínimo: 3,5 pontos percentuais;
- confiança mínima: 72;
- qualidade de dados mínima: 62%;
- discordância máxima: 12,5 pontos percentuais.

Esses cortes são parâmetros experimentais e serão alterados apenas depois de backtests/walk-forward.

## Painel e botão Iniciar análises

O painel continua sem backend. Para o botão **Iniciar análises** disparar o GitHub Action diretamente, configure uma única vez um GitHub token restrito ao repositório com permissão `Actions: Read and write`. O token fica somente no navegador.

Nenhuma chave de API de tênis é necessária.

Também é possível iniciar manualmente em **Actions → Tennis Quant - Analyze → Run workflow** sem configurar token no painel.

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
export PYTHONPATH=src
python -m tennis_quant.cli
```

## Segurança contra viés

- somente pré-jogo pode virar seleção;
- iniciados/finalizados/cancelados/retired/walkover ficam fora do Top 10;
- prediction snapshots são imutáveis;
- o Elo é idempotente;
- mudança da fonte/identidade dos jogadores invalida e reconstrói automaticamente o bootstrap antigo;
- nenhuma derrota altera diretamente o Champion.

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

O CI compila todo o código e executa testes unitários em cada Pull Request. O dashboard mostra fixtures encontrados, ATP pré-jogo, jogos com odds, análise profunda, bootstrap, fontes, jogadores não resolvidos e causas de rejeição.

## Regras científicas

1. A meta é **máximo 10**, não exatamente 10.
2. A faixa permanece 1.50–2.00; não reduziremos artificialmente a odd para elevar a taxa de acerto.
3. Ajustes derivados de derrotas viram Challengers e precisam vencer validação temporal antes de promoção.
4. Acurácia, ROI, Brier Score, calibração, closing line e desempenho por rank/faixa serão medidos separadamente.
5. A meta de 90% é experimental e só poderá ser declarada com amostra fora da amostra grande o suficiente.

## Licenças e uso

O OddsHarvester é open source sob licença MIT. O dataset `JeffSackmann/tennis_atp` é disponibilizado sob CC BY-NC-SA e deve ser tratado como fonte de pesquisa/não comercial. Para eventual produto comercial, a camada histórica deve ser substituída ou licenciada adequadamente. Scraping também deve respeitar os termos aplicáveis ao site de origem.

## Próximas evoluções

- integrar Tennis-Data como dataset de odds históricas para backtests;
- snapshots opening/T-6h/T-3h/T-1h/T-15min e Market Movement;
- Return Rating;
- matchup serve × return;
- Failure Intelligence com dados pós-jogo mais completos;
- Champion × Challenger + walk-forward;
- ML tabular calibrado;
- performance Top 1–3, 4–5, 6–10 e Shadow 11–20.
