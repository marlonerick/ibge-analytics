# O banco

Persistência dos dados do IBGE em PostgreSQL, com a camada analítica em SQL.

O que muda em relação ao Parquet: o dado deixa de estar em 11 tabelas largas e
independentes e passa a ter **uma verdade por fato**, com a hierarquia
territorial normalizada e as métricas derivadas calculadas na leitura. Recarregar
os fatos não deixa nenhum número calculado desatualizado, porque nenhum número
calculado está gravado.

---

## Começando

```bash
cp .env.example .env        # preencha PGPASSWORD
ibge-db sync                # cria o banco, aplica o DDL, carrega e verifica
```

`sync` é `init` + `load` + `refresh` + `qualidade`. Leva cerca de 10 segundos
com os Parquet já em `data/raw/` (rode `python -m ibge_analytics.etl.pipeline`
antes, se ainda não rodou).

> A porta do PostgreSQL é a **5432**. A 3306 é do MySQL/MariaDB — apontar o
> `.env` para ela não funciona: o schema deste projeto usa materialized views,
> `FILTER`, `DISTINCT ON` e `COPY`, que são específicos do PostgreSQL.

### Comandos

| comando | o que faz |
|---|---|
| `ibge-db check` | conexão, inventário e as 14 verificações de qualidade |
| `ibge-db check --indices` | acima, mais quantas varreduras cada índice recebeu |
| `ibge-db init` | cria banco, schemas, tabelas, índices e views (idempotente) |
| `ibge-db init --recriar` | **destrutivo**: derruba os dois schemas antes (pede confirmação) |
| `ibge-db load` | Parquet → Postgres e refresh das materializadas |
| `ibge-db refresh` | só recalcula as materializadas |
| `ibge-db queries` | lista as consultas analíticas |
| `ibge-db query <nome>` | executa uma; `--csv arquivo` grava, `--sql` só mostra o SQL |
| `ibge-db explain <nome>` | `EXPLAIN ANALYZE` da consulta |

---

## Modelo

Dois schemas. `ibge` guarda **o que o IBGE publica**; `analytics` guarda **o que
nós concluímos**.

```
ibge/
├── dim_regiao ───┐
├── dim_uf ───────┤  hierarquia territorial (Localidades v1)
├── dim_municipio ┘
│
├── fato_populacao_{municipio,uf,regiao,brasil}   agregado 6579
├── fato_censo_{municipio,uf,regiao}              agregado 4714
├── fato_pib_{municipio,uf,regiao,brasil}         agregado 5938
└── carga_log                                     linhagem das cargas

analytics/
├── vw_municipio                 hierarquia achatada
├── vw_anos_disponiveis          quais anos cada série realmente tem
├── vw_populacao_municipio       série com variação anualizada (LAG)
├── vw_crescimento_municipio     CAGR + faixa de crescimento
├── mv_painel_municipio     ★    um retrato por município
├── mv_concentracao_municipio ★  curva de Lorenz (população e PIB)
├── vw_ranking_municipio         posição nacional e dentro da UF
├── vw_painel_uf
└── vw_painel_regiao
```

★ = materializada. `ibge-db refresh` as recalcula.

**207.497 linhas**, ~35 MB. A carga completa leva 7 segundos.

### Por que carrega o cru e não o processado

`data/processed/` é denormalizado — repete nome de município, UF e região em
cada linha de fato. Reproduzi-lo no banco gravaria a mesma string 116 mil vezes
e criaria duas verdades sobre o que é "densidade". Os fatos entram na
granularidade em que o SIDRA publica; o resto é view.

### Decisões que o schema registra

**`municipio_id` é `char(7)`, não inteiro.** É um identificador com dígito
verificador. Como `char(7)`, preserva o zero à esquerda que o Parquet perdeu ao
guardar a coluna como `int64`, e ninguém soma a coluna por acidente. Um `CHECK`
exige que os dois primeiros dígitos batam com o `uf_id`.

**Sem `CHECK (pib > 0)`.** PIB municipal negativo existe — ver
[API_NOTES §8](API_NOTES.md).

**A carga é uma transação só.** `TRUNCATE` de todas as tabelas, `COPY` de cada
uma, commit. Ou o banco fica com o snapshot inteiro, ou fica como estava. As
14 tabelas são truncadas num único comando porque se referenciam mutuamente.

**`carga_log` nunca é truncada.** É o que responde "esse número saiu de qual
extração?" sem depender do que estiver no disco hoje.

