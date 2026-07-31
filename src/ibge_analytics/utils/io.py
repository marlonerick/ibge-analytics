"""Carregamento das tabelas processadas e das malhas.

Camada única de leitura, compartilhada pelo dashboard, pelos notebooks e pelo
gerador de relatório — para que os três leiam exatamente os mesmos dados.
"""

from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from ..config import GEO_DIR, PROCESSED_DIR

TABELAS = {
    "painel_municipios": "Retrato municipal mais recente (população, área, PIB, crescimento)",
    "painel_ufs": "Retrato por UF",
    "painel_regioes": "Retrato por grande região",
    "populacao_municipios": "Série histórica de população municipal",
    "populacao_ufs": "Série histórica de população por UF",
    "crescimento_municipios": "Crescimento populacional municipal (CAGR)",
    "crescimento_ufs": "Crescimento populacional por UF",
    "densidade_municipios": "Censo 2022: população, área e densidade",
    "densidade_ufs": "Censo 2022 por UF",
    "pib_municipios": "Série histórica de PIB municipal",
    "pib_ufs": "Série histórica de PIB por UF",
}


class DadosAusentesError(FileNotFoundError):
    """As tabelas processadas não existem — o pipeline ainda não rodou."""


@lru_cache(maxsize=None)
def carregar(nome: str) -> pd.DataFrame:
    caminho = PROCESSED_DIR / f"{nome}.parquet"
    if not caminho.exists():
        raise DadosAusentesError(
            f"{caminho} não encontrado. Rode primeiro:\n"
            f"    python -m ibge_analytics.etl.pipeline"
        )
    return pd.read_parquet(caminho)


@lru_cache(maxsize=None)
def carregar_malha(nome: str) -> dict:
    """Carrega uma malha do IBGE já reorientada para o RFC 7946.

    A reorientação acontece aqui, na única porta de entrada das malhas, para que
    dashboard, notebooks e relatório recebam a geometria correta sem precisar
    lembrar de tratá-la (ver `viz.maps.reorientar_malha`).
    """
    from ..viz.maps import reorientar_malha

    caminho = GEO_DIR / f"{nome}.geojson"
    if not caminho.exists():
        raise DadosAusentesError(
            f"{caminho} não encontrado. Rode o pipeline sem a flag --sem-malhas."
        )
    return reorientar_malha(json.loads(caminho.read_text(encoding="utf-8")))


def dados_disponiveis() -> bool:
    return (PROCESSED_DIR / "painel_municipios.parquet").exists()


def resumo_datasets() -> pd.DataFrame:
    """Inventário do que o pipeline produziu — usado na página inicial."""
    linhas = []
    for nome, descricao in TABELAS.items():
        caminho = PROCESSED_DIR / f"{nome}.parquet"
        if caminho.exists():
            df = carregar(nome)
            linhas.append(
                {
                    "tabela": nome,
                    "descrição": descricao,
                    "linhas": len(df),
                    "colunas": df.shape[1],
                    "tamanho_kb": round(caminho.stat().st_size / 1024, 1),
                }
            )
    return pd.DataFrame(linhas)
