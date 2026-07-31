-- =========================================================================
-- Camada analítica.
--
-- Toda métrica derivada mora aqui, não nas tabelas. A regra: `ibge` guarda o
-- que o IBGE publica; `analytics` guarda o que nós concluímos. Recarregar os
-- fatos nunca deixa um número calculado desatualizado, porque nenhum número
-- calculado está gravado — exceto nas duas materialized views, que são cache
-- explícito e têm comando próprio de refresh (`ibge-db refresh`).
--
-- As faixas (crescimento, porte) repetem exatamente os cortes de
-- `analysis/populacao.py` e `etl/transform.classificar_crescimento`, para que
-- a mesma pergunta feita no SQL e no pandas devolva a mesma resposta.
--
-- Idempotente: recria tudo do zero a cada execução.
-- =========================================================================

DROP MATERIALIZED VIEW IF EXISTS analytics.mv_concentracao_municipio CASCADE;
DROP MATERIALIZED VIEW IF EXISTS analytics.mv_painel_municipio       CASCADE;
DROP VIEW IF EXISTS analytics.vw_painel_regiao          CASCADE;
DROP VIEW IF EXISTS analytics.vw_painel_uf              CASCADE;
DROP VIEW IF EXISTS analytics.vw_crescimento_municipio  CASCADE;
DROP VIEW IF EXISTS analytics.vw_populacao_municipio    CASCADE;
DROP VIEW IF EXISTS analytics.vw_anos_disponiveis       CASCADE;
DROP VIEW IF EXISTS analytics.vw_municipio              CASCADE;


-- =========================================================================
-- vw_municipio — a hierarquia territorial achatada
--
-- Existe para que nenhuma outra view precise repetir o join de três níveis.
-- =========================================================================

CREATE VIEW analytics.vw_municipio AS
SELECT
    m.municipio_id,
    m.municipio_nome,
    m.microrregiao_id,
    m.microrregiao_nome,
    m.mesorregiao_id,
    m.mesorregiao_nome,
    u.uf_id,
    u.uf_sigla,
    u.uf_nome,
    r.regiao_id,
    r.regiao_sigla,
    r.regiao_nome
FROM ibge.dim_municipio m
JOIN ibge.dim_uf        u ON u.uf_id     = m.uf_id
JOIN ibge.dim_regiao    r ON r.regiao_id = u.regiao_id;

COMMENT ON VIEW analytics.vw_municipio IS 'Município → UF → região em uma linha só';


-- =========================================================================
-- vw_anos_disponiveis — quais anos cada série realmente tem
--
-- A série de população pula 2007, 2010, 2022 e 2023, e o PIB municipal começa
-- em 2010. Consultar esta view é mais seguro do que escrever o ano na mão.
-- =========================================================================

CREATE VIEW analytics.vw_anos_disponiveis AS
SELECT 'populacao' AS serie, 'municipio' AS nivel, ano, count(*) AS linhas
  FROM ibge.fato_populacao_municipio GROUP BY ano
UNION ALL
SELECT 'populacao', 'uf', ano, count(*)
  FROM ibge.fato_populacao_uf GROUP BY ano
UNION ALL
SELECT 'pib', 'municipio', ano, count(*)
  FROM ibge.fato_pib_municipio GROUP BY ano
UNION ALL
SELECT 'pib', 'uf', ano, count(*)
  FROM ibge.fato_pib_uf GROUP BY ano
UNION ALL
SELECT 'censo', 'municipio', ano, count(*)
  FROM ibge.fato_censo_municipio GROUP BY ano;


-- =========================================================================
-- vw_populacao_municipio — série histórica com variação entre observações
--
-- A variação é anualizada de propósito. Como a série tem buracos, a diferença
-- bruta entre 2021 e 2024 seria comparada, sem querer, com a diferença entre
-- 2005 e 2006 — três anos contra um. `var_pct_anualizada` divide pelo intervalo
-- real, que `anos_desde_anterior` expõe.
-- =========================================================================

