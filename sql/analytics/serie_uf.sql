-- Série histórica de uma UF: população, PIB e PIB per capita ano a ano.
--
-- Parâmetro: `uf` (sigla, ex. 'SP'; use NULL para o Brasil inteiro)
--
-- FULL OUTER JOIN entre população e PIB porque as duas séries não cobrem os
-- mesmos anos: a população não publica 2007, 2010, 2022 e 2023; o PIB termina
-- em 2023. Um INNER JOIN silenciosamente descartaria as duas pontas da série.
--
-- O CAST em torno de `uf` não é decorativo. Com o parâmetro nulo o
-- PostgreSQL não consegue inferir o tipo de `$1 IS NULL` e recusa a
-- consulta (AmbiguousParameter). Escrever o cast como `uf` seguido de dois
-- dois-pontos e o tipo também não serve: o parser do SQLAlchemy quebra o
-- nome do bind ao meio e cria um parâmetro fantasma.
--
-- (Por isso os comentários deste diretório nunca escrevem o parâmetro com
-- dois-pontos: o SQLAlchemy varre o arquivo inteiro, comentário incluído.)
WITH pop AS (
    SELECT p.ano, sum(p.populacao) AS populacao
    FROM ibge.fato_populacao_uf p
    JOIN ibge.dim_uf u USING (uf_id)
    WHERE CAST(:uf AS text) IS NULL OR u.uf_sigla = upper(CAST(:uf AS text))
    GROUP BY p.ano
),
pib AS (
    SELECT p.ano,
           sum(p.pib_mil_reais)             AS pib_mil_reais,
           sum(p.vab_agropecuaria)          AS vab_agropecuaria,
           sum(p.vab_industria)             AS vab_industria,
           sum(p.vab_servicos)              AS vab_servicos,
           sum(p.vab_administracao_publica) AS vab_administracao_publica
    FROM ibge.fato_pib_uf p
    JOIN ibge.dim_uf u USING (uf_id)
    WHERE CAST(:uf AS text) IS NULL OR u.uf_sigla = upper(CAST(:uf AS text))
    GROUP BY p.ano
)
SELECT
    coalesce(pop.ano, pib.ano)              AS ano,
    coalesce(upper(CAST(:uf AS text)), 'BR') AS uf,
    pop.populacao,
    pop.populacao - lag(pop.populacao) OVER (ORDER BY pop.ano) AS variacao_populacao,
    round((pop.populacao::numeric / NULLIF(lag(pop.populacao) OVER (ORDER BY pop.ano), 0) - 1) * 100, 3) AS variacao_pct,
    pib.pib_mil_reais,
    round((pib.pib_mil_reais / NULLIF(lag(pib.pib_mil_reais) OVER (ORDER BY pib.ano), 0) - 1) * 100, 3) AS variacao_pib_pct,
    -- Só existe nos anos em que as duas séries se sobrepõem — daí o join externo.
    round(pib.pib_mil_reais * 1000 / NULLIF(pop.populacao, 0), 2) AS pib_per_capita,
    round(pib.vab_industria * 100 / NULLIF(pib.vab_agropecuaria + pib.vab_industria + pib.vab_servicos + pib.vab_administracao_publica, 0), 2) AS pct_industria,
    round(pib.vab_servicos  * 100 / NULLIF(pib.vab_agropecuaria + pib.vab_industria + pib.vab_servicos + pib.vab_administracao_publica, 0), 2) AS pct_servicos
FROM pop
FULL OUTER JOIN pib ON pib.ano = pop.ano
ORDER BY ano;
