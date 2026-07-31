"""Carga dos Parquet de `data/raw/` para o PostgreSQL.

Carrega o **cru**, não o processado. As tabelas de `data/processed/` são
denormalizadas — repetem nome de município, UF e região em cada linha de fato —
e reproduzi-las no banco significaria gravar a mesma string 116 mil vezes e
manter duas verdades sobre o que é "densidade". No banco, os fatos ficam na
granularidade em que o SIDRA publica e o resto é view.

A carga é uma substituição completa dentro de uma transação: TRUNCATE de todas
as tabelas de dados, COPY de cada uma, commit. Ou o banco fica com o snapshot
inteiro, ou fica como estava. Não há estado intermediário visível.
"""

from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import Engine

from ..config import RAW_DIR
from .engine import criar_engine

log = logging.getLogger(__name__)


class ParquetAusenteError(FileNotFoundError):
    """O pipeline de extração ainda não rodou."""


#: Colunas que o banco declara como inteiras. O Parquet as traz como float64
#: (é assim que o pandas representa inteiro com nulo), e "12345.0" não é um
#: bigint válido para o COPY.
COLUNAS_INTEIRAS = frozenset(
    {
        "ano",
        "populacao",
        "populacao_censo",
        "uf_id",
        "regiao_id",
        "microrregiao_id",
        "mesorregiao_id",
    }
)

COLUNAS_PIB = (
    "ano",
    "pib_mil_reais",
    "vab_agropecuaria",
    "vab_industria",
    "vab_servicos",
    "vab_administracao_publica",
    "impostos_liquidos",
)

COLUNAS_CENSO = ("ano", "populacao_censo", "area_km2", "densidade_hab_km2")


@dataclass(frozen=True)
class Fonte:
    """De qual Parquet sai qual tabela, e com quais colunas."""

    tabela: str
    parquet: str
    colunas: tuple[str, ...]
    #: Nível territorial da chave. Define como `localidade_id` — que o SIDRA
    #: entrega como string genérica — vira `municipio_id`, `uf_id` ou
    #: `regiao_id` com o tipo certo. None para tabelas sem recorte territorial.
    nivel: str | None = field(default=None)


#: Ordem de carga: dimensões antes dos fatos, porque as chaves estrangeiras
#: são verificadas linha a linha durante o COPY.
FONTES: tuple[Fonte, ...] = (
    Fonte("ibge.dim_regiao", "dim_regioes", ("regiao_id", "regiao_sigla", "regiao_nome")),
    Fonte("ibge.dim_uf", "dim_estados", ("uf_id", "uf_sigla", "uf_nome", "regiao_id")),
    Fonte(
        "ibge.dim_municipio",
        "dim_municipios",
        (
            "municipio_id",
            "municipio_nome",
            "microrregiao_id",
            "microrregiao_nome",
            "mesorregiao_id",
            "mesorregiao_nome",
            "uf_id",
        ),
        nivel="municipio",
    ),
    Fonte("ibge.fato_populacao_municipio", "pop_municipios", ("municipio_id", "ano", "populacao"), "municipio"),
    Fonte("ibge.fato_populacao_uf", "pop_ufs", ("uf_id", "ano", "populacao"), "uf"),
    Fonte("ibge.fato_populacao_regiao", "pop_regioes", ("regiao_id", "ano", "populacao"), "regiao"),
    Fonte("ibge.fato_populacao_brasil", "pop_brasil", ("ano", "populacao")),
    Fonte("ibge.fato_censo_municipio", "censo_municipios", ("municipio_id", *COLUNAS_CENSO), "municipio"),
    Fonte("ibge.fato_censo_uf", "censo_ufs", ("uf_id", *COLUNAS_CENSO), "uf"),
    Fonte("ibge.fato_censo_regiao", "censo_regioes", ("regiao_id", *COLUNAS_CENSO), "regiao"),
    Fonte("ibge.fato_pib_municipio", "pib_municipios", ("municipio_id", *COLUNAS_PIB), "municipio"),
    Fonte("ibge.fato_pib_uf", "pib_ufs", ("uf_id", *COLUNAS_PIB), "uf"),
    Fonte("ibge.fato_pib_regiao", "pib_regioes", ("regiao_id", *COLUNAS_PIB), "regiao"),
    Fonte("ibge.fato_pib_brasil", "pib_brasil", COLUNAS_PIB),
)


