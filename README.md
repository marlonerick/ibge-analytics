# Brasil em números

Pipeline de dados e análise territorial do Brasil construído sobre as APIs
públicas do IBGE. Sai de zero e chega a um dashboard interativo, cinco notebooks
de análise e um relatório HTML autocontido — tudo a partir de dados reais,
baixados na hora.

**Cobertura:** 5.571 municípios · 27 UFs · 5 regiões · séries de 2001 a 2025.

---

## O que ele responde

| Análise | Onde está |
|---|---|
| População por município, porte e concentração (Gini, Lorenz) | `analysis/populacao.py` · notebook 01 |
| Crescimento populacional (CAGR), quem cresce e quem encolhe | `analysis/crescimento.py` · notebook 02 |
| PIB por estado e município, per capita, estrutura setorial | `analysis/pib.py` · notebook 03 |
| Densidade demográfica e ocupação do território | `analysis/densidade.py` · notebook 04 |
| Comparação entre as cinco regiões | notebook 05 |
| Mapas coropléticos com GeoJSON | `viz/maps.py` · página *Mapas* do dashboard |
| Concentração, especialização setorial e ranking em SQL | `sql/analytics/` · `ibge-db query` |

Alguns resultados que os dados mostram:

- **29% dos municípios perderam população** entre 2001 e 2025, mesmo com o país
  crescendo no agregado.
- **Metade do PIB nacional é produzida em 84 municípios** — 1,5% do total.
- **Metade da população vive em 197 municípios que ocupam 3,7% do território.**
- 44% dos municípios têm menos de 10 mil habitantes, e juntos somam 6% da
  população.

---

## Instalação

Requer Python 3.11+.

```bash
pip install -e ".[dev]"
```

## Uso

```bash
# 1. Baixa e processa tudo (~3 min na primeira vez; depois usa cache)
python -m ibge_analytics.etl.pipeline

# 2. Dashboard interativo
streamlit run dashboard/app.py

# 3. Relatório HTML autocontido
python scripts/build_report.py        # -> reports/relatorio.html

# 4. Notebooks
python scripts/build_notebooks.py     # (re)gera os .ipynb
jupyter lab notebooks/
```

Opções do pipeline:

```bash
python -m ibge_analytics.etl.pipeline --sem-malhas          # pula o GeoJSON
python -m ibge_analytics.etl.pipeline --etapas populacao pib
python -m ibge_analytics.etl.pipeline -v                     # log detalhado
```

## Banco de dados

O mesmo dado, persistido em PostgreSQL, com a camada analítica em SQL.

```bash
cp .env.example .env          # preencha PGPASSWORD (porta 5432)
ibge-db sync                  # cria, carrega e verifica — ~10 s

ibge-db query concentracao
ibge-db query top_municipios --metrica pib --limite 10
ibge-db query serie_uf --uf SP --csv serie-sp.csv
```

14 tabelas · 13 índices · 7 views · 2 materializadas · 11 consultas analíticas ·
207.497 linhas. Detalhes em **[docs/BANCO.md](docs/BANCO.md)**.

## Testes

```bash
pytest              # 278 testes offline
pytest -m network   # + 3 testes contra a API real
pytest -m postgres  # + 6 testes de integração com o banco
```

| Arquivo | Cobre |
|---|---|
| `test_api.py` | lotes do SIDRA, sentinelas, cache em disco, hierarquia de Localidades |
| `test_extract.py` | registro de agregados e a janela de anos que cada extração pede |
| `test_transform.py` | métricas derivadas: CAGR, densidade, concentração, agregação |
| `test_pipeline.py` | montagem dos painéis: que ano casa com qual, joins, orquestração |
| `test_analysis.py` | faixas de porte e densidade, rankings, leituras regionais |
| `test_io.py` | camada de leitura, memoização, inventário × pipeline |
| `test_dados.py` | **os Parquets em `data/processed/`** — cobertura, coerência e ordens de grandeza |
| `test_db.py` | configuração, COPY, registro de consultas, coerência SQL × pandas |
| `test_report.py` | navegação do relatório derivada das seções |

Os testes de banco são pulados automaticamente quando não há conexão, e os de
dados quando o pipeline ainda não rodou.

---

## Estrutura

