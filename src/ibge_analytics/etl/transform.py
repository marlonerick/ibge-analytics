"""Transformação: cruza os fatos com a hierarquia territorial e deriva métricas.

Saída em data/processed/ — tabelas analíticas prontas para o dashboard, os
notebooks e os testes. Regra do módulo: nada de I/O de rede aqui.
"""

from __future__ import annotations

import logging

import pandas as pd

from ..config import ORDEM_REGIOES

log = logging.getLogger(__name__)

#: Municípios instalados depois do fim da série do PIB (2023) existem na
#: população mas não no PIB. Não é erro de join — é vigência territorial.
#: Ver docs/API_NOTES.md.
MUNICIPIOS_SEM_PIB = {"5101837"}  # Boa Esperança do Norte - MT, instalado em 2025


def _normalizar_id(serie: pd.Series) -> pd.Series:
    """Códigos IBGE são identificadores, não números — sempre string."""
    return serie.astype(str).str.strip()


def denominador_seguro(serie: pd.Series) -> pd.Series:
    """Anula zeros e negativos para que a divisão produza NaN em vez de erro.

    Necessário porque `(a / b).where(b > 0)` avalia a divisão antes de mascarar,
    e o pandas 3 levanta ZeroDivisionError em vez de devolver inf.
    """
    return serie.where(serie > 0)


# --------------------------------------------------------------------------- #
# Enriquecimento territorial
# --------------------------------------------------------------------------- #

def enriquecer_municipios(fatos: pd.DataFrame, dim_municipios: pd.DataFrame) -> pd.DataFrame:
    """Anexa UF, região e mesorregião a uma tabela de fatos municipais.

    Descartamos `localidade_nome` do SIDRA de propósito: ele vem em formatos
    inconsistentes entre agregados ("São Paulo (SP)" vs "São Paulo - SP"). O
    nome canônico vem da API de Localidades.
    """
    fatos = fatos.copy()
    fatos["municipio_id"] = _normalizar_id(fatos["localidade_id"])

    dim = dim_municipios.copy()
    dim["municipio_id"] = _normalizar_id(dim["municipio_id"])

    resultado = fatos.drop(columns=["localidade_id", "localidade_nome", "nivel"]).merge(
        dim, on="municipio_id", how="left", validate="many_to_one"
    )

    orfaos = resultado["uf_sigla"].isna().sum()
    if orfaos:
        log.warning("%d linhas municipais sem correspondência na dimensão", orfaos)
    return resultado


def enriquecer_ufs(fatos: pd.DataFrame, dim_estados: pd.DataFrame) -> pd.DataFrame:
    """Anexa sigla e região a uma tabela de fatos estaduais."""
    fatos = fatos.copy()
    fatos["uf_id"] = fatos["localidade_id"].astype(int)
    return fatos.drop(columns=["localidade_id", "localidade_nome", "nivel"]).merge(
        dim_estados, on="uf_id", how="left", validate="many_to_one"
    )


# --------------------------------------------------------------------------- #
# Métricas derivadas
# --------------------------------------------------------------------------- #

def calcular_densidade(df: pd.DataFrame) -> pd.DataFrame:
    """Densidade demográfica a partir de população e área.

    O Censo 2022 já publica a variável 614, mas recalculamos para poder aplicar
    a mesma fórmula a qualquer ano da série estimada. A coluna publicada é
    mantida como `densidade_hab_km2` para conferência.
    """
    df = df.copy()
    pop = df.get("populacao_censo", df.get("populacao"))
    # Mascarar o denominador (e não o resultado) — mascarar depois ainda
    # executa a divisão por zero, que o pandas 3 levanta como erro.
    df["densidade_calculada"] = pop / denominador_seguro(df["area_km2"])
    return df


def calcular_pib_per_capita(df: pd.DataFrame) -> pd.DataFrame:
    """PIB per capita em reais.

    O PIB do SIDRA está em mil reais — daí o fator 1.000.
    """
    df = df.copy()
    pop = df.get("populacao_censo", df.get("populacao"))
    df["pib_per_capita"] = df["pib_mil_reais"] * 1_000 / denominador_seguro(pop)
    return df


def calcular_estrutura_setorial(df: pd.DataFrame) -> pd.DataFrame:
    """Participação de cada setor no valor adicionado bruto total."""
    df = df.copy()
    setores = [
        "vab_agropecuaria",
        "vab_industria",
        "vab_servicos",
        "vab_administracao_publica",
    ]
    disponiveis = [c for c in setores if c in df.columns]
    if not disponiveis:
        return df
    total_vab = df[disponiveis].sum(axis=1)
    seguro = denominador_seguro(total_vab)
    for setor in disponiveis:
        df[f"part_{setor}"] = df[setor] / seguro * 100
    df["vab_total"] = total_vab
    return df


