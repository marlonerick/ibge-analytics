"""Consultas analíticas nomeadas.

Cada consulta é um arquivo em `sql/analytics/`. Aqui só ficam o registro (nome,
descrição, parâmetros padrão) e a execução — o SQL em si nunca é montado por
concatenação de string, para que ele possa ser lido, colado no psql e revisado
sem passar pelo Python.

    from ibge_analytics.db import queries
    queries.executar("concentracao")
    queries.executar("top_municipios", metrica="pib", limite=10)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import Engine, text

from .engine import SQL_ANALYTICS_DIR, criar_engine

log = logging.getLogger(__name__)


class ConsultaDesconhecidaError(KeyError):
    """Nome não está no registro."""


@dataclass(frozen=True)
class Consulta:
    nome: str
    descricao: str
    parametros: dict[str, Any] = field(default_factory=dict)

    @property
    def caminho(self):
        return SQL_ANALYTICS_DIR / f"{self.nome}.sql"

    def sql(self) -> str:
        return self.caminho.read_text(encoding="utf-8")


CONSULTAS: dict[str, Consulta] = {
    c.nome: c
    for c in (
        Consulta(
            "top_municipios",
            "Os maiores municípios em um indicador, com share e share acumulado",
            {"metrica": "populacao", "limite": 20},
        ),
        Consulta(
            "concentracao",
            "Quantos municípios concentram 10/25/50/75/90% da população e do PIB",
        ),
        Consulta(
            "declinio_populacional",
            "Municípios em esvaziamento por UF: contagem, share e saldo líquido",
        ),
        Consulta(
            "porte_populacional",
            "A rede urbana por faixa de porte: municípios × população × PIB × área",
        ),
        Consulta(
            "quociente_locacional",
            "Especialização produtiva das UFs (QL setorial contra a média nacional)",
        ),
        Consulta(
            "regioes",
            "Comparação entre as cinco grandes regiões",
        ),
        Consulta(
            "serie_uf",
            "Série histórica de uma UF (população, PIB, per capita). :uf=None → Brasil",
            {"uf": None},
        ),
        Consulta(
            "descolamento_pib_populacao",
            "Municípios onde PIB e população andam em direções opostas",
            {"limite": 30},
        ),
        Consulta(
            "densidade_extremos",
            "Os municípios mais densos e os mais vazios, lado a lado",
            {"limite": 15},
        ),
        Consulta(
            "perfil_municipio",
            "Ficha completa de um município (por código IBGE ou nome)",
            {"municipio": "3550308"},
        ),
        Consulta(
            "qualidade",
            "Verificações de integridade da carga",
        ),
    )
}


def listar() -> pd.DataFrame:
    """Inventário das consultas disponíveis."""
    return pd.DataFrame(
        {
            "consulta": c.nome,
            "descrição": c.descricao,
            "parâmetros": ", ".join(f"{k}={v!r}" for k, v in c.parametros.items()) or "—",
        }
        for c in CONSULTAS.values()
    )


def obter(nome: str) -> Consulta:
    try:
        return CONSULTAS[nome]
    except KeyError as erro:
        disponiveis = ", ".join(sorted(CONSULTAS))
        raise ConsultaDesconhecidaError(
            f"consulta {nome!r} não existe. Disponíveis: {disponiveis}"
        ) from erro


def executar(nome: str, engine: Engine | None = None, **parametros: Any) -> pd.DataFrame:
    """Roda uma consulta nomeada e devolve o resultado.

    Os parâmetros informados sobrepõem os padrões do registro; os não
    informados vêm de lá. Tudo entra como bind parameter — nada é interpolado
    no SQL.
    """
    consulta = obter(nome)
    if desconhecidos := set(parametros) - set(consulta.parametros):
        raise TypeError(
            f"{nome} não aceita {sorted(desconhecidos)}; "
            f"aceita {sorted(consulta.parametros) or 'nenhum parâmetro'}"
        )

    finais = {**consulta.parametros, **parametros}
    log.debug("executando %s com %s", nome, finais)
    engine = engine or criar_engine()
    with engine.connect() as conn:
        return pd.read_sql_query(text(consulta.sql()), conn, params=finais)


def sql_bruto(nome: str) -> str:
    """O SQL da consulta, para inspeção ou para colar no psql."""
    return obter(nome).sql()


def plano(nome: str, engine: Engine | None = None, **parametros: Any) -> str:
    """EXPLAIN ANALYZE da consulta — para conferir se os índices são usados."""
    consulta = obter(nome)
    finais = {**consulta.parametros, **parametros}
    engine = engine or criar_engine()
    with engine.connect() as conn:
        linhas = conn.execute(
            text(f"EXPLAIN (ANALYZE, BUFFERS) {consulta.sql().rstrip().rstrip(';')}"), finais
        ).scalars()
        return "\n".join(linhas)