CREATE VIEW analytics.vw_populacao_municipio AS
WITH serie AS (
    SELECT
        f.municipio_id,
        f.ano,
        f.populacao,
        lag(f.populacao) OVER w AS populacao_anterior,
        lag(f.ano)       OVER w AS ano_anterior
    FROM ibge.fato_populacao_municipio f
    WHERE f.populacao IS NOT NULL
    WINDOW w AS (PARTITION BY f.municipio_id ORDER BY f.ano)
)
SELECT
    m.municipio_id,
    m.municipio_nome,
    m.uf_sigla,
    m.uf_nome,
    m.regiao_nome,
    s.ano,
    s.populacao,
    s.populacao_anterior,
    s.ano - s.ano_anterior                          AS anos_desde_anterior,
    s.populacao - s.populacao_anterior              AS variacao_absoluta,
    round(
        (s.populacao::numeric / NULLIF(s.populacao_anterior, 0) - 1) * 100
    , 4)                                            AS variacao_pct,
    round((
        power(
            s.populacao::double precision / NULLIF(s.populacao_anterior, 0),
            1.0 / NULLIF(s.ano - s.ano_anterior, 0)
        ) - 1
    )::numeric * 100, 4)                            AS var_pct_anualizada
FROM serie s
JOIN analytics.vw_municipio m USING (municipio_id);


-- =========================================================================
-- vw_crescimento_municipio — CAGR entre o primeiro e o último ano da série
--
-- CAGR, e não variação total, porque os municípios não têm todos a mesma
-- janela: os instalados no meio da série têm menos anos, e comparar variações
-- acumuladas de janelas diferentes é comparar coisas diferentes.
--
-- O par (ano_inicial, ano_final) sai do dado, não de constante — um município
-- instalado em 2013 tem série começando em 2013.
-- =========================================================================

CREATE VIEW analytics.vw_crescimento_municipio AS
WITH extremos AS (
    SELECT DISTINCT ON (municipio_id)
        municipio_id,
        first_value(ano)       OVER w AS ano_inicial,
        first_value(populacao) OVER w AS valor_inicial,
        last_value(ano)        OVER w AS ano_final,
        last_value(populacao)  OVER w AS valor_final,
        count(*)               OVER (PARTITION BY municipio_id) AS n_observacoes
    FROM ibge.fato_populacao_municipio
    WHERE populacao IS NOT NULL
    WINDOW w AS (
        PARTITION BY municipio_id ORDER BY ano
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    )
),
calculado AS (
    SELECT
        e.*,
        e.ano_final - e.ano_inicial AS anos,
        e.valor_final - e.valor_inicial AS variacao_absoluta,
        round((e.valor_final::numeric / NULLIF(e.valor_inicial, 0) - 1) * 100, 4) AS variacao_pct,
        -- Série de um ponto só não tem CAGR: NULLIF zera o denominador do
        -- expoente e o resultado vira NULL. Deixar 0% aqui empurraria o
        -- município, calado, para a faixa "crescimento lento".
        round((
            power(
                e.valor_final::double precision / NULLIF(e.valor_inicial, 0),
                1.0 / NULLIF(e.ano_final - e.ano_inicial, 0)
            ) - 1
        )::numeric * 100, 4) AS cagr_pct
    FROM extremos e
    WHERE e.valor_inicial > 0
)
SELECT
    m.municipio_id,
    m.municipio_nome,
    m.uf_sigla,
    m.uf_nome,
    m.regiao_nome,
    c.ano_inicial,
    c.ano_final,
    c.anos,
    c.n_observacoes,
    c.valor_inicial,
    c.valor_final,
    c.variacao_absoluta,
    c.variacao_pct,
    c.cagr_pct,
    -- Cortes idênticos aos de transform.classificar_crescimento (pd.cut com
    -- right=True): intervalos fechados à direita.
    CASE
        WHEN c.cagr_pct IS NULL   THEN NULL
        WHEN c.cagr_pct <= -0.5   THEN 'Perda acentuada'
        WHEN c.cagr_pct <=  0.0   THEN 'Perda leve'
        WHEN c.cagr_pct <=  0.5   THEN 'Crescimento lento'
        WHEN c.cagr_pct <=  1.0   THEN 'Crescimento moderado'
        ELSE                           'Crescimento acelerado'
    END AS faixa_crescimento
