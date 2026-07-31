-- A rede urbana brasileira por faixa de porte.
--
-- Sem parâmetros.
--
-- O contraste central: a maioria dos municípios é pequena, mas a maioria da
-- população não vive neles. As duas colunas de share dizem isso lado a lado.
WITH por_porte AS (
    SELECT
        porte,
        count(*)                                          AS n_municipios,
        sum(populacao_atual)                              AS populacao,
        sum(area_km2)                                     AS area_km2,
        sum(pib_mil_reais)                                AS pib_mil_reais,
        round(avg(pib_per_capita), 2)                     AS pib_per_capita_medio,
        round(avg(cagr_pct), 4)                           AS cagr_medio
    FROM analytics.mv_painel_municipio
    WHERE porte IS NOT NULL
    GROUP BY porte
)
SELECT
    porte,
    n_municipios,
    round(n_municipios * 100.0 / sum(n_municipios) OVER (), 2) AS pct_municipios,
    populacao,
    round(populacao * 100.0 / NULLIF(sum(populacao) OVER (), 0), 2) AS pct_populacao,
    round(pib_mil_reais * 100 / NULLIF(sum(pib_mil_reais) OVER (), 0), 2) AS pct_pib,
    round(area_km2 * 100 / NULLIF(sum(area_km2) OVER (), 0), 2) AS pct_area,
    pib_per_capita_medio,
    cagr_medio
FROM por_porte
-- Ordem crescente de porte, não alfabética do rótulo.
ORDER BY array_position(
    ARRAY['Até 5 mil','5 a 10 mil','10 a 20 mil','20 a 50 mil',
          '50 a 100 mil','100 a 500 mil','Mais de 500 mil'], porte
);
