"""Orquestração do pipeline: extract → transform → data/processed/.

Uso:
    python -m ibge_analytics.etl.pipeline            # tudo
    python -m ibge_analytics.etl.pipeline --sem-malhas
    python -m ibge_analytics.etl.pipeline --etapas populacao pib
"""

from __future__ import annotations

import argparse
import logging
import time

import pandas as pd

from ..config import PROCESSED_DIR
from . import extract, transform

log = logging.getLogger(__name__)


def _salvar(df: pd.DataFrame, nome: str) -> pd.DataFrame:
    destino = PROCESSED_DIR / f"{nome}.parquet"
    df.to_parquet(destino, index=False)
    log.info("processed/%s.parquet: %d linhas × %d colunas", nome, *df.shape)
    return df


def _ano_populacao_mais_proximo(populacao: pd.DataFrame, alvo: int) -> int:
    """Ano de população mais próximo de `alvo` entre os efetivamente publicados.

    O PIB vai até 2023, mas a população estimada não publica 2022 nem 2023 (ver
    config.POPULACAO_ESTIMADA). Para o PIB per capita, então, casamos o PIB com
    o ano de população mais próximo disponível e registramos qual foi usado, em
    vez de deixar a divisão virar NaN silenciosamente.
    """
    disponiveis = sorted(populacao["ano"].unique())
    return min(disponiveis, key=lambda a: (abs(a - alvo), a))


def construir_populacao(dims: dict) -> dict[str, pd.DataFrame]:
    """Série histórica de população + métricas de crescimento."""
    bruto = extract.extrair_populacao()

    mun = transform.enriquecer_municipios(bruto["municipios"], dims["municipios"])
    _salvar(mun, "populacao_municipios")

    ufs = transform.enriquecer_ufs(bruto["ufs"], dims["estados"])
    _salvar(ufs, "populacao_ufs")

    # Crescimento municipal: a métrica-chave da análise territorial.
    cresc_mun = transform.calcular_crescimento(mun, chave="municipio_id", valor="populacao")
    cresc_mun = transform.classificar_crescimento(cresc_mun)
    cresc_mun = cresc_mun.merge(
        dims["municipios"].assign(municipio_id=lambda d: d.municipio_id.astype(str)),
        on="municipio_id",
        how="left",
    )
    _salvar(cresc_mun, "crescimento_municipios")

    cresc_uf = transform.calcular_crescimento(ufs, chave="uf_sigla", valor="populacao")
    cresc_uf = transform.classificar_crescimento(cresc_uf).merge(
        dims["estados"], on="uf_sigla", how="left"
    )
    _salvar(cresc_uf, "crescimento_ufs")

    return {"municipios": mun, "ufs": ufs, "crescimento_municipios": cresc_mun}


def construir_censo(dims: dict) -> dict[str, pd.DataFrame]:
    """Censo 2022: área, população e densidade demográfica."""
    bruto = extract.extrair_censo()

    mun = transform.enriquecer_municipios(bruto["municipios"], dims["municipios"])
    mun = transform.calcular_densidade(mun)
    _salvar(mun, "densidade_municipios")

    ufs = transform.enriquecer_ufs(bruto["ufs"], dims["estados"])
    ufs = transform.calcular_densidade(ufs)
    _salvar(ufs, "densidade_ufs")

    return {"municipios": mun, "ufs": ufs}


def construir_pib(dims: dict) -> dict[str, pd.DataFrame]:
    """PIB, PIB per capita e estrutura setorial."""
    bruto = extract.extrair_pib()

    mun = transform.enriquecer_municipios(bruto["municipios"], dims["municipios"])
    mun = transform.calcular_estrutura_setorial(mun)
    _salvar(mun, "pib_municipios")

    ufs = transform.enriquecer_ufs(bruto["ufs"], dims["estados"])
    ufs = transform.calcular_estrutura_setorial(ufs)
    _salvar(ufs, "pib_ufs")

    return {"municipios": mun, "ufs": ufs}


