"""Testes da camada de API.

O planejamento de lotes e o parsing da resposta do SIDRA são testados sem rede.
Os testes que batem na API real ficam marcados com `network` e são pulados por
padrão:

    pytest                      # só os offline
    pytest -m network           # inclui os que chamam a API
"""

from __future__ import annotations

import pandas as pd
import pytest

from ibge_analytics.api import agregados
from ibge_analytics.config import MAX_CELULAS_POR_REQUISICAO


# --------------------------------------------------------------------------- #
# Planejamento de lotes
# --------------------------------------------------------------------------- #

def _celulas(vars_, anos, n_loc):
    return len(vars_) * len(anos) * n_loc


def test_nivel_pequeno_cabe_numa_requisicao():
    """27 UFs × 22 anos × 1 variável não precisa de lote."""
    planos = agregados._planejar_lotes([37], list(range(2002, 2024)), "N3", 27)
    assert len(planos) == 1


def test_municipal_uma_variavel_fatia_por_periodo():
    """1 var × 5.570 municípios: cabem ~5 anos por requisição."""
    anos = list(range(2001, 2026))
    planos = agregados._planejar_lotes([9324], anos, "N6", 5_570)
    assert len(planos) > 1
    for vars_lote, anos_lote in planos:
        assert _celulas(vars_lote, anos_lote, 5_570) <= MAX_CELULAS_POR_REQUISICAO


def test_municipal_muitas_variaveis_fatia_por_variavel_e_periodo():
    """6 vars × 5.570 já estoura num único ano — fatia também por variável."""
    variaveis = [37, 513, 517, 6575, 525, 543]
    anos = list(range(2010, 2024))
    planos = agregados._planejar_lotes(variaveis, anos, "N6", 5_570)
    for vars_lote, anos_lote in planos:
        assert _celulas(vars_lote, anos_lote, 5_570) <= MAX_CELULAS_POR_REQUISICAO


def test_planejamento_cobre_todos_os_anos_e_variaveis():
    """Nenhum par (variável, ano) pode se perder no fatiamento."""
    variaveis = [37, 513, 517, 6575, 525, 543]
    anos = list(range(2010, 2024))
    planos = agregados._planejar_lotes(variaveis, anos, "N6", 5_570)
    cobertos = {(v, a) for vars_lote, anos_lote in planos for v in vars_lote for a in anos_lote}
    assert cobertos == {(v, a) for v in variaveis for a in anos}


def test_planejamento_nao_duplica_pares():
    variaveis = [37, 513]
    anos = list(range(2010, 2024))
    planos = agregados._planejar_lotes(variaveis, anos, "N6", 5_570)
    pares = [(v, a) for vars_lote, anos_lote in planos for v in vars_lote for a in anos_lote]
    assert len(pares) == len(set(pares))


# --------------------------------------------------------------------------- #
# Parsing da resposta do SIDRA
# --------------------------------------------------------------------------- #

RESPOSTA = [
    {
        "id": "9324",
        "variavel": "População residente estimada",
        "unidade": "Pessoas",
        "resultados": [
            {
                "classificacoes": [],
                "series": [
                    {
                        "localidade": {"id": "3550308", "nivel": {"id": "N6", "nome": "Município"},
                                       "nome": "São Paulo (SP)"},
                        "serie": {"2024": "11895578", "2025": "11904961"},
                    },
                    {
                        "localidade": {"id": "3304557", "nivel": {"id": "N6", "nome": "Município"},
                                       "nome": "Rio de Janeiro (RJ)"},
                        "serie": {"2024": "6729894", "2025": "..."},
                    },
                ],
            }
        ],
    }
]


def test_achatar_produz_uma_linha_por_localidade_e_ano():
    linhas = agregados._achatar(RESPOSTA, "N6")
    assert len(linhas) == 4


def test_achatar_converte_valores_para_numero():
    linhas = agregados._achatar(RESPOSTA, "N6")
    sp2025 = next(l for l in linhas if l["localidade_id"] == "3550308" and l["ano"] == 2025)
    assert sp2025["valor"] == pytest.approx(11_904_961.0)
    assert sp2025["variavel_id"] == 9324


@pytest.mark.parametrize("sentinela", ["...", "..", "X", "-", ""])
def test_sentinelas_do_sidra_viram_nulo(sentinela):
    """O SIDRA usa strings em vez de null; não podem virar 0 nem quebrar."""
    assert agregados._para_numero(sentinela) is None


def test_sentinela_na_serie_vira_nulo_e_nao_zero():
    linhas = agregados._achatar(RESPOSTA, "N6")
    rj2025 = next(l for l in linhas if l["localidade_id"] == "3304557" and l["ano"] == 2025)
    assert rj2025["valor"] is None


def test_para_numero_aceita_decimal():
    assert agregados._para_numero("123.45") == pytest.approx(123.45)


# --------------------------------------------------------------------------- #
# Testes contra a API real
# --------------------------------------------------------------------------- #

@pytest.mark.network
def test_populacao_estimada_nao_publica_anos_de_censo():
    """Trava a peculiaridade que mais causou erro silencioso neste projeto."""
    anos = agregados.anos_disponiveis(6579)
    for ausente in (2007, 2010, 2022, 2023):
        assert ausente not in anos
    assert 2025 in anos


@pytest.mark.network
def test_metadados_do_pib_tem_a_variavel_esperada():
    meta = agregados.metadados(5938)
    ids = {v["id"] for v in meta["variaveis"]}
    assert 37 in ids  # PIB a preços correntes


@pytest.mark.network
def test_serie_estadual_traz_as_27_ufs():
    df = agregados.serie(6579, [9324], [2025], "N3")
    assert len(df) == 27
    assert df["valor"].notna().all()