def preparar(df: pd.DataFrame, fonte: Fonte) -> pd.DataFrame:
    """Ajusta chaves e tipos de um DataFrame cru para o formato da tabela."""
    df = df.copy()

    if fonte.nivel:
        destino = f"{fonte.nivel}_id"
        origem = "localidade_id" if "localidade_id" in df.columns else destino
        bruto = df[origem].astype(str).str.strip()
        # Código de município é char(7): zfill preserva o zero à esquerda que
        # o Parquet perdeu ao guardar a coluna como int64.
        df[destino] = bruto.str.zfill(7) if fonte.nivel == "municipio" else bruto.astype(int)

    if faltando := set(fonte.colunas) - set(df.columns):
        raise KeyError(f"{fonte.parquet}.parquet não tem as colunas {sorted(faltando)}")

    df = df[list(fonte.colunas)]
    for coluna in df.columns.intersection(COLUNAS_INTEIRAS):
        # `to_numeric` antes do round: uma coluna toda nula chega do Parquet
        # como dtype object, e `None.round()` levanta TypeError.
        # Int64 (nullable) e não int64: preserva o nulo em vez de virar 0.
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce").round().astype("Int64")
    return df


def _para_csv(df: pd.DataFrame) -> str:
    """Serializa para o formato que o COPY espera.

    Nulo vira campo vazio. Nenhuma coluna de texto do IBGE tem string vazia
    legítima, então a ambiguidade entre "vazio" e "nulo" não se materializa —
    mas ela existe, e é por isso que a escolha está anotada aqui.
    """
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="")
    return buffer.getvalue()


def _copiar(cursor, fonte: Fonte, df: pd.DataFrame) -> None:
    colunas = ", ".join(df.columns)
    comando = f"COPY {fonte.tabela} ({colunas}) FROM STDIN WITH (FORMAT csv, NULL '')"
    with cursor.copy(comando) as copy:
        copy.write(_para_csv(df))


def _ler(fonte: Fonte) -> pd.DataFrame:
    caminho = RAW_DIR / f"{fonte.parquet}.parquet"
    if not caminho.exists():
        raise ParquetAusenteError(
            f"{caminho} não encontrado. Rode primeiro:\n"
            f"    python -m ibge_analytics.etl.pipeline"
        )
    return pd.read_parquet(caminho)


def carregar(
    engine: Engine | None = None,
    fontes: tuple[Fonte, ...] = FONTES,
    *,
    truncar: bool = True,
) -> pd.DataFrame:
    """Carrega todas as fontes numa transação. Devolve o resumo por tabela.

    Com `truncar=False` o COPY vai por cima do que já existe e as chaves
    primárias rejeitam as repetições — útil apenas para carga incremental de um
    subconjunto novo, nunca para recarregar o mesmo snapshot.
    """
    engine = engine or criar_engine()

    # Lê tudo antes de abrir a transação: um Parquet faltando deve falhar
    # com o banco intacto, e não no meio de um TRUNCATE já executado.
    dados = {fonte.tabela: preparar(_ler(fonte), fonte) for fonte in fontes}

    conexao = engine.raw_connection()
    resumo = []
    try:
        pg = conexao.driver_connection
        with pg.cursor() as cursor:
            if truncar:
                # Todas num só comando: as tabelas se referenciam mutuamente e
                # o PostgreSQL só permite truncar um grupo assim de uma vez.
                alvos = ", ".join(f.tabela for f in fontes)
                log.info("TRUNCATE em %d tabelas", len(fontes))
                cursor.execute(f"TRUNCATE {alvos} RESTART IDENTITY")

            for fonte in fontes:
                df = dados[fonte.tabela]
                caminho = RAW_DIR / f"{fonte.parquet}.parquet"
                inicio_ts = datetime.now(timezone.utc)
                inicio = time.perf_counter()

                _copiar(cursor, fonte, df)

                duracao_ms = int((time.perf_counter() - inicio) * 1000)
                cursor.execute(
                    """
                    INSERT INTO ibge.carga_log
                        (tabela, origem, linhas, bytes_origem, iniciado_em, duracao_ms)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        fonte.tabela,
                        f"data/raw/{fonte.parquet}.parquet",
                        len(df),
                        caminho.stat().st_size,
                        inicio_ts,
                        duracao_ms,
                    ),
                )
                log.info("%-34s %7d linhas  %5d ms", fonte.tabela, len(df), duracao_ms)
                resumo.append({"tabela": fonte.tabela, "linhas": len(df), "ms": duracao_ms})

        conexao.commit()
    except Exception:
        conexao.rollback()
        log.error("carga revertida — o banco continua no estado anterior")
        raise
    finally:
        conexao.close()

    total = sum(linha["linhas"] for linha in resumo)
    log.info("carga concluída: %d linhas em %d tabelas", total, len(resumo))
    return pd.DataFrame(resumo)
