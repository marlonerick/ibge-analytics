"""Testes das transformações e métricas derivadas.

São testes puros: nenhuma chamada de rede, nenhum arquivo. As regras de negócio
que valem a pena travar estão aqui — divisão por zero, CAGR, concentração e a
diferença entre densidade regional e média de densidades.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ibge_analytics.etl import transform


# --------------------------------------------------------------------------- #
# denominador_seguro
# --------------------------------------------------------------------------- #

def test_denominador_seguro_anula_zeros_e_negativos():
    serie = pd.Series([10.0, 0.0, -5.0, 2.0])
    resultado = transform.denominador_seguro(serie)
    assert resultado.isna().tolist() == [False, True, True, False]


def test_divisao_por_area_zero_nao_levanta():
    """Municípios com área ausente não podem derrubar o pipeline."""
    df = pd.DataFrame({"populacao_censo": [100.0, 50.0], "area_km2": [10.0, 0.0]})
    resultado = transform.calcular_densidade(df)
    assert resultado["densidade_calculada"].iloc[0] == pytest.approx(10.0)
    assert pd.isna(resultado["densidade_calculada"].iloc[1])


def test_pib_per_capita_converte_mil_reais():
    """O SIDRA publica o PIB em mil reais; o per capita sai em reais."""
    df = pd.DataFrame({"pib_mil_reais": [1_000.0], "populacao": [100.0]})
    resultado = transform.calcular_pib_per_capita(df)
    assert resultado["pib_per_capita"].iloc[0] == pytest.approx(10_000.0)


def test_estrutura_setorial_soma_cem_por_cento():
    df = pd.DataFrame(
        {
            "vab_agropecuaria": [25.0],
            "vab_industria": [25.0],
            "vab_servicos": [25.0],
            "vab_administracao_publica": [25.0],
        }
    )
    resultado = transform.calcular_estrutura_setorial(df)
    partes = [c for c in resultado.columns if c.startswith("part_")]
    assert resultado[partes].sum(axis=1).iloc[0] == pytest.approx(100.0)


def test_estrutura_setorial_com_vab_zerado():
    df = pd.DataFrame(
        {
            "vab_agropecuaria": [0.0], "vab_industria": [0.0],
            "vab_servicos": [0.0], "vab_administracao_publica": [0.0],
        }
    )
    resultado = transform.calcular_estrutura_setorial(df)
    assert pd.isna(resultado["part_vab_industria"].iloc[0])


# --------------------------------------------------------------------------- #
# crescimento
# --------------------------------------------------------------------------- #

def test_cagr_de_dobrar_em_dez_anos():
    """Dobrar em 10 anos equivale a ~7,18% a.a."""
    df = pd.DataFrame(
        {"id": ["a", "a"], "ano": [2010, 2020], "populacao": [1_000.0, 2_000.0]}
    )
    resultado = transform.calcular_crescimento(df, chave="id")
    assert resultado["cagr_pct"].iloc[0] == pytest.approx(7.177, abs=1e-3)
    assert resultado["variacao_pct"].iloc[0] == pytest.approx(100.0)
    assert resultado["variacao_absoluta"].iloc[0] == pytest.approx(1_000.0)


def test_cagr_usa_primeiro_e_ultimo_ano_mesmo_fora_de_ordem():
    df = pd.DataFrame(
        {
            "id": ["a", "a", "a"],
            "ano": [2020, 2010, 2015],
            "populacao": [2_000.0, 1_000.0, 1_500.0],
        }
    )
    resultado = transform.calcular_crescimento(df, chave="id")
    assert resultado["ano_inicial"].iloc[0] == 2010
    assert resultado["ano_final"].iloc[0] == 2020
    assert resultado["valor_final"].iloc[0] == pytest.approx(2_000.0)


def test_cagr_indefinido_para_um_unico_ano():
    df = pd.DataFrame({"id": ["a"], "ano": [2020], "populacao": [1_000.0]})
    resultado = transform.calcular_crescimento(df, chave="id")
    assert pd.isna(resultado["cagr_pct"].iloc[0])


def test_crescimento_ignora_anos_sem_dado():
    """Buracos na série (2007, 2010, 2022, 2023) não podem virar valor inicial."""
    df = pd.DataFrame(
        {
            "id": ["a"] * 3,
            "ano": [2010, 2015, 2020],
            "populacao": [None, 1_000.0, 2_000.0],
        }
    )
    resultado = transform.calcular_crescimento(df, chave="id")
    assert resultado["ano_inicial"].iloc[0] == 2015


def test_classificar_crescimento_separa_perda_de_ganho():
    df = pd.DataFrame({"cagr_pct": [-1.5, -0.2, 0.3, 0.7, 2.0]})
    resultado = transform.classificar_crescimento(df)
    assert resultado["faixa_crescimento"].tolist() == [
        "Perda acentuada", "Perda leve", "Crescimento lento",
        "Crescimento moderado", "Crescimento acelerado",
    ]


# --------------------------------------------------------------------------- #
# concentração
# --------------------------------------------------------------------------- #

def test_gini_zero_para_distribuicao_perfeitamente_igual():
    df = pd.DataFrame({"v": [100.0] * 50})
    assert transform.concentracao(df, "v")["gini"] == pytest.approx(0.0, abs=1e-9)


def test_gini_alto_para_distribuicao_concentrada():
    df = pd.DataFrame({"v": [1.0] * 99 + [10_000.0]})
    assert transform.concentracao(df, "v")["gini"] > 0.9


def test_concentracao_vazia_devolve_dicionario_vazio():
    assert transform.concentracao(pd.DataFrame({"v": [None, None]}), "v") == {}


# --------------------------------------------------------------------------- #
# agregação regional
# --------------------------------------------------------------------------- #

def test_agregar_por_regiao_preserva_ordem_canonica():
    df = pd.DataFrame(
        {
            "regiao_nome": ["Sul", "Norte", "Sudeste", "Centro-Oeste", "Nordeste"],
            "populacao_atual": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    resultado = transform.agregar_por_regiao(df, ["populacao_atual"])
    assert resultado["regiao_nome"].tolist() == [
        "Norte", "Nordeste", "Sudeste", "Sul", "Centro-Oeste"
    ]


def test_densidade_regional_nao_e_media_das_densidades():
    """Densidade da região é população/área somadas — não a média municipal.

    Um município de 3 km² e outro de 159 mil km² não podem pesar igual.
    """
    df = pd.DataFrame(
        {
            "regiao_nome": ["Norte", "Norte"],
            "populacao_atual": [1_000.0, 1_000.0],
            "area_km2": [1.0, 999.0],
        }
    )
    agregado = transform.agregar_por_regiao(df, ["populacao_atual", "area_km2"])
    densidade = agregado["populacao_atual"] / agregado["area_km2"]
    assert densidade.iloc[0] == pytest.approx(2.0)  # 2000/1000
    media_ingenua = (1_000 / 1 + 1_000 / 999) / 2
    assert densidade.iloc[0] != pytest.approx(media_ingenua)


# --------------------------------------------------------------------------- #
# enriquecimento
# --------------------------------------------------------------------------- #

def test_enriquecer_municipios_normaliza_id_para_string():
    fatos = pd.DataFrame(
        {
            "localidade_id": [3550308],  # int vindo do SIDRA
            "localidade_nome": ["São Paulo (SP)"],
            "nivel": ["N6"],
            "populacao": [11_000_000.0],
        }
    )
    dim = pd.DataFrame(
        {
            "municipio_id": ["3550308"],  # string vinda de Localidades
            "municipio_nome": ["São Paulo"],
            "uf_sigla": ["SP"],
            "regiao_nome": ["Sudeste"],
        }
    )
    resultado = transform.enriquecer_municipios(fatos, dim)
    assert resultado["uf_sigla"].iloc[0] == "SP"
    # O nome do SIDRA é descartado em favor do nome canônico.
    assert resultado["municipio_nome"].iloc[0] == "São Paulo"
    assert "localidade_nome" not in resultado.columns