def construir_painel(pop: dict, censo: dict, pib: dict, dims: dict) -> pd.DataFrame:
    """Tabela analítica municipal: um retrato por município no ano mais recente.

    É a tabela que o dashboard e os mapas consomem — junta população atual,
    área, densidade, PIB per capita e ritmo de crescimento numa linha só.
    """
    ano_pop = int(pop["municipios"]["ano"].max())
    ano_pib = int(pib["municipios"]["ano"].max())
    log.info("painel municipal: população %s, PIB %s, censo 2022", ano_pop, ano_pib)

    base = (
        pop["municipios"]
        .query("ano == @ano_pop")[["municipio_id", "populacao"]]
        .rename(columns={"populacao": "populacao_atual"})
    )

    censo_cols = ["municipio_id", "populacao_censo", "area_km2", "densidade_hab_km2"]
    base = base.merge(censo["municipios"][censo_cols], on="municipio_id", how="left")

    pib_ano = pib["municipios"].query("ano == @ano_pib")[
        [
            "municipio_id",
            "pib_mil_reais",
            "vab_agropecuaria",
            "vab_industria",
            "vab_servicos",
            "vab_administracao_publica",
            "part_vab_agropecuaria",
            "part_vab_industria",
            "part_vab_servicos",
            "part_vab_administracao_publica",
        ]
    ]
    base = base.merge(pib_ano, on="municipio_id", how="left")

    # PIB per capita usa a população contemporânea ao PIB, não a mais recente —
    # dividir o PIB de 2023 pela população de 2025 subestimaria o indicador.
    ano_pop_pib = _ano_populacao_mais_proximo(pop["municipios"], ano_pib)
    log.info("PIB per capita: PIB %s ÷ população %s", ano_pib, ano_pop_pib)
    pop_ano_pib = (
        pop["municipios"]
        .query("ano == @ano_pop_pib")[["municipio_id", "populacao"]]
        .rename(columns={"populacao": "populacao_ano_pib"})
    )
    base = base.merge(pop_ano_pib, on="municipio_id", how="left")

    cresc = pop["crescimento_municipios"][
        ["municipio_id", "cagr_pct", "variacao_pct", "variacao_absoluta", "faixa_crescimento"]
    ]
    base = base.merge(cresc, on="municipio_id", how="left")

    dim = dims["municipios"].assign(municipio_id=lambda d: d.municipio_id.astype(str))
    base = base.merge(dim, on="municipio_id", how="left")

    # Densidade e PIB per capita sobre a população atual (não a censitária), para
    # que o painel represente o retrato mais recente possível.
    base["densidade_atual"] = base["populacao_atual"] / transform.denominador_seguro(base["area_km2"])
    base["pib_per_capita"] = base["pib_mil_reais"] * 1_000 / transform.denominador_seguro(
        base["populacao_ano_pib"]
    )
    base["ano_populacao"] = ano_pop
    base["ano_pib"] = ano_pib
    base["ano_populacao_pib"] = ano_pop_pib

    sem_pib = base["pib_mil_reais"].isna().sum()
    if sem_pib:
        log.info("%d municípios sem PIB (esperado: instalados após %s)", sem_pib, ano_pib)

    return _salvar(base, "painel_municipios")