FROM calculado c
JOIN analytics.vw_municipio m USING (municipio_id);


-- =========================================================================
-- mv_painel_municipio — um retrato por município, no ano mais recente
--
-- Materializada porque é o join central do projeto (5 fatos + 3 dimensões +
-- um LATERAL por linha) e porque quase toda consulta analítica parte dela.
-- Como os dados são anuais, o cache só precisa ser invalidado na carga.
--
-- Refresh: `ibge-db refresh` (usa REFRESH ... CONCURRENTLY graças ao índice
-- único em municipio_id, logo abaixo).
-- =========================================================================

CREATE MATERIALIZED VIEW analytics.mv_painel_municipio AS
WITH ano_pop AS (SELECT max(ano) AS ano FROM ibge.fato_populacao_municipio),
     ano_pib AS (SELECT max(ano) AS ano FROM ibge.fato_pib_municipio),
     -- O PIB total vai a 2023, mas o valor adicionado por setor para em 2021:
     -- o IBGE publica os dois no mesmo agregado (5938) e simplesmente deixa as
     -- variáveis setoriais nulas nos dois últimos anos. Tomar `max(ano)` para
     -- tudo zeraria a estrutura setorial inteira, calada. Cada bloco usa então
     -- o ano mais recente em que o SEU dado existe, e a view grava qual foi.
     ano_vab AS (
         SELECT max(ano) AS ano FROM ibge.fato_pib_municipio WHERE vab_industria IS NOT NULL
     )
SELECT
    m.municipio_id,
    m.municipio_nome,
    m.uf_id,
    m.uf_sigla,
    m.uf_nome,
    m.regiao_id,
    m.regiao_nome,
    m.mesorregiao_nome,

    (SELECT ano FROM ano_pop)                       AS ano_populacao,
    (SELECT ano FROM ano_pib)                       AS ano_pib,
    (SELECT ano FROM ano_vab)                       AS ano_vab,
    pop.populacao                                   AS populacao_atual,

    censo.populacao_censo,
    censo.area_km2,
    censo.densidade_hab_km2,

    pib.pib_mil_reais,

    -- De `ano_vab`, não de `ano_pib` — anos diferentes de propósito. Os
    -- impostos líquidos param no mesmo ano que o VAB: só a variável 37 (PIB
    -- total) segue até 2023.
    vab.impostos_liquidos,
    vab.vab_agropecuaria,
    vab.vab_industria,
    vab.vab_servicos,
    vab.vab_administracao_publica,

    cresc.cagr_pct,
    cresc.variacao_pct,
    cresc.variacao_absoluta,
    cresc.faixa_crescimento,
    cresc.ano_inicial                               AS ano_inicial_serie,

    -- Densidade sobre a população mais recente, não a censitária: o painel é
    -- um retrato de hoje, e a área praticamente não muda.
    round(pop.populacao / NULLIF(censo.area_km2, 0), 2)        AS densidade_atual,

    -- PIB per capita usa a população CONTEMPORÂNEA ao PIB. O PIB vai até 2023
    -- e a população até 2025; dividir um pelo outro subestimaria o indicador
    -- em dois anos de crescimento. `ano_populacao_pib` registra qual ano
    -- acabou sendo usado — como a série pula 2022 e 2023, não é 2023.
    pop_pib.ano                                                AS ano_populacao_pib,
    pop_pib.populacao                                          AS populacao_ano_pib,
    round(pib.pib_mil_reais * 1000 / NULLIF(pop_pib.populacao, 0), 2) AS pib_per_capita,

    -- Estrutura setorial: participação de cada setor no VAB total, no ano do VAB.
    round(vab.vab_agropecuaria          * 100 / NULLIF(vab.vab_agropecuaria + vab.vab_industria + vab.vab_servicos + vab.vab_administracao_publica, 0), 4) AS part_vab_agropecuaria,
    round(vab.vab_industria             * 100 / NULLIF(vab.vab_agropecuaria + vab.vab_industria + vab.vab_servicos + vab.vab_administracao_publica, 0), 4) AS part_vab_industria,
    round(vab.vab_servicos              * 100 / NULLIF(vab.vab_agropecuaria + vab.vab_industria + vab.vab_servicos + vab.vab_administracao_publica, 0), 4) AS part_vab_servicos,
    round(vab.vab_administracao_publica * 100 / NULLIF(vab.vab_agropecuaria + vab.vab_industria + vab.vab_servicos + vab.vab_administracao_publica, 0), 4) AS part_vab_administracao_publica,
    (vab.vab_agropecuaria + vab.vab_industria + vab.vab_servicos + vab.vab_administracao_publica) AS vab_total,

    -- Faixas de porte: mesmos cortes de analysis.populacao.FAIXAS_PORTE
    -- (pd.cut com right=False), logo fechados à esquerda.
    CASE
        WHEN pop.populacao IS NULL     THEN NULL
        WHEN pop.populacao <   5000    THEN 'Até 5 mil'
        WHEN pop.populacao <  10000    THEN '5 a 10 mil'
        WHEN pop.populacao <  20000    THEN '10 a 20 mil'
        WHEN pop.populacao <  50000    THEN '20 a 50 mil'
        WHEN pop.populacao < 100000    THEN '50 a 100 mil'
        WHEN pop.populacao < 500000    THEN '100 a 500 mil'
        ELSE                                'Mais de 500 mil'
    END AS porte