def calcular_crescimento(
    df: pd.DataFrame,
    chave: str,
    valor: str = "populacao",
    ano_col: str = "ano",
) -> pd.DataFrame:
    """Crescimento entre o primeiro e o último ano disponível de cada entidade.

    Devolve variação absoluta, variação percentual e CAGR (taxa média de
    crescimento anual composta) — a métrica correta para comparar entidades
    cujas séries podem ter comprimentos diferentes.
    """
    df = df.dropna(subset=[valor])
    ordenado = df.sort_values(ano_col)
    agg = ordenado.groupby(chave).agg(
        ano_inicial=(ano_col, "first"),
        ano_final=(ano_col, "last"),
        valor_inicial=(valor, "first"),
        valor_final=(valor, "last"),
    )
    agg = agg[agg["valor_inicial"] > 0]

    anos = agg["ano_final"] - agg["ano_inicial"]
    agg["variacao_absoluta"] = agg["valor_final"] - agg["valor_inicial"]
    agg["variacao_pct"] = (agg["valor_final"] / agg["valor_inicial"] - 1) * 100
    agg["cagr_pct"] = (
        (agg["valor_final"] / agg["valor_inicial"]) ** (1 / anos.where(anos > 0)) - 1
    ) * 100
    # Série de um ponto só não tem CAGR. Mascarar depois é obrigatório: o
    # expoente vira NaN, mas `1.0 ** NaN` é 1.0 em NumPy, então o cálculo
    # devolveria 0% de crescimento em vez de indefinido — e o município cairia
    # calado na faixa "crescimento lento".
    agg.loc[anos <= 0, "cagr_pct"] = float("nan")
    return agg.reset_index()


def classificar_crescimento(df: pd.DataFrame, col: str = "cagr_pct") -> pd.DataFrame:
    """Rotula o ritmo de crescimento em faixas legíveis.

    Os cortes seguem o crescimento nacional como referência: o Brasil cresceu a
    ~0,5% a.a. na última década, então "acelerado" é o dobro disso.
    """
    df = df.copy()
    df["faixa_crescimento"] = pd.cut(
        df[col],
        bins=[-float("inf"), -0.5, 0.0, 0.5, 1.0, float("inf")],
        labels=[
            "Perda acentuada",
            "Perda leve",
            "Crescimento lento",
            "Crescimento moderado",
            "Crescimento acelerado",
        ],
    )
    return df


def concentracao(df: pd.DataFrame, valor: str) -> dict[str, float]:
    """Métricas de concentração de uma distribuição (Gini + share dos topos)."""
    serie = df[valor].dropna().sort_values()
    if serie.empty:
        return {}
    n = len(serie)
    total = serie.sum()
    # Gini pela fórmula do ordenamento: 2*sum(i*x_i)/(n*sum(x)) - (n+1)/n
    indices = pd.Series(range(1, n + 1), index=serie.index)
    gini = (2 * (indices * serie).sum()) / (n * total) - (n + 1) / n

    decrescente = serie.sort_values(ascending=False)
    return {
        "gini": float(gini),
        "n": n,
        "share_top_1pct": float(decrescente.head(max(1, n // 100)).sum() / total * 100),
        "share_top_10pct": float(decrescente.head(max(1, n // 10)).sum() / total * 100),
        "share_top_100": float(decrescente.head(100).sum() / total * 100),
    }


# --------------------------------------------------------------------------- #
# Agregação regional
# --------------------------------------------------------------------------- #

def agregar_por_regiao(df: pd.DataFrame, colunas_soma: list[str]) -> pd.DataFrame:
    """Soma indicadores por região, preservando a ordem canônica do IBGE."""
    disponiveis = [c for c in colunas_soma if c in df.columns]
    agregado = df.groupby("regiao_nome", as_index=False)[disponiveis].sum(min_count=1)
    agregado["regiao_nome"] = pd.Categorical(
        agregado["regiao_nome"], categories=ORDEM_REGIOES, ordered=True
    )
    return agregado.sort_values("regiao_nome").reset_index(drop=True)


def ordenar_regioes(df: pd.DataFrame, col: str = "regiao_nome") -> pd.DataFrame:
    df = df.copy()
    df[col] = pd.Categorical(df[col], categories=ORDEM_REGIOES, ordered=True)
    return df.sort_values(col)
