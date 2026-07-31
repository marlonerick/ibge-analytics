-- Verificações de integridade da carga.
--
-- Sem parâmetros.
--
-- Roda depois de `ibge-db load`. As chaves estrangeiras já impedem órfão e a
-- PK já impede duplicata — o que sobra é o que o banco não consegue declarar:
-- lacunas esperadas, redundâncias entre níveis que devem fechar, e o dado
-- publicado batendo com o dado recalculado.
--
-- Status 'OK' em tudo é o esperado. 'ATENÇÃO' marca divergência conhecida e
-- documentada; 'FALHA' marca o que não deveria acontecer nunca.

-- Cobertura das dimensões -----------------------------------------------------
SELECT 'municípios na dimensão'                              AS verificacao,
       (SELECT count(*) FROM ibge.dim_municipio)::numeric    AS valor,
       '5.571 (malha vigente)'                               AS esperado,
       CASE WHEN (SELECT count(*) FROM ibge.dim_municipio) BETWEEN 5500 AND 5600
            THEN 'OK' ELSE 'FALHA' END                       AS status

UNION ALL
SELECT 'UFs na dimensão',
       (SELECT count(*) FROM ibge.dim_uf)::numeric, '27',
       CASE WHEN (SELECT count(*) FROM ibge.dim_uf) = 27 THEN 'OK' ELSE 'FALHA' END

UNION ALL
SELECT 'regiões na dimensão',
       (SELECT count(*) FROM ibge.dim_regiao)::numeric, '5',
       CASE WHEN (SELECT count(*) FROM ibge.dim_regiao) = 5 THEN 'OK' ELSE 'FALHA' END

-- Cobertura dos fatos ---------------------------------------------------------
UNION ALL
SELECT 'anos na série de população',
       (SELECT count(DISTINCT ano) FROM ibge.fato_populacao_municipio)::numeric,
       '21 (2001-2025 sem 2007, 2010, 2022, 2023)',
       CASE WHEN (SELECT count(DISTINCT ano) FROM ibge.fato_populacao_municipio) >= 20
            THEN 'OK' ELSE 'FALHA' END

UNION ALL
-- Municípios instalados depois do fim da série do PIB existem na população mas
-- não no PIB. É vigência territorial, não falha de join.
SELECT 'municípios sem PIB no último ano',
       (SELECT count(*) FROM analytics.mv_painel_municipio WHERE pib_mil_reais IS NULL)::numeric,
       '0 a 5 (instalados após o fim da série do PIB)',
       CASE WHEN (SELECT count(*) FROM analytics.mv_painel_municipio WHERE pib_mil_reais IS NULL) <= 5
            THEN 'OK' ELSE 'ATENÇÃO' END

UNION ALL
SELECT 'municípios sem área (Censo 2022)',
       (SELECT count(*) FROM analytics.mv_painel_municipio WHERE area_km2 IS NULL)::numeric,
       '0 a 5 (instalados após o Censo)',
       CASE WHEN (SELECT count(*) FROM analytics.mv_painel_municipio WHERE area_km2 IS NULL) <= 5
            THEN 'OK' ELSE 'ATENÇÃO' END

UNION ALL
SELECT 'municípios sem população no último ano',
       (SELECT count(*) FROM analytics.mv_painel_municipio WHERE populacao_atual IS NULL)::numeric,
       '0',
       CASE WHEN (SELECT count(*) FROM analytics.mv_painel_municipio WHERE populacao_atual IS NULL) = 0
            THEN 'OK' ELSE 'FALHA' END

-- Consistência entre níveis territoriais ---------------------------------------
-- O SIDRA publica cada nível separadamente. Se a soma dos municípios não
-- fechar com o total da UF, um dos dois foi extraído errado.
UNION ALL
SELECT 'soma dos municípios vs. total das UFs (população)',
       round(abs(
           (SELECT sum(populacao) FROM ibge.fato_populacao_municipio
             WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_municipio))::numeric
         - (SELECT sum(populacao) FROM ibge.fato_populacao_uf
             WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_uf))::numeric
       ) * 100 / NULLIF((SELECT sum(populacao) FROM ibge.fato_populacao_uf
                          WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_uf)), 0), 6),
       'divergência < 0,01%',
       CASE WHEN abs(
           (SELECT sum(populacao) FROM ibge.fato_populacao_municipio
             WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_municipio))::numeric
         - (SELECT sum(populacao) FROM ibge.fato_populacao_uf
             WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_uf))::numeric
       ) * 100 / NULLIF((SELECT sum(populacao) FROM ibge.fato_populacao_uf
                          WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_uf)), 0) < 0.01
       THEN 'OK' ELSE 'ATENÇÃO' END

UNION ALL
SELECT 'soma das UFs vs. agregado regional (população)',
       round(abs(
           (SELECT sum(populacao) FROM ibge.fato_populacao_uf
             WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_uf))::numeric
         - coalesce((SELECT sum(populacao) FROM ibge.fato_populacao_regiao
             WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_uf)), 0)::numeric
       ), 0),
       'diferença de 0 habitantes',
       CASE WHEN abs(
           (SELECT sum(populacao) FROM ibge.fato_populacao_uf
             WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_uf))::numeric
         - coalesce((SELECT sum(populacao) FROM ibge.fato_populacao_regiao
             WHERE ano = (SELECT max(ano) FROM ibge.fato_populacao_uf)), 0)::numeric
       ) <= 1 THEN 'OK' ELSE 'ATENÇÃO' END