FROM analytics.vw_municipio m
LEFT JOIN ibge.fato_populacao_municipio pop
       ON pop.municipio_id = m.municipio_id AND pop.ano = (SELECT ano FROM ano_pop)
LEFT JOIN ibge.fato_censo_municipio censo
       ON censo.municipio_id = m.municipio_id
LEFT JOIN ibge.fato_pib_municipio pib
       ON pib.municipio_id = m.municipio_id AND pib.ano = (SELECT ano FROM ano_pib)
LEFT JOIN ibge.fato_pib_municipio vab
       ON vab.municipio_id = m.municipio_id AND vab.ano = (SELECT ano FROM ano_vab)
LEFT JOIN analytics.vw_crescimento_municipio cresc
       ON cresc.municipio_id = m.municipio_id
-- O ano de população mais próximo do ano do PIB, entre os efetivamente
-- publicados. LATERAL porque o "mais próximo" depende da linha, e o desempate
-- por `ano` mantém o resultado determinístico quando há empate na distância.
LEFT JOIN LATERAL (
    SELECT p.ano, p.populacao
    FROM ibge.fato_populacao_municipio p
    WHERE p.municipio_id = m.municipio_id
      AND p.populacao IS NOT NULL
    ORDER BY abs(p.ano - (SELECT ano FROM ano_pib)), p.ano
    LIMIT 1
) pop_pib ON true;

-- Único: exigido pelo REFRESH MATERIALIZED VIEW CONCURRENTLY, que mantém a
-- view legível durante a atualização.
CREATE UNIQUE INDEX ux_mv_painel_municipio ON analytics.mv_painel_municipio (municipio_id);
CREATE INDEX ix_mv_painel_uf       ON analytics.mv_painel_municipio (uf_sigla);
CREATE INDEX ix_mv_painel_regiao   ON analytics.mv_painel_municipio (regiao_nome);
CREATE INDEX ix_mv_painel_porte    ON analytics.mv_painel_municipio (porte);
CREATE INDEX ix_mv_painel_pib_pc   ON analytics.mv_painel_municipio (pib_per_capita DESC NULLS LAST);
CREATE INDEX ix_mv_painel_pop      ON analytics.mv_painel_municipio (populacao_atual DESC NULLS LAST);


