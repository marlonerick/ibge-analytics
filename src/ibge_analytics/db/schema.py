"""Aplicação do DDL: schemas, tabelas, índices e views.

Cada arquivo de `sql/` é executado inteiro, como o psql executaria. Não há
migrações versionadas: o schema é reconstruível a partir do Parquet em
segundos, então recriar é mais simples — e mais honesto — do que manter um
histórico de ALTERs de um banco que ninguém opera em produção.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

from .engine import criar_engine, ler_sql

log = logging.getLogger(__name__)

#: Ordem de aplicação. Índices depois das tabelas, views depois dos índices —
#: as views não dependem dos índices, mas o planejador só os aproveita se já
#: existirem quando a materialized view é populada.
ARQUIVOS_DDL = ("01_schema.sql", "02_indexes.sql", "03_views.sql")

#: Tudo que o projeto cria. `derrubar()` não toca em nada fora daqui.
SCHEMAS = ("analytics", "ibge")

MATERIALIZED_VIEWS = (
    "analytics.mv_painel_municipio",
    "analytics.mv_concentracao_municipio",
)


def aplicar(engine: Engine | None = None, arquivos: tuple[str, ...] = ARQUIVOS_DDL) -> None:
    """Executa os arquivos de DDL na ordem."""
    engine = engine or criar_engine()
    for arquivo in arquivos:
        log.info("aplicando %s", arquivo)
        # Uma transação por arquivo: se 03_views.sql falhar no meio, o banco
        # não fica com metade das views recriadas.
        with engine.begin() as conn:
            conn.execute(text(ler_sql(arquivo)))
    log.info("DDL aplicado: %s", ", ".join(arquivos))


def derrubar(engine: Engine | None = None) -> None:
    """Remove os schemas do projeto. Destrutivo — só via `--recriar`."""
    engine = engine or criar_engine()
    with engine.begin() as conn:
        for schema in SCHEMAS:
            log.warning("DROP SCHEMA %s CASCADE", schema)
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def atualizar_materializadas(engine: Engine | None = None, concorrente: bool = True) -> None:
    """Recalcula as materialized views.

    CONCURRENTLY mantém a view legível durante o refresh, mas exige que ela já
    tenha sido populada ao menos uma vez — numa view recém-criada o comando
    falha. Nesse caso, cai para o refresh bloqueante, que é o correto na
    primeira vez.

    A ordem importa: mv_concentracao lê mv_painel.
    """
    engine = engine or criar_engine()
    for view in MATERIALIZED_VIEWS:
        with engine.begin() as conn:
            populada = conn.execute(
                text("SELECT ispopulated FROM pg_matviews WHERE schemaname || '.' || matviewname = :v"),
                {"v": view},
            ).scalar()
            modo = "CONCURRENTLY " if concorrente and populada else ""
            log.info("REFRESH %s%s", modo, view)
            conn.execute(text(f"REFRESH MATERIALIZED VIEW {modo}{view}"))
            # REFRESH não atualiza as estatísticas, e o autovacuum não coleta
            # materialized views. Sem este ANALYZE, `pg_stats` fica sem linhas
            # para a view — e a verificação de "coluna 100% nula" em
            # qualidade.sql passaria contando zero de nada, um OK falso.
            conn.execute(text(f"ANALYZE {view}"))


def inventario(engine: Engine | None = None) -> list[dict]:
    """Tabelas e views existentes, com a contagem de linhas.

    `count(*)` de verdade, e não a estimativa de `pg_class.reltuples`: são
    poucas tabelas e a contagem exata é o que se quer conferir depois da carga.
    """
    engine = engine or criar_engine()
    with engine.connect() as conn:
        objetos = conn.execute(
            text(
                """
                SELECT schemaname AS schema, tablename AS objeto, 'tabela' AS tipo
                  FROM pg_tables  WHERE schemaname = ANY(:s)
                UNION ALL
                SELECT schemaname, viewname, 'view'
                  FROM pg_views   WHERE schemaname = ANY(:s)
                UNION ALL
                SELECT schemaname, matviewname, 'materializada'
                  FROM pg_matviews WHERE schemaname = ANY(:s)
                ORDER BY 1, 3, 2
                """
            ),
            {"s": list(SCHEMAS)},
        ).mappings().all()

        linhas = []
        for obj in objetos:
            qualificado = f'{obj["schema"]}.{obj["objeto"]}'
            n = conn.execute(text(f"SELECT count(*) FROM {qualificado}")).scalar_one()
            tamanho = conn.execute(
                text("SELECT pg_size_pretty(pg_total_relation_size(:q))"), {"q": qualificado}
            ).scalar_one()
            linhas.append(
                {"objeto": qualificado, "tipo": obj["tipo"], "linhas": n, "tamanho": tamanho}
            )
        return linhas


def indices(engine: Engine | None = None) -> list[dict]:
    """Índices criados e quanto cada um já foi usado."""
    engine = engine or criar_engine()
    with engine.connect() as conn:
        return [
            dict(linha)
            for linha in conn.execute(
                text(
                    """
                    SELECT s.relname       AS tabela,
                           s.indexrelname  AS indice,
                           s.idx_scan      AS varreduras,
                           pg_size_pretty(pg_relation_size(s.indexrelid)) AS tamanho
                    FROM pg_stat_user_indexes s
                    WHERE s.schemaname = ANY(:s)
                    ORDER BY s.relname, s.indexrelname
                    """
                ),
                {"s": list(SCHEMAS)},
            ).mappings()
        ]