def construir_painel_uf(pop: dict, censo: dict, pib: dict, dims: dict) -> pd.DataFrame:
    """Tabela analítica estadual — a base da comparação entre regiões."""
    ano_pop = int(pop["ufs"]["ano"].max())
    ano_pib = int(pib["ufs"]["ano"].max())

    base = (
        pop["ufs"]
        .query("ano == @ano_pop")[["uf_id", "uf_sigla", "uf_nome", "regiao_nome", "populacao"]]
        .rename(columns={"populacao": "populacao_atual"})
    )
    base = base.merge(
        censo["ufs"][["uf_id", "populacao_censo", "area_km2", "densidade_hab_km2"]],
        on="uf_id",
        how="left",
    )
    pib_cols = [
        "uf_id",
        "pib_mil_reais",
        "vab_agropecuaria",
        "vab_industria",
        "vab_servicos",
        "vab_administracao_publica",
        "part_vab_agropecuaria",
        "part_vab_industria",
        "part_vab_servicos",
        "part_vab_administracao_publica",
    ]
    base = base.merge(pib["ufs"].query("ano == @ano_pib")[pib_cols], on="uf_id", how="left")

    ano_pop_pib = _ano_populacao_mais_proximo(pop["ufs"], ano_pib)
    pop_ano_pib = (
        pop["ufs"]
        .query("ano == @ano_pop_pib")[["uf_id", "populacao"]]
        .rename(columns={"populacao": "populacao_ano_pib"})
    )
    base = base.merge(pop_ano_pib, on="uf_id", how="left")

    base["densidade_atual"] = base["populacao_atual"] / base["area_km2"]
    base["pib_per_capita"] = base["pib_mil_reais"] * 1_000 / base["populacao_ano_pib"]
    base["part_pib_brasil"] = base["pib_mil_reais"] / base["pib_mil_reais"].sum() * 100
    base["part_pop_brasil"] = base["populacao_atual"] / base["populacao_atual"].sum() * 100
    base["ano_populacao"] = ano_pop
    base["ano_pib"] = ano_pib
    base["ano_populacao_pib"] = ano_pop_pib

    return _salvar(transform.ordenar_regioes(base), "painel_ufs")


def construir_painel_regiao(painel_uf: pd.DataFrame) -> pd.DataFrame:
    """Comparação entre as 5 grandes regiões."""
    somaveis = [
        "populacao_atual",
        "populacao_ano_pib",
        "populacao_censo",
        "area_km2",
        "pib_mil_reais",
        "vab_agropecuaria",
        "vab_industria",
        "vab_servicos",
        "vab_administracao_publica",
    ]
    reg = transform.agregar_por_regiao(painel_uf, somaveis)
    reg["densidade_atual"] = reg["populacao_atual"] / reg["area_km2"]
    reg["pib_per_capita"] = reg["pib_mil_reais"] * 1_000 / reg["populacao_ano_pib"]
    reg["part_pib_brasil"] = reg["pib_mil_reais"] / reg["pib_mil_reais"].sum() * 100
    reg["part_pop_brasil"] = reg["populacao_atual"] / reg["populacao_atual"].sum() * 100
    reg["part_area_brasil"] = reg["area_km2"] / reg["area_km2"].sum() * 100
    reg["n_ufs"] = painel_uf.groupby("regiao_nome", observed=True).size().values
    return _salvar(reg, "painel_regioes")


def executar(etapas: set[str], com_malhas: bool = True) -> None:
    inicio = time.perf_counter()

    log.info("=== dimensões ===")
    dims = extract.extrair_dimensoes()

    pop = construir_populacao(dims) if "populacao" in etapas else {}
    censo = construir_censo(dims) if "censo" in etapas else {}
    pib = construir_pib(dims) if "pib" in etapas else {}

    if pop and censo and pib:
        log.info("=== painéis analíticos ===")
        construir_painel(pop, censo, pib, dims)
        painel_uf = construir_painel_uf(pop, censo, pib, dims)
        construir_painel_regiao(painel_uf)

    if com_malhas:
        log.info("=== malhas territoriais ===")
        extract.extrair_malhas(dims["estados"]["uf_id"].tolist())

    log.info("pipeline concluído em %.1fs", time.perf_counter() - inicio)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline de dados IBGE")
    parser.add_argument(
        "--etapas",
        nargs="+",
        default=["populacao", "censo", "pib"],
        choices=["populacao", "censo", "pib"],
    )
    parser.add_argument("--sem-malhas", action="store_true", help="pula o download de GeoJSON")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    executar(set(args.etapas), com_malhas=not args.sem_malhas)


if __name__ == "__main__":
    main()