-- =========================================================================
-- mv_concentracao_municipio — a curva de Lorenz, pré-calculada
--
-- Ordena os municípios do maior para o menor e acumula a participação. É o
-- que responde "quantos municípios fazem metade do PIB do país?" com um único
-- filtro, sem window function na hora da consulta.
--
-- Materializada: são duas ordenações completas de 5.571 linhas com soma
-- acumulada, e o resultado só muda quando os fatos mudam.
-- =========================================================================

CREATE MATERIALIZED VIEW analytics.mv_concentracao_municipio AS
WITH base AS (
    SELECT municipio_id, municipio_nome, uf_sigla, regiao_nome,
           populacao_atual, pib_mil_reais, area_km2
    FROM analytics.mv_painel_municipio
),
pop AS (
    SELECT
        municipio_id,
        'populacao'::text AS metrica,
        populacao_atual::numeric AS valor,
        row_number() OVER (ORDER BY populacao_atual DESC, municipio_id) AS posicao,
        sum(populacao_atual) OVER (ORDER BY populacao_atual DESC, municipio_id) AS valor_acumulado,
        sum(area_km2)        OVER (ORDER BY populacao_atual DESC, municipio_id) AS area_acumulada,
        sum(populacao_atual) OVER () AS valor_total,
        sum(area_km2)        OVER () AS area_total
    FROM base
    WHERE populacao_atual IS NOT NULL
),
pib AS (
    SELECT
        municipio_id,
        'pib'::text AS metrica,
        pib_mil_reais AS valor,
        row_number() OVER (ORDER BY pib_mil_reais DESC, municipio_id) AS posicao,
        sum(pib_mil_reais) OVER (ORDER BY pib_mil_reais DESC, municipio_id) AS valor_acumulado,
        sum(area_km2)      OVER (ORDER BY pib_mil_reais DESC, municipio_id) AS area_acumulada,
        sum(pib_mil_reais) OVER () AS valor_total,
        sum(area_km2)      OVER () AS area_total
    FROM base
    WHERE pib_mil_reais IS NOT NULL
),
uniao AS (SELECT * FROM pop UNION ALL SELECT * FROM pib)
SELECT
    u.metrica,
    u.posicao,
    b.municipio_id,
    b.municipio_nome,
    b.uf_sigla,
    b.regiao_nome,
    u.valor,
    u.valor_acumulado,
    round(u.valor          * 100 / NULLIF(u.valor_total, 0), 6) AS share_pct,
    round(u.valor_acumulado * 100 / NULLIF(u.valor_total, 0), 6) AS share_acumulado_pct,
    round(u.posicao        * 100.0 / count(*) OVER (PARTITION BY u.metrica), 6) AS pct_municipios,
    round(u.area_acumulada * 100 / NULLIF(u.area_total, 0), 6)  AS area_acumulada_pct
FROM uniao u
JOIN base b USING (municipio_id);

CREATE UNIQUE INDEX ux_mv_concentracao ON analytics.mv_concentracao_municipio (metrica, posicao);

COMMENT ON MATERIALIZED VIEW analytics.mv_concentracao_municipio
    IS 'Curva de Lorenz por município: share acumulado de população e de PIB, com a área ocupada';


-- =========================================================================
-- Painéis agregados
-- =========================================================================

CREATE VIEW analytics.vw_painel_uf AS
WITH ano_pop AS (SELECT max(ano) AS ano FROM ibge.fato_populacao_uf),
     ano_pib AS (SELECT max(ano) AS ano FROM ibge.fato_pib_uf),
     -- Mesmo descompasso do painel municipal: PIB total até 2023, VAB setorial
     -- até 2021. Ver o comentário em mv_painel_municipio.
     ano_vab AS (SELECT max(ano) AS ano FROM ibge.fato_pib_uf WHERE vab_industria IS NOT NULL),
