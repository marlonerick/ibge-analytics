-- Ficha completa de um município: indicadores, posição nos rankings e série.
--
-- Parâmetro: `municipio` (código IBGE de 7 dígitos ou nome)
--
-- O nome casa por `lower()` para aproveitar o índice ix_dim_municipio_nome —
-- `ILIKE` sem curinga faria seq scan. Nomes se repetem entre UFs (há quatro
-- "Bom Jesus"), então o resultado pode trazer mais de uma linha; o código é o
-- desempate confiável.
WITH alvo AS (
    SELECT municipio_id
    FROM ibge.dim_municipio
    WHERE municipio_id = :municipio
       OR lower(municipio_nome) = lower(:municipio)
)
SELECT
    p.municipio_id,
    p.municipio_nome,
    p.uf_sigla,
    p.regiao_nome,
    p.mesorregiao_nome,

    p.ano_populacao,
    p.populacao_atual,
    p.populacao_censo,
    p.area_km2,
    p.densidade_atual,

    p.ano_pib,
    p.pib_mil_reais,
    p.ano_populacao_pib,
    p.pib_per_capita,
    p.ano_vab,
    p.part_vab_agropecuaria,
    p.part_vab_industria,
    p.part_vab_servicos,
    p.part_vab_administracao_publica,

    p.ano_inicial_serie,
    p.cagr_pct,
    p.variacao_pct,
    p.faixa_crescimento,
    p.porte,

    r.rank_populacao,
    r.rank_pib,
    r.rank_pib_per_capita,
    r.rank_densidade,
    r.rank_populacao_uf,
    r.rank_pib_uf,
    r.percentil_pib_per_capita,
    r.percentil_crescimento,

    -- Série de população compactada em um array de "ano:valor", para caber
    -- numa ficha de uma linha por município.
    (
        SELECT array_agg(f.ano || ':' || f.populacao ORDER BY f.ano)
        FROM ibge.fato_populacao_municipio f
        WHERE f.municipio_id = p.municipio_id AND f.populacao IS NOT NULL
    ) AS serie_populacao
FROM analytics.mv_painel_municipio p
JOIN analytics.vw_ranking_municipio r USING (municipio_id)
WHERE p.municipio_id IN (SELECT municipio_id FROM alvo)
ORDER BY p.populacao_atual DESC NULLS LAST;
