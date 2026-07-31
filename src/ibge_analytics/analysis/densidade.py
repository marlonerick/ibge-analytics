"""Análise de densidade demográfica e ocupação do território."""

from __future__ import annotations

import pandas as pd

#: Cortes de densidade em hab/km². As faixas separam o vazio demográfico
#: amazônico (<1) da ocupação rural, urbana e metropolitana.
FAIXAS_DENSIDADE = [0, 1, 5, 25, 100, 500, float("inf")]
ROTULOS_DENSIDADE = [
    "Muito baixa (<1)",
    "Baixa (1–5)",
    "Média-baixa (5–25)",
    "Média (25–100)",
    "Alta (100–500)",
    "Muito alta (>500)",
]


def classificar(painel: pd.DataFrame, coluna: str = "densidade_atual") -> pd.DataFrame:
    df = painel.copy()
    df["faixa_densidade"] = pd.cut(
        df[coluna], bins=FAIXAS_DENSIDADE, labels=ROTULOS_DENSIDADE, right=False
    )
    return df


def distribuicao(painel: pd.DataFrame) -> pd.DataFrame:
    """Quanto do território e da população cabe em cada faixa de densidade.

    O contraste entre as duas colunas é o retrato da ocupação desigual do país.
    """
    df = classificar(painel)
    resumo = df.groupby("faixa_densidade", observed=True).agg(
        n_municipios=("municipio_id", "count"),
        area_km2=("area_km2", "sum"),
        populacao=("populacao_atual", "sum"),
    )
    resumo["pct_area"] = resumo["area_km2"] / resumo["area_km2"].sum() * 100
    resumo["pct_populacao"] = resumo["populacao"] / resumo["populacao"].sum() * 100
    return resumo.reset_index()


def extremos(painel: pd.DataFrame, n: int = 15) -> dict[str, pd.DataFrame]:
    """Os municípios mais densos e mais vazios."""
    cols = ["municipio_nome", "uf_sigla", "regiao_nome", "populacao_atual", "area_km2",
            "densidade_atual"]
    validos = painel.dropna(subset=["densidade_atual"])
    return {
        "mais_densos": validos.nlargest(n, "densidade_atual")[cols].reset_index(drop=True),
        "mais_vazios": validos.nsmallest(n, "densidade_atual")[cols].reset_index(drop=True),
        "maiores_areas": validos.nlargest(n, "area_km2")[cols].reset_index(drop=True),
    }


def densidade_por_regiao(painel_regiao: pd.DataFrame) -> pd.DataFrame:
    """Densidade regional com as parcelas de área e população.

    Densidade regional é população/área da região — não a média das densidades
    municipais, que daria peso igual a um município de 3 km² e a um de 159 mil.
    """
    return painel_regiao[
        ["regiao_nome", "populacao_atual", "area_km2", "densidade_atual",
         "part_pop_brasil", "part_area_brasil"]
    ].copy()


def concentracao_territorial(painel: pd.DataFrame) -> dict[str, float]:
    """Quanto do território é preciso para reunir metade da população."""
    df = painel.dropna(subset=["densidade_atual", "area_km2", "populacao_atual"])
    ordenado = df.sort_values("densidade_atual", ascending=False)
    pop_acum = ordenado["populacao_atual"].cumsum() / ordenado["populacao_atual"].sum()
    corte = (pop_acum < 0.5).sum() + 1
    area_metade = ordenado.head(corte)["area_km2"].sum()
    return {
        "n_municipios_metade_pop": int(corte),
        "area_metade_pop_km2": float(area_metade),
        "pct_area_metade_pop": float(area_metade / df["area_km2"].sum() * 100),
        "area_total_km2": float(df["area_km2"].sum()),
    }
