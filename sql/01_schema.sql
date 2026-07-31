-- =========================================================================
-- Modelo dimensional dos dados do IBGE.
--
-- Duas camadas, em schemas separados:
--   ibge.*       fatos e dimensões carregados do pipeline (data/raw/)
--   analytics.*  views derivadas (03_views.sql) — nada é gravado aqui
--
-- O que entra em `ibge` é o dado cru normalizado, na granularidade em que o
-- SIDRA publica. Toda métrica derivada (densidade, per capita, CAGR, share)
-- vive em `analytics`, para que recarregar os fatos nunca invalide um número
-- calculado — ele é recalculado por definição.
--
-- Idempotente: pode rodar sobre um banco já inicializado sem perder dados.
-- =========================================================================

CREATE SCHEMA IF NOT EXISTS ibge;
CREATE SCHEMA IF NOT EXISTS analytics;

COMMENT ON SCHEMA ibge      IS 'Fatos e dimensões do IBGE (SIDRA v3 + Localidades v1)';
COMMENT ON SCHEMA analytics IS 'Views analíticas derivadas — sem tabelas próprias';


-- =========================================================================
-- Dimensões territoriais (Localidades v1)
-- =========================================================================

CREATE TABLE IF NOT EXISTS ibge.dim_regiao (
    regiao_id    smallint    PRIMARY KEY,
    regiao_sigla char(2)     NOT NULL UNIQUE,
    regiao_nome  text        NOT NULL UNIQUE
);

COMMENT ON TABLE ibge.dim_regiao IS 'As 5 grandes regiões';

CREATE TABLE IF NOT EXISTS ibge.dim_uf (
    uf_id     smallint PRIMARY KEY,
    uf_sigla  char(2)  NOT NULL UNIQUE,
    uf_nome   text     NOT NULL,
    regiao_id smallint NOT NULL REFERENCES ibge.dim_regiao (regiao_id)
);

COMMENT ON TABLE ibge.dim_uf IS 'As 27 unidades da federação';

-- O código de município do IBGE é um identificador de 7 dígitos com dígito
-- verificador — nunca um número. Guardar como char(7) preserva zeros à
-- esquerda e impede que alguém some a coluna por acidente.
CREATE TABLE IF NOT EXISTS ibge.dim_municipio (
    municipio_id      char(7)  PRIMARY KEY,
    municipio_nome    text     NOT NULL,
    -- Municípios instalados recentemente ainda não têm micro/mesorregião
    -- atribuída na malha vigente; a coluna é nula por vigência, não por erro.
    microrregiao_id   integer,
    microrregiao_nome text,
    mesorregiao_id    integer,
    mesorregiao_nome  text,
    uf_id             smallint NOT NULL REFERENCES ibge.dim_uf (uf_id),

    CONSTRAINT dim_municipio_id_numerico CHECK (municipio_id ~ '^[0-9]{7}$'),
    -- Os dois primeiros dígitos do código municipal são o código da UF.
    CONSTRAINT dim_municipio_prefixo_uf  CHECK (left(municipio_id, 2) = uf_id::text)
);

COMMENT ON TABLE  ibge.dim_municipio               IS 'Municípios vigentes com a hierarquia territorial completa';
COMMENT ON COLUMN ibge.dim_municipio.municipio_id  IS 'Código IBGE de 7 dígitos; os 2 primeiros são o código da UF';


-- =========================================================================
-- Fatos: população residente estimada (agregado 6579)
--
-- A série não publica 2007, 2010, 2022 e 2023 — os anos simplesmente não
-- existem como linha. Nenhuma view deve assumir continuidade anual.
-- =========================================================================

CREATE TABLE IF NOT EXISTS ibge.fato_populacao_municipio (
    municipio_id char(7)  NOT NULL REFERENCES ibge.dim_municipio (municipio_id) ON DELETE CASCADE,
    ano          smallint NOT NULL,
    populacao    bigint,

    PRIMARY KEY (municipio_id, ano),
    CONSTRAINT fato_pop_mun_ano_plausivel CHECK (ano BETWEEN 1990 AND 2100),
    CONSTRAINT fato_pop_mun_nao_negativa  CHECK (populacao IS NULL OR populacao >= 0)
);

CREATE TABLE IF NOT EXISTS ibge.fato_populacao_uf (
    uf_id     smallint NOT NULL REFERENCES ibge.dim_uf (uf_id) ON DELETE CASCADE,
    ano       smallint NOT NULL,
    populacao bigint,

    PRIMARY KEY (uf_id, ano),
    CONSTRAINT fato_pop_uf_ano_plausivel CHECK (ano BETWEEN 1990 AND 2100)
);

CREATE TABLE IF NOT EXISTS ibge.fato_populacao_regiao (
    regiao_id smallint NOT NULL REFERENCES ibge.dim_regiao (regiao_id) ON DELETE CASCADE,
    ano       smallint NOT NULL,
    populacao bigint,

    PRIMARY KEY (regiao_id, ano)
);

CREATE TABLE IF NOT EXISTS ibge.fato_populacao_brasil (
    ano       smallint PRIMARY KEY,
    populacao bigint
);


-- =========================================================================
-- Fatos: Censo 2022 — população, área e densidade (agregado 4714)
--
-- Um retrato único (2022), não uma série. A área territorial só existe aqui:
-- é a única fonte oficial que a publica por município.
-- =========================================================================

