-- Especialização produtiva das UFs (quociente locacional).
--
-- Sem parâmetros.
--
--     QL = (VAB do setor na UF / VAB total da UF)
--        ÷ (VAB do setor no Brasil / VAB total do Brasil)
--
-- QL > 1 significa que o setor pesa mais na UF do que pesa no país. É a métrica
-- que separa "estado com muita indústria" de "estado grande" — a participação
-- bruta confunde as duas coisas, o quociente não.
--
-- O VALUES lateral transforma as quatro colunas de VAB em quatro linhas: sem
-- ele, cada setor precisaria de uma query própria ou de um UNION de quatro.
WITH longo AS (
    SELECT p.uf_sigla, p.uf_nome, p.regiao_nome, s.setor, s.vab
    FROM analytics.vw_painel_uf p
    CROSS JOIN LATERAL (VALUES
        ('Agropecuária',          p.vab_agropecuaria),
        ('Indústria',             p.vab_industria),
        ('Serviços',              p.vab_servicos),
        ('Administração pública', p.vab_administracao_publica)
    ) AS s(setor, vab)
    WHERE p.vab_agropecuaria IS NOT NULL
),
shares AS (
    SELECT
        uf_sigla, uf_nome, regiao_nome, setor, vab,
        vab / NULLIF(sum(vab) OVER (PARTITION BY uf_sigla), 0) AS share_uf,
        sum(vab) OVER (PARTITION BY setor) / NULLIF(sum(vab) OVER (), 0) AS share_brasil
    FROM longo
)
SELECT
    uf_sigla,
    uf_nome,
    regiao_nome,
    setor,
    vab                                          AS vab_mil_reais,
    round(share_uf     * 100, 2)                 AS part_na_uf_pct,
    round(share_brasil * 100, 2)                 AS part_no_brasil_pct,
    round(share_uf / NULLIF(share_brasil, 0), 3) AS quociente_locacional,
    CASE
        WHEN share_uf / NULLIF(share_brasil, 0) >= 1.5 THEN 'Muito especializada'
        WHEN share_uf / NULLIF(share_brasil, 0) >= 1.2 THEN 'Especializada'
        WHEN share_uf / NULLIF(share_brasil, 0) >= 0.8 THEN 'Perfil nacional'
        ELSE                                                'Sub-representada'
    END AS leitura
FROM shares
ORDER BY setor, quociente_locacional DESC;
