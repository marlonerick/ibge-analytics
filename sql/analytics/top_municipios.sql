-- Os `limite` municípios no topo de um indicador, com a participação nacional.
--
-- Parâmetros: `metrica` ('populacao' | 'pib' | 'pib_per_capita' | 'densidade' | 'crescimento')
--             `limite`
--
-- A métrica entra como valor, não como nome de coluna interpolado — um CASE
-- resolve a escolha dentro do próprio plano, sem montar SQL por concatenação.
WITH escolhido AS (
    SELECT
        municipio_id, municipio_nome, uf_sigla, regiao_nome,
        populacao_atual, pib_mil_reais, pib_per_capita, densidade_atual, cagr_pct,
        CASE :metrica
            WHEN 'populacao'      THEN populacao_atual::numeric
            WHEN 'pib'            THEN pib_mil_reais
            WHEN 'pib_per_capita' THEN pib_per_capita
            WHEN 'densidade'      THEN densidade_atual
            WHEN 'crescimento'    THEN cagr_pct
        END AS valor
    FROM analytics.mv_painel_municipio
)
SELECT
    row_number() OVER (ORDER BY valor DESC) AS posicao,
    municipio_nome,
    uf_sigla,
    regiao_nome,
    valor,
    -- Share só faz sentido para métricas somáveis. Per capita, densidade e
    -- CAGR são razões: somá-las para achar um total não significaria nada.
    CASE WHEN :metrica IN ('populacao', 'pib')
         THEN round(valor * 100 / NULLIF(sum(valor) OVER (), 0), 4)
    END AS share_pct,
    CASE WHEN :metrica IN ('populacao', 'pib')
         THEN round(sum(valor) OVER (ORDER BY valor DESC) * 100 / NULLIF(sum(valor) OVER (), 0), 4)
    END AS share_acumulado_pct,
    populacao_atual,
    pib_mil_reais,
    pib_per_capita
FROM escolhido
WHERE valor IS NOT NULL
ORDER BY valor DESC
LIMIT :limite;
