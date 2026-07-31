"""Testes da camada visual.

O foco é o que quebra silenciosamente: a orientação dos polígonos (que já
produziu um mapa inteiramente preenchido, sem erro nenhum) e a formatação
numérica no padrão brasileiro.
"""

from __future__ import annotations

import pytest

from ibge_analytics.viz import maps
from ibge_analytics.viz.theme import (
    CORES_REGIAO,
    SERIES_CLARO,
    SERIES_ESCURO,
    formatar_compacto,
    formatar_numero,
)


# --------------------------------------------------------------------------- #
# Orientação de polígonos
# --------------------------------------------------------------------------- #

#: Quadrado em sentido anti-horário (convenção do RFC 7946 e do IBGE).
ANTI_HORARIO = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
HORARIO = ANTI_HORARIO[::-1]


def _malha(anel):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"codarea": "11"},
                "geometry": {"type": "Polygon", "coordinates": [anel]},
            }
        ],
    }


def test_anel_externo_vira_horario():
    """O d3-geo do Plotly preenche o interior só com anel externo horário.

    Com o anel anti-horário ele pinta o *complemento* — a projeção inteira sai
    colorida e a área fica vazada.
    """
    resultado = maps.reorientar_malha(_malha(ANTI_HORARIO))
    anel = resultado["features"][0]["geometry"]["coordinates"][0]
    assert maps._area_assinada([(x, y) for x, y in anel]) > 0


def test_anel_ja_horario_permanece_intacto():
    resultado = maps.reorientar_malha(_malha(HORARIO))
    assert resultado["features"][0]["geometry"]["coordinates"][0] == HORARIO


def test_buraco_fica_anti_horario():
    """Buracos precisam da orientação oposta à do anel externo."""
    externo = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    buraco = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]
    malha = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"codarea": "11"},
                "geometry": {"type": "Polygon", "coordinates": [externo, buraco]},
            }
        ],
    }
    coords = maps.reorientar_malha(malha)["features"][0]["geometry"]["coordinates"]
    assert maps._area_assinada([(x, y) for x, y in coords[0]]) > 0   # externo horário
    assert maps._area_assinada([(x, y) for x, y in coords[1]]) < 0   # buraco anti-horário


def test_multipolygon_e_reorientado():
    malha = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"codarea": "11"},
                "geometry": {"type": "MultiPolygon", "coordinates": [[ANTI_HORARIO], [ANTI_HORARIO]]},
            }
        ],
    }
    coords = maps.reorientar_malha(malha)["features"][0]["geometry"]["coordinates"]
    for poligono in coords:
        assert maps._area_assinada([(x, y) for x, y in poligono[0]]) > 0


def test_reorientar_e_idempotente():
    uma = maps.reorientar_malha(_malha(ANTI_HORARIO))
    duas = maps.reorientar_malha(maps.reorientar_malha(_malha(ANTI_HORARIO)))
    assert uma["features"][0]["geometry"] == duas["features"][0]["geometry"]


# --------------------------------------------------------------------------- #
# Filtro de malha
# --------------------------------------------------------------------------- #

def test_filtrar_malha_mantem_apenas_os_codigos_pedidos():
    malha = {
        "type": "FeatureCollection",
        "features": [
            {"properties": {"codarea": "3550308"}, "geometry": {}},
            {"properties": {"codarea": "3304557"}, "geometry": {}},
            {"properties": {"codarea": "2927408"}, "geometry": {}},
        ],
    }
    resultado = maps.filtrar_malha(malha, {"3550308", "2927408"})
    assert {f["properties"]["codarea"] for f in resultado["features"]} == {"3550308", "2927408"}


# --------------------------------------------------------------------------- #
# Paleta
# --------------------------------------------------------------------------- #

def test_cor_segue_a_regiao_nao_a_posicao():
    """A cor precisa ser estável: filtrar regiões não pode repintar as demais."""
    assert CORES_REGIAO["Norte"] == SERIES_CLARO[0]
    assert CORES_REGIAO["Nordeste"] == SERIES_CLARO[1]
    assert len(set(CORES_REGIAO.values())) == 5


def test_paletas_clara_e_escura_tem_o_mesmo_numero_de_slots():
    assert len(SERIES_CLARO) == len(SERIES_ESCURO) == 8


# --------------------------------------------------------------------------- #
# Formatação (padrão brasileiro)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "valor,casas,esperado",
    [
        (1_234_567, 0, "1.234.567"),
        (1_234.5, 1, "1.234,5"),
        (0, 0, "0"),
        (-1_500, 0, "-1.500"),
    ],
)
def test_formatar_numero_usa_padrao_brasileiro(valor, casas, esperado):
    assert formatar_numero(valor, casas) == esperado


@pytest.mark.parametrize(
    "valor,esperado",
    [(2_300_000, "2,3 mi"), (45_100, "45,1 mil"), (1_500_000_000, "1,5 bi"), (999, "999")],
)
def test_formatar_compacto_abrevia(valor, esperado):
    assert formatar_compacto(valor) == esperado


def test_formatacao_de_nulo():
    assert formatar_numero(None) == "—"
    assert formatar_compacto(float("nan")) == "—"