-- Dado publicado vs. dado recalculado ------------------------------------------
-- O Censo publica a densidade (variável 614). Recalculamos população ÷ área e
-- comparamos: divergência real indicaria que área e população vieram de
-- extrações diferentes.
--
-- A tolerância é dupla, e tem de ser. O IBGE publica a densidade com 2 casas
-- decimais, então um município de 0,1538 hab/km² sai como 0,15 — uma diferença
-- de 2,5% em termos relativos, que é só o arredondamento. Exigir as duas
-- condições (1% relativo E meia casa decimal em absoluto) separa erro de carga
-- de precisão de publicação; só o critério relativo acusaria os cinco
-- municípios mais vazios do país como se fossem defeito.
UNION ALL
SELECT 'densidade publicada vs. recalculada (divergência real)',
       (SELECT count(*) FROM ibge.fato_censo_municipio
         WHERE densidade_hab_km2 IS NOT NULL AND area_km2 > 0
           AND abs(densidade_hab_km2 - populacao_censo / area_km2) > 0.01 * densidade_hab_km2
           AND abs(densidade_hab_km2 - populacao_censo / area_km2) > 0.005)::numeric,
       '0',
       CASE WHEN (SELECT count(*) FROM ibge.fato_censo_municipio
                   WHERE densidade_hab_km2 IS NOT NULL AND area_km2 > 0
                     AND abs(densidade_hab_km2 - populacao_censo / area_km2) > 0.01 * densidade_hab_km2
                     AND abs(densidade_hab_km2 - populacao_censo / area_km2) > 0.005) = 0
            THEN 'OK' ELSE 'FALHA' END

-- Plausibilidade ---------------------------------------------------------------
UNION ALL
SELECT 'municípios com CAGR fora de ±10% a.a.',
       (SELECT count(*) FROM analytics.vw_crescimento_municipio
         WHERE cagr_pct IS NOT NULL AND abs(cagr_pct) > 10)::numeric,
       '0 a 20 (municípios novos, com série curta)',
       CASE WHEN (SELECT count(*) FROM analytics.vw_crescimento_municipio
                   WHERE cagr_pct IS NOT NULL AND abs(cagr_pct) > 10) <= 20
            THEN 'OK' ELSE 'ATENÇÃO' END

UNION ALL
-- PIB exatamente zero seria falha de carga: não existe município sem economia.
SELECT 'PIB municipal zerado',
       (SELECT count(*) FROM ibge.fato_pib_municipio WHERE pib_mil_reais = 0)::numeric,
       '0',
       CASE WHEN (SELECT count(*) FROM ibge.fato_pib_municipio WHERE pib_mil_reais = 0) = 0
            THEN 'OK' ELSE 'FALHA' END

UNION ALL
-- PIB negativo, ao contrário, é dado legítimo. O valor adicionado de um setor
-- pode ser negativo quando o consumo intermediário supera a produção no ano —
-- Guamaré/RN em 2012 é o caso conhecido, com VAB industrial de -417 milhões
-- num município de refinaria. Por isso o schema não tem CHECK de positividade
-- no PIB: seria uma regra que os dados reais violam.
SELECT 'PIB municipal negativo',
       (SELECT count(*) FROM ibge.fato_pib_municipio WHERE pib_mil_reais < 0)::numeric,
       '0 a 5 (VAB setorial negativo é possível)',
       CASE WHEN (SELECT count(*) FROM ibge.fato_pib_municipio WHERE pib_mil_reais < 0) <= 5
            THEN 'OK' ELSE 'ATENÇÃO' END

-- Coluna inteiramente nula -----------------------------------------------------
-- A verificação genérica que as duas específicas acima não davam: uma coluna do
-- painel 100% nula quase sempre significa que ela foi buscada no ano errado.
-- Aconteceu duas vezes — com o VAB setorial e com os impostos líquidos, ambos
-- publicados só até 2021 enquanto o PIB total vai até 2023. Cada caso custou
-- uma inspeção manual; este bloco os denuncia na carga seguinte.
--
-- Lê pg_stats em vez de contar coluna a coluna: o ANALYZE já mediu a fração de
-- nulos de cada uma, e null_frac = 1 é exatamente a pergunta.
UNION ALL
SELECT 'colunas 100% nulas em mv_painel_municipio',
       (SELECT count(*) FROM pg_stats
         WHERE schemaname = 'analytics' AND tablename = 'mv_painel_municipio'
           AND null_frac = 1)::numeric,
       '0 (coluna toda nula = buscada no ano errado)',
       CASE WHEN (SELECT count(*) FROM pg_stats
                   WHERE schemaname = 'analytics' AND tablename = 'mv_painel_municipio'
                     AND null_frac = 1) = 0
            THEN 'OK' ELSE 'FALHA' END

-- Frescor ----------------------------------------------------------------------
UNION ALL
SELECT 'horas desde a última carga',
       round(extract(epoch FROM now() - (SELECT max(iniciado_em) FROM ibge.carga_log)) / 3600, 1),
       'a carga já rodou ao menos uma vez',
       CASE WHEN (SELECT count(*) FROM ibge.carga_log) > 0 THEN 'OK' ELSE 'FALHA' END;
