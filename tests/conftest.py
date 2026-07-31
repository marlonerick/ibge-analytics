"""Fixtures compartilhadas: um Brasil em miniatura.

Sete municípios, seis UFs e as cinco regiões, montados **no formato em que as
APIs entregam** — colunas `localidade_*`, série de população com buraco em
2022-2023, PIB terminando dois anos antes da população e um município sem PIB
nenhum. É pouco dado de propósito: cada número que os testes conferem pode ser
recalculado na mão a partir das tabelas deste arquivo.

Quem consome:
  * `test_pipeline.py` — roda os construtores sobre estes fatos;
  * `test_analysis.py` — analisa os painéis que saem dali;
  * `test_io.py`       — usa os mesmos painéis como conteúdo de disco.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ibge_analytics.etl import pipeline

# --------------------------------------------------------------------------- #
# Território
# --------------------------------------------------------------------------- #

#: uf_id, sigla, nome, regiao_id, regiao_sigla, regiao_nome
UFS = [
    (11, "RO", "Rondônia", 1, "N", "Norte"),
    (23, "CE", "Ceará", 2, "NE", "Nordeste"),
    (33, "RJ", "Rio de Janeiro", 3, "SE", "Sudeste"),
    (35, "SP", "São Paulo", 3, "SE", "Sudeste"),
    (43, "RS", "Rio Grande do Sul", 4, "S", "Sul"),
    (52, "GO", "Goiás", 5, "CO", "Centro-Oeste"),
]

#: municipio_id, nome, uf_id. O Sudeste tem duas UFs e São Paulo tem dois
#: municípios — sem isso, "somar por região" e "contar UFs" passariam por acaso.
MUNICIPIOS = [
    ("1100015", "Alta Floresta D'Oeste", 11),
    ("2304400", "Fortaleza", 23),
    ("3304557", "Rio de Janeiro", 33),
    ("3509502", "Campinas", 35),
    ("3550308", "São Paulo", 35),
    ("4314902", "Porto Alegre", 43),
    ("5208707", "Goiânia", 52),
]

UF_DO_MUNICIPIO = {mun: uf for mun, _, uf in MUNICIPIOS}

# --------------------------------------------------------------------------- #
# Fatos
# --------------------------------------------------------------------------- #

#: A série real pula 2022 e 2023 (estimativa suspensa na revisão pós-Censo).
ANOS_POPULACAO = [2020, 2021, 2024, 2025]

POPULACAO = {
    "1100015": {2020: 22_000.0, 2021: 21_500.0, 2024: 20_000.0, 2025: 19_500.0},
    "2304400": {2020: 2_600_000.0, 2021: 2_620_000.0, 2024: 2_700_000.0, 2025: 2_720_000.0},
    "3304557": {2020: 6_700_000.0, 2021: 6_710_000.0, 2024: 6_720_000.0, 2025: 6_730_000.0},
    "3509502": {2020: 1_200_000.0, 2021: 1_210_000.0, 2024: 1_240_000.0, 2025: 1_250_000.0},
    "3550308": {2020: 11_800_000.0, 2021: 11_820_000.0, 2024: 11_880_000.0, 2025: 11_900_000.0},
    "4314902": {2020: 1_490_000.0, 2021: 1_480_000.0, 2024: 1_460_000.0, 2025: 1_450_000.0},
    "5208707": {2020: 1_520_000.0, 2021: 1_540_000.0, 2024: 1_580_000.0, 2025: 1_600_000.0},
}

#: Censo 2022: população recenseada e área territorial (km²).
CENSO = {
    "1100015": (21_000.0, 7_067.0),
    "2304400": (2_428_000.0, 312.0),
    "3304557": (6_211_000.0, 1_200.0),
    "3509502": (1_139_000.0, 795.0),
    "3550308": (11_451_000.0, 1_521.0),
    "4314902": (1_332_000.0, 495.0),
    "5208707": (1_437_000.0, 729.0),
}

ANOS_PIB = [2021, 2023]

#: Campinas (3509502) não aparece: representa o município cuja vigência
#: territorial não cobre a série do PIB — o join tem de deixá-lo passar.
PIB_MIL_REAIS = {
    "1100015": {2021: 500_000.0, 2023: 560_000.0},
    "2304400": {2021: 79_000_000.0, 2023: 92_000_000.0},
    "3304557": {2021: 375_000_000.0, 2023: 430_000_000.0},
    "3550308": {2021: 828_000_000.0, 2023: 950_000_000.0},
    "4314902": {2021: 93_000_000.0, 2023: 105_000_000.0},
    "5208707": {2021: 68_000_000.0, 2023: 78_000_000.0},
}

#: (agropecuária, indústria, serviços, administração pública) — frações do VAB.
PERFIL_SETORIAL = {
    "1100015": (0.40, 0.10, 0.35, 0.15),
    "2304400": (0.01, 0.19, 0.60, 0.20),
    "3304557": (0.01, 0.25, 0.59, 0.15),
    "3550308": (0.00, 0.20, 0.70, 0.10),
    "4314902": (0.01, 0.15, 0.69, 0.15),
    "5208707": (0.02, 0.18, 0.62, 0.18),
}

#: Fatia do PIB que é valor adicionado; o resto são impostos líquidos.
FRACAO_VAB = 0.85


# --------------------------------------------------------------------------- #
# Construtores
# --------------------------------------------------------------------------- #

def _nome_uf(uf_id: int) -> str:
    return next(nome for id_, _, nome, *_ in UFS if id_ == uf_id)


def _somar_por_uf(por_municipio: dict[str, dict[int, float]]) -> dict[int, dict[int, float]]:
    """Agrega uma métrica municipal para o nível de UF."""
    total: dict[int, dict[int, float]] = {}
    for mun_id, serie in por_municipio.items():
        uf = UF_DO_MUNICIPIO[mun_id]
        for ano, valor in serie.items():
            total.setdefault(uf, {})
            total[uf][ano] = total[uf].get(ano, 0.0) + valor
    return total


def _vabs(mun_id: str, pib: float) -> dict[str, float]:
    agro, ind, serv, adm = PERFIL_SETORIAL[mun_id]
    vab = pib * FRACAO_VAB
    return {
        "vab_agropecuaria": vab * agro,
        "vab_industria": vab * ind,
        "vab_servicos": vab * serv,
        "vab_administracao_publica": vab * adm,
        "impostos_liquidos": pib - vab,
    }


def _fatos_populacao_municipios() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "localidade_id": mun_id,
                "localidade_nome": f"{nome} ({_sigla(uf)})",
                "nivel": "N6",
                "ano": ano,
                "populacao": POPULACAO[mun_id][ano],
            }
            for mun_id, nome, uf in MUNICIPIOS
            for ano in ANOS_POPULACAO
        ]
    )


def _sigla(uf_id: int) -> str:
    return next(sigla for id_, sigla, *_ in UFS if id_ == uf_id)


def _fatos_populacao_ufs() -> pd.DataFrame:
    por_uf = _somar_por_uf(POPULACAO)
    return pd.DataFrame(
        [
            {
                "localidade_id": str(uf_id),
                "localidade_nome": _nome_uf(uf_id),
                "nivel": "N3",
                "ano": ano,
                "populacao": valor,
            }
            for uf_id, serie in por_uf.items()
            for ano, valor in serie.items()
        ]
    )


def _fatos_censo_municipios() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "localidade_id": mun_id,
                "localidade_nome": nome,
                "nivel": "N6",
                "ano": 2022,
                "populacao_censo": CENSO[mun_id][0],
                "area_km2": CENSO[mun_id][1],
                # A variável 614 do Censo: a densidade que o IBGE publica.
                "densidade_hab_km2": round(CENSO[mun_id][0] / CENSO[mun_id][1], 2),
            }
            for mun_id, nome, _ in MUNICIPIOS
        ]
    )


def _fatos_censo_ufs() -> pd.DataFrame:
    populacao = _somar_por_uf({m: {2022: CENSO[m][0]} for m, _, _ in MUNICIPIOS})
    area = _somar_por_uf({m: {2022: CENSO[m][1]} for m, _, _ in MUNICIPIOS})
    return pd.DataFrame(
        [
            {
                "localidade_id": str(uf_id),
                "localidade_nome": _nome_uf(uf_id),
                "nivel": "N3",
                "ano": 2022,
                "populacao_censo": populacao[uf_id][2022],
                "area_km2": area[uf_id][2022],
                "densidade_hab_km2": round(populacao[uf_id][2022] / area[uf_id][2022], 2),
            }
            for uf_id, *_ in UFS
        ]
    )


def _fatos_pib_municipios() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "localidade_id": mun_id,
                "localidade_nome": nome,
                "nivel": "N6",
                "ano": ano,
                "pib_mil_reais": PIB_MIL_REAIS[mun_id][ano],
                **_vabs(mun_id, PIB_MIL_REAIS[mun_id][ano]),
            }
            for mun_id, nome, _ in MUNICIPIOS
            if mun_id in PIB_MIL_REAIS
            for ano in ANOS_PIB
        ]
    )


def _fatos_pib_ufs() -> pd.DataFrame:
    linhas = []
    for uf_id, *_ in UFS:
        municipios_da_uf = [m for m in PIB_MIL_REAIS if UF_DO_MUNICIPIO[m] == uf_id]
        for ano in ANOS_PIB:
            pib = sum(PIB_MIL_REAIS[m][ano] for m in municipios_da_uf)
            vabs: dict[str, float] = {}
            for m in municipios_da_uf:
                for chave, valor in _vabs(m, PIB_MIL_REAIS[m][ano]).items():
                    vabs[chave] = vabs.get(chave, 0.0) + valor
            linhas.append(
                {
                    "localidade_id": str(uf_id),
                    "localidade_nome": _nome_uf(uf_id),
                    "nivel": "N3",
                    "ano": ano,
                    "pib_mil_reais": pib,
                    **vabs,
                }
            )
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- #
# Fixtures — dimensões e fatos crus
# --------------------------------------------------------------------------- #

@pytest.fixture
def dim_estados() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "uf_id": uf_id,
                "uf_sigla": sigla,
                "uf_nome": nome,
                "regiao_id": reg_id,
                "regiao_sigla": reg_sigla,
                "regiao_nome": reg_nome,
            }
            for uf_id, sigla, nome, reg_id, reg_sigla, reg_nome in UFS
        ]
    )


@pytest.fixture
def dim_municipios(dim_estados: pd.DataFrame) -> pd.DataFrame:
    por_uf = dim_estados.set_index("uf_id")
    return pd.DataFrame(
        [
            {
                "municipio_id": mun_id,
                "municipio_nome": nome,
                "uf_id": uf_id,
                "uf_sigla": por_uf.loc[uf_id, "uf_sigla"],
                "uf_nome": por_uf.loc[uf_id, "uf_nome"],
                "regiao_id": por_uf.loc[uf_id, "regiao_id"],
                "regiao_sigla": por_uf.loc[uf_id, "regiao_sigla"],
                "regiao_nome": por_uf.loc[uf_id, "regiao_nome"],
            }
            for mun_id, nome, uf_id in MUNICIPIOS
        ]
    )


@pytest.fixture
def dims(dim_municipios: pd.DataFrame, dim_estados: pd.DataFrame) -> dict:
    return {"municipios": dim_municipios, "estados": dim_estados}


@pytest.fixture
def fatos_populacao() -> dict[str, pd.DataFrame]:
    return {"municipios": _fatos_populacao_municipios(), "ufs": _fatos_populacao_ufs()}


@pytest.fixture
def fatos_censo() -> dict[str, pd.DataFrame]:
    return {"municipios": _fatos_censo_municipios(), "ufs": _fatos_censo_ufs()}


@pytest.fixture
def fatos_pib() -> dict[str, pd.DataFrame]:
    return {"municipios": _fatos_pib_municipios(), "ufs": _fatos_pib_ufs()}


# --------------------------------------------------------------------------- #
# Fixtures — pipeline rodado sobre os fatos sintéticos
# --------------------------------------------------------------------------- #

@pytest.fixture
def pipeline_isolado(monkeypatch, tmp_path, dims, fatos_populacao, fatos_censo, fatos_pib):
    """Pipeline escrevendo em tmp_path e lendo os fatos sintéticos.

    Redireciona `PROCESSED_DIR` **antes** de qualquer construtor rodar: sem
    isso, os testes sobrescreveriam `data/processed/` do desenvolvedor com sete
    municípios inventados.
    """
    monkeypatch.setattr(pipeline, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(pipeline.extract, "extrair_dimensoes", lambda: dims)
    monkeypatch.setattr(pipeline.extract, "extrair_populacao", lambda *a, **k: fatos_populacao)
    monkeypatch.setattr(pipeline.extract, "extrair_censo", lambda *a, **k: fatos_censo)
    monkeypatch.setattr(pipeline.extract, "extrair_pib", lambda *a, **k: fatos_pib)
    monkeypatch.setattr(pipeline.extract, "extrair_malhas", lambda *a, **k: None)
    return tmp_path


@pytest.fixture
def paineis(pipeline_isolado, dims) -> dict:
    """Saída completa do pipeline sobre o Brasil em miniatura."""
    pop = pipeline.construir_populacao(dims)
    censo = pipeline.construir_censo(dims)
    pib = pipeline.construir_pib(dims)
    painel = pipeline.construir_painel(pop, censo, pib, dims)
    painel_uf = pipeline.construir_painel_uf(pop, censo, pib, dims)
    painel_regiao = pipeline.construir_painel_regiao(painel_uf)
    return {
        "populacao": pop,
        "censo": censo,
        "pib": pib,
        "municipios": painel,
        "ufs": painel_uf,
        "regioes": painel_regiao,
        "destino": pipeline_isolado,
    }


@pytest.fixture
def painel(paineis) -> pd.DataFrame:
    """Atalho para o painel municipal — o insumo da maioria das análises."""
    return paineis["municipios"]
