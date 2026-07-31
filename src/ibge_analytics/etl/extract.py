"""Extração: baixa os dados crus das APIs e grava em data/raw/.

Cada função devolve o DataFrame e persiste em Parquet. O cache do cliente HTTP
já evita rebaixar; o Parquet aqui existe para que as etapas seguintes e os
notebooks não dependam de rede.
"""

from __future__ import annotations

import logging

import pandas as pd

from ..api import agregados, localidades, malhas
from ..config import (
    CENSO_2022,
    PIB,
    POPULACAO_ESTIMADA,
    RAW_DIR,
    Nivel,
)

log = logging.getLogger(__name__)


def _salvar(df: pd.DataFrame, nome: str) -> pd.DataFrame:
    destino = RAW_DIR / f"{nome}.parquet"
    df.to_parquet(destino, index=False)
    log.info("raw/%s.parquet: %d linhas", nome, len(df))
    return df


# ------------------------------------------------------------------ dimensões #

def extrair_dimensoes() -> dict[str, pd.DataFrame]:
    return {
        "municipios": _salvar(localidades.municipios(), "dim_municipios"),
        "estados": _salvar(localidades.estados(), "dim_estados"),
        "regioes": _salvar(localidades.regioes(), "dim_regioes"),
    }


# ---------------------------------------------------------------------- fatos #

def extrair_populacao(anos: list[int] | None = None) -> dict[str, pd.DataFrame]:
    """População estimada por município, UF, região e Brasil."""
    anos = anos or POPULACAO_ESTIMADA.anos
    return {
        "municipios": _salvar(
            agregados.serie_de(POPULACAO_ESTIMADA, Nivel.MUNICIPIO, anos), "pop_municipios"
        ),
        "ufs": _salvar(agregados.serie_de(POPULACAO_ESTIMADA, Nivel.UF, anos), "pop_ufs"),
        "regioes": _salvar(agregados.serie_de(POPULACAO_ESTIMADA, Nivel.REGIAO, anos), "pop_regioes"),
        "brasil": _salvar(agregados.serie_de(POPULACAO_ESTIMADA, Nivel.BRASIL, anos), "pop_brasil"),
    }


def extrair_censo() -> dict[str, pd.DataFrame]:
    """Censo 2022: população, área e densidade — a base da análise territorial."""
    return {
        "municipios": _salvar(
            agregados.serie_de(CENSO_2022, Nivel.MUNICIPIO), "censo_municipios"
        ),
        "ufs": _salvar(agregados.serie_de(CENSO_2022, Nivel.UF), "censo_ufs"),
        "regioes": _salvar(agregados.serie_de(CENSO_2022, Nivel.REGIAO), "censo_regioes"),
    }


def extrair_pib(anos: list[int] | None = None) -> dict[str, pd.DataFrame]:
    """PIB e valor adicionado por setor.

    A série municipal é pesada (6 variáveis × 5.570 municípios). Por padrão
    baixamos a janela recente no nível municipal e a série completa nos níveis
    agregados, que são baratos.
    """
    anos_uf = anos or PIB.anos
    anos_mun = anos or [a for a in PIB.anos if a >= 2010]
    return {
        "municipios": _salvar(
            agregados.serie_de(PIB, Nivel.MUNICIPIO, anos_mun), "pib_municipios"
        ),
        "ufs": _salvar(agregados.serie_de(PIB, Nivel.UF, anos_uf), "pib_ufs"),
        "regioes": _salvar(agregados.serie_de(PIB, Nivel.REGIAO, anos_uf), "pib_regioes"),
        "brasil": _salvar(agregados.serie_de(PIB, Nivel.BRASIL, anos_uf), "pib_brasil"),
    }


# --------------------------------------------------------------------- malhas #

def extrair_malhas(ufs: list[int], incluir_municipios: bool = True) -> None:
    """Baixa e persiste as geometrias usadas pelos mapas."""
    malhas.salvar(malhas.malha_ufs(), "ufs")
    malhas.salvar(malhas.malha_regioes(), "regioes")
    if incluir_municipios:
        malhas.salvar(malhas.malha_municipios_brasil(ufs), "municipios")
