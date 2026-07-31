"""API de Localidades v1 — malha administrativa (regiões, UFs, municípios).

Esta API é a fonte de nomes, siglas e da hierarquia município → UF → região.
Os agregados do SIDRA devolvem apenas códigos + um nome concatenado
("São Paulo (SP)"), então cruzamos tudo por aqui.
"""

from __future__ import annotations

import pandas as pd

from ..config import LOCALIDADES_URL
from .client import IBGEClient, get_client


def estados(client: IBGEClient | None = None) -> pd.DataFrame:
    """As 27 UFs com sua região. Colunas: uf_id, uf_sigla, uf_nome, regiao_*."""
    client = client or get_client()
    dados = client.get_json(f"{LOCALIDADES_URL}/estados", params={"orderBy": "nome"})
    return pd.DataFrame(
        [
            {
                "uf_id": uf["id"],
                "uf_sigla": uf["sigla"],
                "uf_nome": uf["nome"],
                "regiao_id": uf["regiao"]["id"],
                "regiao_sigla": uf["regiao"]["sigla"],
                "regiao_nome": uf["regiao"]["nome"],
            }
            for uf in dados
        ]
    )


def municipios(client: IBGEClient | None = None) -> pd.DataFrame:
    """Os 5.570 municípios com a hierarquia territorial completa.

    A v1 aninha município → microrregião → mesorregião → UF → região. Achatamos
    o que interessa para as análises.
    """
    client = client or get_client()
    dados = client.get_json(f"{LOCALIDADES_URL}/municipios", params={"orderBy": "nome"})

    linhas = []
    for m in dados:
        # Municípios criados após a última revisão de microrregiões podem vir
        # com 'microrregiao' nulo — nesse caso a UF vem por 'regiao-imediata'.
        micro = m.get("microrregiao")
        if micro:
            meso = micro["mesorregiao"]
            uf = meso["UF"]
            micro_id, micro_nome = micro["id"], micro["nome"]
            meso_id, meso_nome = meso["id"], meso["nome"]
        else:
            imediata = m.get("regiao-imediata", {})
            uf = imediata.get("regiao-intermediaria", {}).get("UF", {})
            micro_id = micro_nome = meso_id = meso_nome = None

        if not uf:
            continue

        linhas.append(
            {
                "municipio_id": m["id"],
                "municipio_nome": m["nome"],
                "microrregiao_id": micro_id,
                "microrregiao_nome": micro_nome,
                "mesorregiao_id": meso_id,
                "mesorregiao_nome": meso_nome,
                "uf_id": uf["id"],
                "uf_sigla": uf["sigla"],
                "uf_nome": uf["nome"],
                "regiao_id": uf["regiao"]["id"],
                "regiao_sigla": uf["regiao"]["sigla"],
                "regiao_nome": uf["regiao"]["nome"],
            }
        )
    return pd.DataFrame(linhas)


def regioes(client: IBGEClient | None = None) -> pd.DataFrame:
    """As 5 grandes regiões."""
    client = client or get_client()
    dados = client.get_json(f"{LOCALIDADES_URL}/regioes")
    return pd.DataFrame(
        [{"regiao_id": r["id"], "regiao_sigla": r["sigla"], "regiao_nome": r["nome"]} for r in dados]
    )