base AS (
    SELECT
        u.uf_id, u.uf_sigla, u.uf_nome, r.regiao_id, r.regiao_nome,
        (SELECT ano FROM ano_pop) AS ano_populacao,
        (SELECT ano FROM ano_pib) AS ano_pib,
        (SELECT ano FROM ano_vab) AS ano_vab,
        pop.populacao   AS populacao_atual,
        c.populacao_censo, c.area_km2, c.densidade_hab_km2,
        pib.pib_mil_reais,
        vab.impostos_liquidos,
        vab.vab_agropecuaria, vab.vab_industria,
        vab.vab_servicos, vab.vab_administracao_publica,
        pop_pib.ano       AS ano_populacao_pib,
        pop_pib.populacao AS populacao_ano_pib
    FROM ibge.dim_uf u
    JOIN ibge.dim_regiao r ON r.regiao_id = u.regiao_id
    LEFT JOIN ibge.fato_populacao_uf pop ON pop.uf_id = u.uf_id AND pop.ano = (SELECT ano FROM ano_pop)
    LEFT JOIN ibge.fato_censo_uf     c   ON c.uf_id   = u.uf_id
    LEFT JOIN ibge.fato_pib_uf       pib ON pib.uf_id = u.uf_id AND pib.ano = (SELECT ano FROM ano_pib)
    LEFT JOIN ibge.fato_pib_uf       vab ON vab.uf_id = u.uf_id AND vab.ano = (SELECT ano FROM ano_vab)
    LEFT JOIN LATERAL (
        SELECT p.ano, p.populacao
        FROM ibge.fato_populacao_uf p
        WHERE p.uf_id = u.uf_id AND p.populacao IS NOT NULL
        ORDER BY abs(p.ano - (SELECT ano FROM ano_pib)), p.ano
        LIMIT 1
    ) pop_pib ON true
)
SELECT
    b.*,
    round(b.populacao_atual / NULLIF(b.area_km2, 0), 2)                   AS densidade_atual,
    round(b.pib_mil_reais * 1000 / NULLIF(b.populacao_ano_pib, 0), 2)     AS pib_per_capita,
    round(b.pib_mil_reais   * 100 / NULLIF(sum(b.pib_mil_reais)   OVER (), 0), 4) AS part_pib_brasil,
    round(b.populacao_atual * 100 / NULLIF(sum(b.populacao_atual) OVER (), 0), 4) AS part_pop_brasil,
    round(b.area_km2        * 100 / NULLIF(sum(b.area_km2)        OVER (), 0), 4) AS part_area_brasil,
    round(b.vab_agropecuaria          * 100 / NULLIF(b.vab_agropecuaria + b.vab_industria + b.vab_servicos + b.vab_administracao_publica, 0), 4) AS part_vab_agropecuaria,
    round(b.vab_industria             * 100 / NULLIF(b.vab_agropecuaria + b.vab_industria + b.vab_servicos + b.vab_administracao_publica, 0), 4) AS part_vab_industria,
    round(b.vab_servicos              * 100 / NULLIF(b.vab_agropecuaria + b.vab_industria + b.vab_servicos + b.vab_administracao_publica, 0), 4) AS part_vab_servicos,
    round(b.vab_administracao_publica * 100 / NULLIF(b.vab_agropecuaria + b.vab_industria + b.vab_servicos + b.vab_administracao_publica, 0), 4) AS part_vab_administracao_publica
FROM base b;


