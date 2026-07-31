-- Comparação entre as cinco grandes regiões.
--
-- Sem parâmetros.
--
-- As três colunas de share (população, PIB, território) lado a lado são o
-- ponto: a desigualdade regional aparece na distância entre elas, não no valor
-- de nenhuma isoladamente.
SELECT
    regiao_nome,
    n_ufs,
    n_municipios,
    populacao_atual,
    part_pop_brasil        AS pct_populacao,
    pib_mil_reais,
    part_pib_brasil        AS pct_pib,
    area_km2,
    part_area_brasil       AS pct_area,
    densidade_atual        AS densidade_hab_km2,
    pib_per_capita,
    -- Razão entre a fatia do PIB e a fatia da população: acima de 1, a região
    -- produz mais do que sua população proporcional sugeriria.
    round(part_pib_brasil / NULLIF(part_pop_brasil, 0), 3) AS razao_pib_populacao,
    round(vab_agropecuaria          * 100 / NULLIF(vab_agropecuaria + vab_industria + vab_servicos + vab_administracao_publica, 0), 2) AS pct_agropecuaria,
    round(vab_industria             * 100 / NULLIF(vab_agropecuaria + vab_industria + vab_servicos + vab_administracao_publica, 0), 2) AS pct_industria,
    round(vab_servicos              * 100 / NULLIF(vab_agropecuaria + vab_industria + vab_servicos + vab_administracao_publica, 0), 2) AS pct_servicos,
    round(vab_administracao_publica * 100 / NULLIF(vab_agropecuaria + vab_industria + vab_servicos + vab_administracao_publica, 0), 2) AS pct_administracao_publica,
    ano_populacao,
    ano_pib,
    -- Diferente de `ano_pib`: o VAB setorial para dois anos antes do PIB total.
    ano_vab
FROM analytics.vw_painel_regiao;
