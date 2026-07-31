"""Análise de crescimento populacional: ritmo, ganhadores e perdedores."""

from __future__ import annotations

import pandas as pd


def municipios_em_declinio(crescimento: pd.DataFrame) -> pd.DataFrame:
    """Municípios que perderam população no período completo da série."""
    return crescimento[crescimento["variacao_absoluta"] < 0].sort_values("cagr_pct")


def resumo_declinio(crescimento: pd.DataFrame) -> dict[str, float]:
    """Quantifica o encolhimento populacional — um dos achados centrais.

    Boa parte dos municípios brasileiros perde população mesmo com o país ainda
    crescendo: o crescimento nacional se concentra em poucos polos.
    """
    total = len(crescimento)
    perdendo = crescimento[crescimento["variacao_absoluta"] < 0]
    return {
        "total_municipios": total,
        "n_perdendo": len(perdendo),
        "pct_perdendo": len(perdendo) / total * 100 if total else 0.0,
        "populacao_perdida": float(-perdendo["variacao_absoluta"].sum()),
        "cagr_mediano": float(crescimento["cagr_pct"].median()),
    }


def top_crescimento(crescimento: pd.DataFrame, n: int = 20, populacao_minima: int = 20_000) -> pd.DataFrame:
    """Municípios que mais crescem, filtrando os muito pequenos.

    O filtro por população existe porque municípios minúsculos produzem CAGRs
    extremos por ruído de base: sair de 800 para 1.600 habitantes é +100%, mas
    não é um fenômeno comparável ao crescimento de uma cidade média.
    """
    base = crescimento[crescimento["valor_final"] >= populacao_minima]
    return base.nlargest(n, "cagr_pct")[
        ["municipio_nome", "uf_sigla", "regiao_nome", "valor_inicial", "valor_final", "cagr_pct"]
    ].reset_index(drop=True)


def top_declinio(crescimento: pd.DataFrame, n: int = 20, populacao_minima: int = 20_000) -> pd.DataFrame:
    base = crescimento[crescimento["valor_final"] >= populacao_minima]
    return base.nsmallest(n, "cagr_pct")[
        ["municipio_nome", "uf_sigla", "regiao_nome", "valor_inicial", "valor_final", "cagr_pct"]
    ].reset_index(drop=True)


def crescimento_por_regiao(crescimento: pd.DataFrame) -> pd.DataFrame:
    """Ritmo de crescimento agregado por região."""
    return (
        crescimento.groupby("regiao_nome", observed=True)
        .agg(
            n_municipios=("municipio_id", "count"),
            n_perdendo=("variacao_absoluta", lambda s: int((s < 0).sum())),
            cagr_mediano=("cagr_pct", "median"),
            populacao_inicial=("valor_inicial", "sum"),
            populacao_final=("valor_final", "sum"),
        )
        .assign(
            pct_perdendo=lambda d: d["n_perdendo"] / d["n_municipios"] * 100,
            crescimento_regional_pct=lambda d: (
                d["populacao_final"] / d["populacao_inicial"] - 1
            ) * 100,
        )
        .reset_index()
    )


def distribuicao_faixas(crescimento: pd.DataFrame) -> pd.DataFrame:
    """Contagem de municípios por faixa de ritmo de crescimento."""
    resumo = (
        crescimento.groupby("faixa_crescimento", observed=True)
        .agg(n_municipios=("municipio_id", "count"), populacao=("valor_final", "sum"))
        .reset_index()
    )
    resumo["pct_municipios"] = resumo["n_municipios"] / resumo["n_municipios"].sum() * 100
    return resumo


def serie_indexada(populacao: pd.DataFrame, chave: str, ano_base: int | None = None) -> pd.DataFrame:
    """Reindexa séries para base 100 no ano inicial.

    Permite comparar trajetórias de entidades de tamanhos muito diferentes num
    mesmo eixo — sem recorrer a um segundo eixo y, que distorce a leitura.
    """
    df = populacao.dropna(subset=["populacao"]).sort_values("ano")
    ano_base = ano_base or int(df["ano"].min())
    base = df[df["ano"] == ano_base].set_index(chave)["populacao"]
    df = df.copy()
    df["indice"] = df["populacao"] / df[chave].map(base) * 100
    return df
