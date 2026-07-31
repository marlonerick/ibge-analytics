-- =========================================================================
-- Índices.
--
-- Separado do schema de propósito: um índice é uma decisão de desempenho, não
-- de modelagem, e a lista abaixo existe para atender consultas concretas. Cada
-- bloco diz qual.
--
-- As chaves primárias já cobrem os acessos por entidade — (municipio_id, ano)
-- resolve "a série deste município". O que falta, e é o padrão dominante das
-- análises, é o oposto: "todos os municípios de um ano".
-- =========================================================================


-- ------------------------------------------------------------------ dimensões
-- Percorrer a hierarquia de baixo para cima. Sem esses, todo agrupamento por
-- UF ou região faz seq scan nas dimensões — barato isoladamente, caro quando
-- aparece em nested loop dentro das views municipais.

CREATE INDEX IF NOT EXISTS ix_dim_municipio_uf     ON ibge.dim_municipio (uf_id);
CREATE INDEX IF NOT EXISTS ix_dim_municipio_meso   ON ibge.dim_municipio (mesorregiao_id);
CREATE INDEX IF NOT EXISTS ix_dim_uf_regiao        ON ibge.dim_uf (regiao_id);

-- Busca de município por nome digitado ("qual é o código de Piracicaba?").
-- lower() para casar a expressão exata que as consultas usam.
CREATE INDEX IF NOT EXISTS ix_dim_municipio_nome   ON ibge.dim_municipio (lower(municipio_nome));


-- ----------------------------------------------------------------- população
-- Recorte por ano: a PK é (municipio_id, ano), então `WHERE ano = 2025`
-- sozinho não tem índice utilizável.
CREATE INDEX IF NOT EXISTS ix_fato_pop_mun_ano ON ibge.fato_populacao_municipio (ano);

-- Ranking e top-N dentro de um ano. INCLUDE carrega o município na folha, o
-- que torna "os 50 maiores de 2025" um index-only scan — sem tocar a heap.
CREATE INDEX IF NOT EXISTS ix_fato_pop_mun_ano_rank
    ON ibge.fato_populacao_municipio (ano, populacao DESC)
    INCLUDE (municipio_id)
    WHERE populacao IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_fato_pop_uf_ano ON ibge.fato_populacao_uf (ano);


-- ----------------------------------------------------------------------- PIB
CREATE INDEX IF NOT EXISTS ix_fato_pib_mun_ano ON ibge.fato_pib_municipio (ano);

-- Concentração do PIB: ordena o ano inteiro por valor decrescente e soma
-- acumulado. É a consulta mais cara do projeto — este índice a entrega já
-- ordenada, dispensando o sort de 5.570 linhas por ano analisado.
CREATE INDEX IF NOT EXISTS ix_fato_pib_mun_ano_rank
    ON ibge.fato_pib_municipio (ano, pib_mil_reais DESC)
    INCLUDE (municipio_id)
    WHERE pib_mil_reais IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_fato_pib_uf_ano ON ibge.fato_pib_uf (ano);


-- --------------------------------------------------------------------- censo
-- Extremos de densidade e de área. NULLS LAST casa a ordenação que as
-- consultas pedem, para que o índice sirva ao ORDER BY sem sort adicional.
CREATE INDEX IF NOT EXISTS ix_fato_censo_mun_densidade
    ON ibge.fato_censo_municipio (densidade_hab_km2 DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS ix_fato_censo_mun_area
    ON ibge.fato_censo_municipio (area_km2 DESC NULLS LAST);


-- -------------------------------------------------------------------- carga
-- "Qual foi a última carga desta tabela?" — sempre lida em ordem decrescente.
CREATE INDEX IF NOT EXISTS ix_carga_log_tabela_data
    ON ibge.carga_log (tabela, iniciado_em DESC);
