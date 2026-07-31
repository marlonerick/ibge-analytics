"""Análise de população: rankings, concentração e distribuição por porte."""

from __future__ import annotations

import pandas as pd

from ..etl.transform import concentracao

#: Faixas de porte municipal usadas pelo IBGE e pelo IBAM em estudos urbanos.
FAIXAS_PORTE = [0, 5_000, 10_000, 20_000, 50_000, 100_000, 500_000, float("inf")]
ROTULOS_PORTE = [
    "Até 5 mil",
    "5 a 10 mil",
    "10 a 20 mil",
    "20 a 50 mil",
    "50 a 100 mil",
    "100 a 500 mil",
    "Mais de 500 mil",
]


def ranking_municipios(
    painel: pd.DataFrame, n: int = 20, coluna: str = "populacao_atual", ascendente: bool = False
) -> pd.DataFrame:
    """Os N municípios no topo (ou na base) de um indicador."""
    cols = ["municipio_nome", "uf_sigla", "regiao_nome", coluna]
    return (
        painel.dropna(subset=[coluna])
        .sort_values(coluna, ascending=ascendente)
        .head(n)[cols]
        .reset_index(drop=True)
    )


def classificar_porte(painel: pd.DataFrame, coluna: str = "populacao_atual") -> pd.DataFrame:
    """Adiciona a faixa de porte populacional a cada município."""
    df = painel.copy()
    df["porte"] = pd.cut(df[coluna], bins=FAIXAS_PORTE, labels=ROTULOS_PORTE, right=False)
    return df


def distribuicao_por_porte(painel: pd.DataFrame) -> pd.DataFrame:
    """Quantos municípios e quanta gente há em cada faixa de porte.

    É o recorte que mostra o contraste central da rede urbana brasileira: a
    maioria dos municípios é pequena, mas a maioria da população não vive neles.
    """
    df = classificar_porte(painel)
    resumo = df.groupby("porte", observed=True).agg(
        n_municipios=("municipio_id", "count"),
        populacao=("populacao_atual", "sum"),
    )
    resumo["pct_municipios"] = resumo["n_municipios"] / resumo["n_municipios"].sum() * 100
    resumo["pct_populacao"] = resumo["populacao"] / resumo["populacao"].sum() * 100
    return resumo.reset_index()


def metricas_concentracao(painel: pd.DataFrame) -> dict[str, float]:
    """Gini e participação dos maiores na população nacional."""
    return concentracao(painel, "populacao_atual")


def curva_lorenz(painel: pd.DataFrame, coluna: str = "populacao_atual") -> pd.DataFrame:
    """Pontos da curva de Lorenz — base do gráfico de concentração."""
    serie = painel[coluna].dropna().sort_values()
    acumulado = serie.cumsum() / serie.sum()
    return pd.DataFrame(
        {
            "pct_municipios": [i / len(serie) * 100 for i in range(1, len(serie) + 1)],
            "pct_populacao": acumulado.values * 100,
        }
    )


def serie_nacional(populacao_ufs: pd.DataFrame) -> pd.DataFrame:
    """População do Brasil ano a ano, somando as UFs."""
    return (
        populacao_ufs.groupby("ano", as_index=False)["populacao"]
        .sum()
        .assign(variacao_pct=lambda d: d["populacao"].pct_change() * 100)
    )
