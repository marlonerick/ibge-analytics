-- Quantos municípios concentram cada fatia da população e do PIB do país.
--
-- Sem parâmetros.
--
-- Lê a curva de Lorenz já materializada e pega, para cada corte, o primeiro
-- município em que o acumulado cruza o limiar — DISTINCT ON faz isso em uma
-- passada, sem subconsulta correlacionada por corte.
WITH cortes(limiar) AS (VALUES (10), (25), (50), (75), (90)),
     total_municipios AS (
         SELECT metrica, count(*) AS n FROM analytics.mv_concentracao_municipio GROUP BY metrica
     )
SELECT DISTINCT ON (c.metrica, k.limiar)
    c.metrica,
    k.limiar                                                        AS pct_alvo,
    c.posicao                                                       AS n_municipios,
    round(c.posicao * 100.0 / t.n, 2)                               AS pct_dos_municipios,
    round(c.share_acumulado_pct, 2)                                 AS pct_atingido,
    round(c.area_acumulada_pct, 2)                                  AS pct_do_territorio,
    c.municipio_nome || ' (' || c.uf_sigla || ')'                   AS municipio_de_corte
FROM analytics.mv_concentracao_municipio c
JOIN total_municipios t USING (metrica)
CROSS JOIN cortes k
WHERE c.share_acumulado_pct >= k.limiar
ORDER BY c.metrica, k.limiar, c.posicao;