```
ibge-analytics/
├── src/ibge_analytics/
│   ├── config.py              # caminhos, registro de agregados, constantes
│   ├── api/
│   │   ├── client.py          # sessão HTTP: retry, backoff, cache em disco
│   │   ├── agregados.py       # SIDRA v3 + fatiamento de requisições
│   │   ├── localidades.py     # hierarquia município → UF → região
│   │   └── malhas.py          # GeoJSON das malhas territoriais
│   ├── etl/
│   │   ├── extract.py         # APIs      → data/raw/
│   │   ├── transform.py       # métricas derivadas, sem I/O
│   │   └── pipeline.py        # orquestração → data/processed/
│   ├── analysis/              # populacao · crescimento · pib · densidade
│   ├── db/
│   │   ├── engine.py          # conexão (.env / libpq), leitura dos .sql
│   │   ├── schema.py          # aplica o DDL, refresh das materializadas
│   │   ├── load.py            # Parquet -> Postgres via COPY, numa transação
│   │   ├── queries.py         # registro das consultas analíticas
│   │   └── cli.py             # `ibge-db`
│   ├── viz/
│   │   ├── theme.py           # paleta validada, tokens, formatação pt-BR
│   │   ├── charts.py          # gráficos Plotly
│   │   └── maps.py            # coropléticos Plotly + Folium
│   └── utils/io.py            # leitura das tabelas processadas
├── sql/
│   ├── 01_schema.sql          # tabelas, chaves, constraints
│   ├── 02_indexes.sql         # índices, cada um com a consulta que atende
│   ├── 03_views.sql           # camada analítica
│   └── analytics/             # 11 consultas nomeadas e parametrizadas
├── dashboard/                 # app Streamlit (5 páginas)
├── notebooks/                 # 5 notebooks gerados por script
├── scripts/                   # build_report.py · build_notebooks.py
├── data/{raw,interim,processed,geo}/
├── reports/                   # relatorio.html + figuras
├── tests/                     # 287 testes
└── docs/
    ├── ARQUITETURA.md         # camadas, fluxo ETL, dicionário de dados, stack
    ├── API_NOTES.md           # comportamentos reais das APIs do IBGE
    └── BANCO.md               # modelo, índices e consultas do PostgreSQL
```

---

## Fontes

| API | Uso |
|---|---|
| [Agregados v3 (SIDRA)](https://servicodados.ibge.gov.br/api/docs/agregados?versao=3) | população, PIB, área, densidade |
| [Localidades v1](https://servicodados.ibge.gov.br/api/docs/localidades) | hierarquia territorial |
| [Malhas v3](https://servicodados.ibge.gov.br/api/docs/malhas) | geometrias GeoJSON |

Agregados consumidos: **6579** (população estimada), **4714** (Censo 2022:
população, área e densidade) e **5938** (PIB municipal e valor adicionado por
setor).

---

## Decisões de projeto

**Requisições fatiadas por orçamento de células.** A API rejeita respostas
grandes com HTTP 500 sem explicação. O limite não é de períodos, e sim do
produto `variáveis × períodos × localidades`; o cliente calcula os lotes antes
de pedir, em vez de descobrir o estouro por tentativa e erro.

**Anos vêm da API, não de constantes.** A série de população estimada não
publica 2007, 2010, 2022 e 2023 — e pedir um ano inexistente não dá erro, o dado
só some. O pipeline consulta `/periodos` e valida o que pediu.

**Cada indicador usa a população do seu ano.** O PIB vai até 2023 e a população
até 2025; dividir um pelo outro subestimaria o PIB per capita. O pipeline casa o
PIB com o ano de população publicado mais próximo e grava qual usou.

**Cache agressivo em disco.** Requisições municipais levam de 5 a 20 s e os
dados são anuais. O cache tem TTL de 30 dias e escrita atômica.

**Malhas reorientadas na carga.** O Plotly renderiza com d3-geo, que exige
winding esférico — o oposto do que o IBGE (e o RFC 7946) entrega. Sem inverter,
o mapa sai com a projeção inteira preenchida, *sem erro nenhum*.

**O banco guarda o cru; o SQL calcula o resto.** `data/processed/` é
denormalizado — repete nome de município, UF e região em cada linha de fato.
No PostgreSQL os fatos entram na granularidade em que o SIDRA publica, e toda
métrica derivada é view. Recarregar os fatos não deixa nenhum número calculado
desatualizado, porque nenhum número calculado está gravado.

**Cada indicador usa o ano do seu próprio dado.** Além do PIB per capita, o
mesmo vale para a estrutura setorial: o agregado 5938 publica o PIB total até
2023 mas o valor adicionado por setor só até 2021, e as variáveis setoriais vêm
presentes e nulas nos dois últimos anos. Tomar `max(ano)` uma vez para tudo
zeraria a estrutura setorial inteira, calada. O painel expõe `ano_pib` e
`ano_vab` lado a lado.

**Cor por último, e validada.** A paleta é a de referência do sistema de design,
usada sem alteração de hex, com as restrições que a validação dela impõe: as
formas que comparam todos os pares entre si (dispersão) são facetadas em vez de
coloridas, e as cores de menor contraste sempre vêm acompanhadas de rótulo
direto ou tabela. Nenhuma leitura depende só da cor.

As camadas, o fluxo ETL etapa a etapa, o dicionário de dados e o passo a passo
de reprodução estão em **[docs/ARQUITETURA.md](docs/ARQUITETURA.md)**; os
detalhes de cada peculiaridade das APIs, em
**[docs/API_NOTES.md](docs/API_NOTES.md)**; as decisões de modelagem e os
índices, em **[docs/BANCO.md](docs/BANCO.md)**.