---

## Índices

13 índices, cada um para uma consulta concreta. As PKs já cobrem o acesso por
entidade — `(municipio_id, ano)` resolve "a série deste município". O que falta,
e é o padrão dominante das análises, é o oposto: "todos os municípios de um ano".

Os dois mais interessantes são parciais e com `INCLUDE`:

```sql
CREATE INDEX ix_fato_pop_mun_ano_rank
    ON ibge.fato_populacao_municipio (ano, populacao DESC)
    INCLUDE (municipio_id)
    WHERE populacao IS NOT NULL;
```

O `INCLUDE` carrega o município na folha do índice, o que torna "os 50 maiores
de 2025" um **index-only scan** — `Heap Fetches: 0`, 0,1 ms, sem tocar a tabela:

```
Limit  (actual time=0.090..0.096 rows=50)
  ->  Index Only Scan using ix_fato_pop_mun_ano_rank  (actual time=0.089..0.093)
        Index Cond: (ano = 2025)
        Heap Fetches: 0
```

---

## Consultas analíticas

Onze consultas em `sql/analytics/`, uma por arquivo. O registro em
`db/queries.py` só guarda nome, descrição e parâmetros padrão — o SQL nunca é
montado por concatenação, para que possa ser lido, colado no `psql` e revisado
sem passar pelo Python.

| consulta | responde |
|---|---|
| `concentracao` | quantos municípios fazem 10/25/50/75/90% da população e do PIB |
| `top_municipios` | os maiores em um indicador, com share acumulado |
| `porte_populacional` | a rede urbana por faixa de porte |
| `declinio_populacional` | quantos municípios encolhem, por UF, e o saldo líquido |
| `quociente_locacional` | especialização produtiva das UFs contra a média nacional |
| `descolamento_pib_populacao` | onde PIB e população andam em direções opostas |
| `densidade_extremos` | os mais densos e os mais vazios, na mesma tabela |
| `regioes` | comparação entre as cinco grandes regiões |
| `serie_uf` | série histórica de uma UF (ou do Brasil) |
| `perfil_municipio` | ficha completa de um município |
| `qualidade` | 14 verificações de integridade da carga |

Em Python:

```python
from ibge_analytics.db import queries

queries.executar("concentracao")
queries.executar("top_municipios", metrica="pib", limite=10)
queries.executar("serie_uf", uf="SP")
print(queries.sql_bruto("quociente_locacional"))
```

### Duas armadilhas do SQLAlchemy que este código evita

**`:param::tipo` não funciona.** O parser do SQLAlchemy quebra o nome do bind ao
meio quando vem `::` logo depois, e cria um parâmetro fantasma. Use
`CAST(:param AS tipo)`.

**Comentários também são varridos.** `:algo` dentro de `--` vira bind parameter
de verdade. Por isso os comentários em `sql/analytics/` escrevem os parâmetros
sem os dois-pontos: `` `limite` ``, não `:limite`. O teste
`test_sql_nao_usa_parametro_nao_declarado` trava isso.

**Parâmetro nulo precisa de tipo.** `WHERE :uf IS NULL` falha com
`AmbiguousParameter` — o PostgreSQL não consegue inferir o tipo. Daí o `CAST`
em `serie_uf.sql`.

---

## Coerência com o pandas

As mesmas faixas estão escritas duas vezes: em `CASE` no SQL e em `pd.cut` no
Python. Isso é duplicação, e é deliberada — o SQL precisa rodar sem o Python.
O que a mantém honesta são os testes:

- `test_faixas_de_crescimento_do_sql_batem_com_as_do_pandas`
- `test_cortes_de_crescimento_do_sql_batem_com_os_do_pandas`
- `test_faixas_de_porte_do_sql_batem_com_as_do_pandas`
- `test_cagr_do_sql_bate_com_o_do_pandas` — compara os 5.571 CAGR calculados
  nos dois lugares, com tolerância de 1e-3 p.p.

Atenção a `pd.cut`: as faixas de **crescimento** usam `right=True` (fechadas à
direita, `<=`) e as de **porte** usam `right=False` (fechadas à esquerda, `<`).
O SQL replica cada uma na sua forma.

---

## Testes

```bash
pytest                 # 82 testes, nenhum precisa de banco
pytest -m postgres     # + 6 testes de integração
```

Os testes marcados `postgres` são **pulados automaticamente** quando não há
conexão, para que a suíte continue verde numa máquina sem banco.
