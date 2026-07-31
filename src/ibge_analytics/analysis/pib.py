"""Análise econômica: PIB, PIB per capita, concentração e estrutura setorial."""

from __future__ import annotations

import pandas as pd

from ..etl.transform import concentracao

SETORES = {
    "part_vab_agropecuaria": "Agropecuária",
    "part_vab_industria": "Indústria",
    "part_vab_servicos": "Serviços",
    "part_vab_administracao_publica": "Administração pública",
}


def ranking_ufs(painel_uf: pd.DataFrame, coluna: str = "pib_mil_reais") -> pd.DataFrame:
    """UFs ordenadas por um indicador econômico."""
    cols = ["uf_sigla", "uf_nome", "regiao_nome", coluna, "part_pib_brasil", "pib_per_capita"]
    existentes = [c for c in cols if c in painel_uf.columns]
    return painel_uf.sort_values(coluna, ascending=False)[existentes].reset_index(drop=True)


def concentracao_pib(painel: pd.DataFrame) -> dict[str, float]:
    """Concentração do PIB entre municípios."""
    return concentracao(painel, "pib_mil_reais")


def estrutura_setorial(painel: pd.DataFrame, chave: str = "uf_sigla") -> pd.DataFrame:
    """Composição percentual do valor adicionado por entidade — formato longo.

    Formato longo porque é o que os gráficos de barra empilhada consomem.
    """
    disponiveis = [c for c in SETORES if c in painel.columns]
    longo = painel.melt(
        id_vars=[chave, "regiao_nome"],
        value_vars=disponiveis,
        var_name="setor",
        value_name="participacao",
    )
    longo["setor"] = longo["setor"].map(SETORES)
    return longo.dropna(subset=["participacao"])


def descolamento_pib_populacao(painel_uf: pd.DataFrame) -> pd.DataFrame:
    """Compara a fatia do PIB com a fatia da população de cada UF.

    A razão entre as duas é o indicador de desigualdade regional mais direto:
    acima de 1, a UF concentra mais riqueza do que gente.
    """
    df = painel_uf.copy()
    df["razao_pib_pop"] = df["part_pib_brasil"] / df["part_pop_brasil"]
    return df.sort_values("razao_pib_pop", ascending=False)[
        [
            "uf_sigla",
            "uf_nome",
            "regiao_nome",
            "part_pib_brasil",
            "part_pop_brasil",
            "razao_pib_pop",
            "pib_per_capita",
        ]
    ].reset_index(drop=True)


def evolucao_participacao(pib_ufs: pd.DataFrame) -> pd.DataFrame:
    """Participação de cada UF no PIB nacional ao longo do tempo.

    Mostra se a economia está desconcentrando geograficamente ou não.
    """
    df = pib_ufs.dropna(subset=["pib_mil_reais"]).copy()
    total_ano = df.groupby("ano")["pib_mil_reais"].transform("sum")
    df["part_pib_brasil"] = df["pib_mil_reais"] / total_ano * 100
    return df


def evolucao_participacao_regional(pib_ufs: pd.DataFrame) -> pd.DataFrame:
    """Idem, agregado por região."""
    df = evolucao_participacao(pib_ufs)
    return (
        df.groupby(["ano", "regiao_nome"], observed=True, as_index=False)["part_pib_brasil"]
        .sum()
    )


def top_municipios_pib(painel: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    cols = ["municipio_nome", "uf_sigla", "regiao_nome", "pib_mil_reais", "pib_per_capita",
            "populacao_atual"]
    return painel.nlargest(n, "pib_mil_reais")[cols].reset_index(drop=True)


def resumo_concentracao_municipal(painel: pd.DataFrame) -> dict[str, float]:
    """Quantos municípios somam metade do PIB do país."""
    serie = painel["pib_mil_reais"].dropna().sort_values(ascending=False)
    acumulado = serie.cumsum() / serie.sum()
    n_metade = int((acumulado < 0.5).sum()) + 1
    return {
        "n_municipios_metade_pib": n_metade,
        "pct_municipios_metade_pib": n_metade / len(serie) * 100,
        "share_top_10": float(serie.head(10).sum() / serie.sum() * 100),
        **concentracao(painel, "pib_mil_reais"),
    }
