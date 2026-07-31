-- Municípios onde o PIB e a população andam em direções opostas.
--
-- Parâmetro: `limite`
--
-- São dois fenômenos distintos no mesmo recorte: lugares que enriquecem
-- esvaziando (agro e mineração intensivos em capital) e lugares que incham
-- empobrecendo (periferia metropolitana). A coluna `padrao` separa os dois.
--
-- A comparação usa a mesma janela para as duas séries — o primeiro e o último
-- ano em que ambas existem —, senão o "crescimento do PIB" de um município
-- estaria medido em 14 anos e o da população em 21.
WITH janela AS (
    SELECT
        greatest(
            (SELECT min(ano) FROM ibge.fato_pib_municipio),
            (SELECT min(ano) FROM ibge.fato_populacao_municipio)
        ) AS ano_ini,
        least(
            (SELECT max(ano) FROM ibge.fato_pib_municipio),
            (SELECT max(ano) FROM ibge.fato_populacao_municipio)
        ) AS ano_fim
),
-- O ano de população efetivamente disponível mais próximo de cada ponta: a
-- série pula anos, então `ano_ini`/`ano_fim` podem não existir nela.
ancoras AS (
    SELECT
        (SELECT ano FROM ibge.fato_populacao_municipio
          WHERE ano >= j.ano_ini GROUP BY ano ORDER BY ano LIMIT 1)        AS pop_ini,
        (SELECT ano FROM ibge.fato_populacao_municipio
          WHERE ano <= j.ano_fim GROUP BY ano ORDER BY ano DESC LIMIT 1)   AS pop_fim,
        j.ano_ini AS pib_ini,
        j.ano_fim AS pib_fim
    FROM janela j
),
base AS (
    SELECT
        m.municipio_id, m.municipio_nome, m.uf_sigla, m.regiao_nome,
        p0.populacao AS pop_inicial, p1.populacao AS pop_final,
        g0.pib_mil_reais AS pib_inicial, g1.pib_mil_reais AS pib_final
    FROM analytics.vw_municipio m
    CROSS JOIN ancoras a
    JOIN ibge.fato_populacao_municipio p0 ON p0.municipio_id = m.municipio_id AND p0.ano = a.pop_ini
    JOIN ibge.fato_populacao_municipio p1 ON p1.municipio_id = m.municipio_id AND p1.ano = a.pop_fim
    JOIN ibge.fato_pib_municipio       g0 ON g0.municipio_id = m.municipio_id AND g0.ano = a.pib_ini
    JOIN ibge.fato_pib_municipio       g1 ON g1.municipio_id = m.municipio_id AND g1.ano = a.pib_fim
    WHERE p0.populacao > 0 AND g0.pib_mil_reais > 0
)
SELECT
    municipio_nome,
    uf_sigla,
    regiao_nome,
    pop_inicial,
    pop_final,
    round((pop_final::numeric / pop_inicial - 1) * 100, 2) AS var_populacao_pct,
    pib_inicial,
    pib_final,
    round((pib_final / pib_inicial - 1) * 100, 2)          AS var_pib_pct,
    round((pib_final / pib_inicial - 1) * 100
        - (pop_final::numeric / pop_inicial - 1) * 100, 2) AS descolamento_pp,
    CASE
        WHEN pop_final < pop_inicial AND pib_final > pib_inicial THEN 'Enriquece esvaziando'
        WHEN pop_final > pop_inicial AND pib_final < pib_inicial THEN 'Incha empobrecendo'
    END AS padrao
FROM base
WHERE (pop_final < pop_inicial) <> (pib_final < pib_inicial)
ORDER BY abs(
    (pib_final / pib_inicial - 1) - (pop_final::numeric / pop_inicial - 1)
) DESC
LIMIT :limite;
