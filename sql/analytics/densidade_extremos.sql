-- Os dois extremos da ocupação do território, na mesma tabela.
--
-- Parâmetro: `limite` (quantos de cada ponta)
--
-- UNION ALL de duas janelas ordenadas em sentidos opostos. Sair numa tabela só
-- é o ponto: a distância entre as pontas — quatro ordens de grandeza — só
-- aparece quando as duas estão à vista.
(
    SELECT
        'Mais densos'  AS extremo,
        row_number() OVER (ORDER BY densidade_atual DESC) AS posicao,
        municipio_nome, uf_sigla, regiao_nome,
        populacao_atual, area_km2, densidade_atual, pib_per_capita, porte
    FROM analytics.mv_painel_municipio
    WHERE densidade_atual IS NOT NULL
    ORDER BY densidade_atual DESC
    LIMIT :limite
)
UNION ALL
(
    SELECT
        'Mais vazios',
        row_number() OVER (ORDER BY densidade_atual ASC),
        municipio_nome, uf_sigla, regiao_nome,
        populacao_atual, area_km2, densidade_atual, pib_per_capita, porte
    FROM analytics.mv_painel_municipio
    WHERE densidade_atual IS NOT NULL
    ORDER BY densidade_atual ASC
    LIMIT :limite
)
ORDER BY extremo DESC, posicao;
