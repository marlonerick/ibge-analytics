-- Esvaziamento populacional por UF: quantos municípios encolhem, e quanto.
--
-- Sem parâmetros.
--
-- O agregado esconde o fenômeno — o país cresce enquanto boa parte dos
-- municípios perde gente. Este recorte separa as duas coisas: a soma líquida
-- por UF e a contagem de municípios em queda dentro dela.
SELECT
    c.uf_sigla,
    c.uf_nome,
    c.regiao_nome,
    count(*)                                                          AS n_municipios,
    count(*) FILTER (WHERE c.cagr_pct < 0)                            AS n_em_declinio,
    round(count(*) FILTER (WHERE c.cagr_pct < 0) * 100.0 / count(*), 2) AS pct_em_declinio,
    count(*) FILTER (WHERE c.faixa_crescimento = 'Perda acentuada')   AS n_perda_acentuada,

    -- População perdida pelos que encolhem, contra a ganha pelos que crescem.
    -- FILTER dentro do agregado evita varrer a tabela duas vezes.
    sum(c.variacao_absoluta) FILTER (WHERE c.cagr_pct < 0)            AS populacao_perdida,
    sum(c.variacao_absoluta) FILTER (WHERE c.cagr_pct >= 0)           AS populacao_ganha,
    sum(c.variacao_absoluta)                                          AS saldo_liquido,

    round(avg(c.cagr_pct), 4)                                         AS cagr_medio,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY c.cagr_pct)::numeric, 4) AS cagr_mediano
FROM analytics.vw_crescimento_municipio c
GROUP BY c.uf_sigla, c.uf_nome, c.regiao_nome
ORDER BY pct_em_declinio DESC;