-- Região: soma das UFs, e não o fato regional do SIDRA. O agregado regional do
-- IBGE existe (`fato_populacao_regiao`), mas somar as UFs garante que o painel
-- regional e o estadual fechem entre si — ver a consulta `qualidade`, que
-- compara as duas fontes justamente para flagrar divergência.
CREATE VIEW analytics.vw_painel_regiao AS
WITH agregado AS (
    SELECT
        regiao_id,
        regiao_nome,
        count(*)                       AS n_ufs,
        sum(populacao_atual)           AS populacao_atual,
        sum(populacao_ano_pib)         AS populacao_ano_pib,
        sum(populacao_censo)           AS populacao_censo,
        sum(area_km2)                  AS area_km2,
        sum(pib_mil_reais)             AS pib_mil_reais,
        sum(vab_agropecuaria)          AS vab_agropecuaria,
        sum(vab_industria)             AS vab_industria,
        sum(vab_servicos)              AS vab_servicos,
        sum(vab_administracao_publica) AS vab_administracao_publica,
        min(ano_populacao)             AS ano_populacao,
        min(ano_pib)                   AS ano_pib,
        min(ano_vab)                   AS ano_vab
    FROM analytics.vw_painel_uf
    GROUP BY regiao_id, regiao_nome
),
com_municipios AS (
    SELECT a.*, (SELECT count(*) FROM analytics.vw_municipio m WHERE m.regiao_id = a.regiao_id) AS n_municipios
    FROM agregado a
)
SELECT
    c.*,
    round(c.populacao_atual / NULLIF(c.area_km2, 0), 2)               AS densidade_atual,
    round(c.pib_mil_reais * 1000 / NULLIF(c.populacao_ano_pib, 0), 2) AS pib_per_capita,
    round(c.pib_mil_reais   * 100 / NULLIF(sum(c.pib_mil_reais)   OVER (), 0), 4) AS part_pib_brasil,
    round(c.populacao_atual * 100 / NULLIF(sum(c.populacao_atual) OVER (), 0), 4) AS part_pop_brasil,
    round(c.area_km2        * 100 / NULLIF(sum(c.area_km2)        OVER (), 0), 4) AS part_area_brasil
FROM com_municipios c
-- Ordem canônica do IBGE (norte → sul), não alfabética.
ORDER BY array_position(
    ARRAY['Norte','Nordeste','Sudeste','Sul','Centro-Oeste'], c.regiao_nome
);


-- =========================================================================
-- vw_ranking_municipio — posição de cada município em cada indicador
--
-- Nacional e dentro da própria UF. `percent_rank` sobrevive a comparações
-- entre UFs de tamanhos muito diferentes, onde a posição absoluta não diz nada.
-- =========================================================================

CREATE VIEW analytics.vw_ranking_municipio AS
SELECT
    municipio_id,
    municipio_nome,
    uf_sigla,
    regiao_nome,
    populacao_atual,
    pib_mil_reais,
    pib_per_capita,
    densidade_atual,
    cagr_pct,

    rank() OVER (ORDER BY populacao_atual DESC NULLS LAST) AS rank_populacao,
    rank() OVER (ORDER BY pib_mil_reais   DESC NULLS LAST) AS rank_pib,
    rank() OVER (ORDER BY pib_per_capita  DESC NULLS LAST) AS rank_pib_per_capita,
    rank() OVER (ORDER BY densidade_atual DESC NULLS LAST) AS rank_densidade,
    rank() OVER (ORDER BY cagr_pct        DESC NULLS LAST) AS rank_crescimento,

    rank() OVER (PARTITION BY uf_sigla ORDER BY populacao_atual DESC NULLS LAST) AS rank_populacao_uf,
    rank() OVER (PARTITION BY uf_sigla ORDER BY pib_mil_reais   DESC NULLS LAST) AS rank_pib_uf,

    round(percent_rank() OVER (ORDER BY pib_per_capita ASC NULLS FIRST)::numeric * 100, 2) AS percentil_pib_per_capita,
    round(percent_rank() OVER (ORDER BY cagr_pct       ASC NULLS FIRST)::numeric * 100, 2) AS percentil_crescimento
FROM analytics.mv_painel_municipio;