CREATE TABLE IF NOT EXISTS ibge.fato_censo_municipio (
    municipio_id      char(7)       PRIMARY KEY REFERENCES ibge.dim_municipio (municipio_id) ON DELETE CASCADE,
    ano               smallint      NOT NULL,
    populacao_censo   bigint,
    area_km2          numeric(14,3),
    densidade_hab_km2 numeric(14,2),

    CONSTRAINT fato_censo_mun_area_positiva CHECK (area_km2 IS NULL OR area_km2 > 0)
);

COMMENT ON COLUMN ibge.fato_censo_municipio.densidade_hab_km2
    IS 'Densidade publicada pelo IBGE (variável 614) — mantida para conferência; analytics recalcula';

CREATE TABLE IF NOT EXISTS ibge.fato_censo_uf (
    uf_id             smallint      PRIMARY KEY REFERENCES ibge.dim_uf (uf_id) ON DELETE CASCADE,
    ano               smallint      NOT NULL,
    populacao_censo   bigint,
    area_km2          numeric(14,3),
    densidade_hab_km2 numeric(14,2)
);

CREATE TABLE IF NOT EXISTS ibge.fato_censo_regiao (
    regiao_id         smallint      PRIMARY KEY REFERENCES ibge.dim_regiao (regiao_id) ON DELETE CASCADE,
    ano               smallint      NOT NULL,
    populacao_censo   bigint,
    area_km2          numeric(14,3),
    densidade_hab_km2 numeric(14,2)
);


-- =========================================================================
-- Fatos: PIB a preços correntes e valor adicionado por setor (agregado 5938)
--
-- Valores em MIL reais, como o SIDRA publica. Nenhuma conversão na carga —
-- converter na origem esconderia a unidade real do dado. As views multiplicam
-- por 1.000 onde o número precisa sair em reais.
--
-- Não há CHECK de positividade no PIB nem no VAB, de propósito: o valor
-- adicionado de um setor pode ser negativo quando o consumo intermediário
-- supera a produção no ano. Guamaré/RN em 2012 tem VAB industrial de -417
-- milhões e PIB total negativo. Uma constraint "pib > 0" recusaria dado
-- oficial correto — a verificação de plausibilidade fica em `qualidade.sql`,
-- onde pode distinguir o negativo legítimo do zero, que seria falha de carga.
-- =========================================================================

CREATE TABLE IF NOT EXISTS ibge.fato_pib_municipio (
    municipio_id              char(7)       NOT NULL REFERENCES ibge.dim_municipio (municipio_id) ON DELETE CASCADE,
    ano                       smallint      NOT NULL,
    pib_mil_reais             numeric(18,3),
    vab_agropecuaria          numeric(18,3),
    vab_industria             numeric(18,3),
    vab_servicos              numeric(18,3),
    vab_administracao_publica numeric(18,3),
    impostos_liquidos         numeric(18,3),

    PRIMARY KEY (municipio_id, ano),
    CONSTRAINT fato_pib_mun_ano_plausivel CHECK (ano BETWEEN 1990 AND 2100)
);

COMMENT ON COLUMN ibge.fato_pib_municipio.pib_mil_reais IS 'PIB a preços correntes, em mil reais (unidade original do SIDRA)';

CREATE TABLE IF NOT EXISTS ibge.fato_pib_uf (
    uf_id                     smallint      NOT NULL REFERENCES ibge.dim_uf (uf_id) ON DELETE CASCADE,
    ano                       smallint      NOT NULL,
    pib_mil_reais             numeric(18,3),
    vab_agropecuaria          numeric(18,3),
    vab_industria             numeric(18,3),
    vab_servicos              numeric(18,3),
    vab_administracao_publica numeric(18,3),
    impostos_liquidos         numeric(18,3),

    PRIMARY KEY (uf_id, ano)
);

CREATE TABLE IF NOT EXISTS ibge.fato_pib_regiao (
    regiao_id                 smallint      NOT NULL REFERENCES ibge.dim_regiao (regiao_id) ON DELETE CASCADE,
    ano                       smallint      NOT NULL,
    pib_mil_reais             numeric(18,3),
    vab_agropecuaria          numeric(18,3),
    vab_industria             numeric(18,3),
    vab_servicos              numeric(18,3),
    vab_administracao_publica numeric(18,3),
    impostos_liquidos         numeric(18,3),

    PRIMARY KEY (regiao_id, ano)
);

CREATE TABLE IF NOT EXISTS ibge.fato_pib_brasil (
    ano                       smallint PRIMARY KEY,
    pib_mil_reais             numeric(18,3),
    vab_agropecuaria          numeric(18,3),
    vab_industria             numeric(18,3),
    vab_servicos              numeric(18,3),
    vab_administracao_publica numeric(18,3),
    impostos_liquidos         numeric(18,3)
);


-- =========================================================================
-- Linhagem: o que foi carregado, de onde, quando e em quanto tempo.
--
-- Sobrevive às recargas (nunca é truncada). É o que permite responder "esse
-- número saiu de qual extração?" sem depender do que estiver no disco hoje.
-- =========================================================================

CREATE TABLE IF NOT EXISTS ibge.carga_log (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tabela        text        NOT NULL,
    origem        text        NOT NULL,
    linhas        integer     NOT NULL,
    bytes_origem  bigint,
    iniciado_em   timestamptz NOT NULL,
    duracao_ms    integer     NOT NULL,
    executado_por text        NOT NULL DEFAULT current_user
);

COMMENT ON TABLE  ibge.carga_log        IS 'Uma linha por tabela carregada, por execução de `ibge-db load`';
COMMENT ON COLUMN ibge.carga_log.origem IS 'Caminho do Parquet de origem, relativo à raiz do projeto';
