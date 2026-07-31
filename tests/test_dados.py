"""Validação das tabelas que o pipeline produziu em `data/processed/`.

Enquanto os outros arquivos testam funções, este testa **os dados**: se o que
está no disco hoje é utilizável pelo dashboard, pelos notebooks e pelo
relatório. Roda sobre os Parquets versionados no repositório e é pulado inteiro
numa máquina onde o pipeline ainda não rodou:

    python -m ibge_analytics.etl.pipeline

Regra ao escrever teste aqui: nada de número mágico que só vale para a rodada
de hoje. As invariantes são estruturais (uma linha por município, participações
que fecham em 100%, a métrica recalculada bate com a coluna gravada) ou têm
folga declarada — o IBGE revisa a série e cria municípios.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ibge_analytics.config import ORDEM_REGIOES, POPULACAO_ESTIMADA
from ibge_analytics.etl.transform import MUNICIPIOS_SEM_PIB, classificar_crescimento
from ibge_analytics.utils import io as uio

pytestmark = pytest.mark.skipif(
    not uio.dados_disponiveis(),
    reason="data/processed vazio — rode o pipeline antes",
)

#: Número oficial de municípios. Só cresce (criação de municípios é lei), então
#: a asserção é um piso, não uma igualdade.
MUNICIPIOS_MINIMO = 5_570

UFS = 27
REGIOES = 5


@pytest.fixture(scope="module")
def painel() -> pd.DataFrame:
    return uio.carregar("painel_municipios")


@pytest.fixture(scope="module")
def painel_uf() -> pd.DataFrame:
    return uio.carregar("painel_ufs")


@pytest.fixture(scope="module")
def painel_regiao() -> pd.DataFrame:
    return uio.carregar("painel_regioes")


@pytest.fixture(scope="module")
def crescimento() -> pd.DataFrame:
    return uio.carregar("crescimento_municipios")


# --------------------------------------------------------------------------- #
# Cobertura territorial
# --------------------------------------------------------------------------- #

def test_painel_cobre_o_pais_inteiro(painel):
    assert len(painel) >= MUNICIPIOS_MINIMO
    assert painel["municipio_id"].is_unique
    assert painel["uf_sigla"].nunique() == UFS
    assert set(painel["regiao_nome"]) == set(ORDEM_REGIOES)


def test_codigo_de_municipio_tem_sete_digitos(painel):
    """O código é identificador, não número: sete dígitos, zero à esquerda inclusive."""
    assert painel["municipio_id"].str.fullmatch(r"\d{7}").all()


def test_codigo_do_municipio_comeca_pelo_codigo_da_uf(painel):
    """Detecta join trocado: os dois primeiros dígitos são a UF, sempre."""
    assert (painel["municipio_id"].str[:2].astype(int) == painel["uf_id"]).all()


def test_todo_municipio_tem_populacao(painel):
    assert painel["populacao_atual"].notna().all()
    assert (painel["populacao_atual"] > 0).all()


def test_so_os_municipios_documentados_ficam_sem_pib(painel):
    """Vigência territorial: instalados depois do fim da série do PIB.

    Se aparecer outro, ou é município novo (atualizar `MUNICIPIOS_SEM_PIB`) ou o
    join do painel quebrou.
    """
    sem_pib = set(painel.loc[painel["pib_mil_reais"].isna(), "municipio_id"])
    assert sem_pib == MUNICIPIOS_SEM_PIB


def test_area_e_positiva_onde_existe(painel):
    areas = painel["area_km2"].dropna()
    assert (areas > 0).all()
    assert len(areas) >= MUNICIPIOS_MINIMO - len(MUNICIPIOS_SEM_PIB)


# --------------------------------------------------------------------------- #
# Métricas gravadas × métricas recalculadas
# --------------------------------------------------------------------------- #

def test_densidade_do_painel_confere_com_populacao_e_area(painel):
    esperado = painel["populacao_atual"] / painel["area_km2"]
    assert (painel["densidade_atual"] - esperado).abs().max() == pytest.approx(0.0)


def test_pib_per_capita_confere_com_o_pib_e_a_populacao_do_ano(painel):
    esperado = painel["pib_mil_reais"] * 1_000 / painel["populacao_ano_pib"]
    assert (painel["pib_per_capita"] - esperado).abs().max() == pytest.approx(0.0)


def test_anos_do_painel_sao_coerentes(painel):
    """A população é mais recente que o PIB, e o ano casado fica perto do PIB."""
    ano_pop = painel["ano_populacao"].unique()
    ano_pib = painel["ano_pib"].unique()
    ano_casado = painel["ano_populacao_pib"].unique()
    assert len(ano_pop) == len(ano_pib) == len(ano_casado) == 1
    assert ano_pop[0] >= ano_pib[0]
    assert abs(int(ano_casado[0]) - int(ano_pib[0])) <= 2


def test_densidade_do_censo_bate_com_a_publicada_pelo_ibge():
    """Nossa conta contra a variável 614 — a conferência mais direta que existe.

    A tolerância é a do arredondamento da fonte (duas casas decimais).
    """
    censo = uio.carregar("densidade_municipios")
    diferenca = (censo["densidade_calculada"] - censo["densidade_hab_km2"]).abs()
    assert diferenca.max() < 0.01


def test_cagr_gravado_confere_com_a_formula(crescimento):
    anos = crescimento["ano_final"] - crescimento["ano_inicial"]
    esperado = ((crescimento["valor_final"] / crescimento["valor_inicial"]) ** (1 / anos) - 1) * 100
    assert (esperado - crescimento["cagr_pct"]).abs().max() == pytest.approx(0.0)


def test_faixa_de_crescimento_corresponde_ao_cagr(crescimento):
    recalculada = classificar_crescimento(crescimento[["cagr_pct"]])["faixa_crescimento"]
    com_cagr = crescimento["cagr_pct"].notna()
    assert (
        recalculada[com_cagr].astype(str) == crescimento.loc[com_cagr, "faixa_crescimento"].astype(str)
    ).all()


def test_crescimento_cobre_os_mesmos_municipios_do_painel(painel, crescimento):
    assert set(crescimento["municipio_id"]) == set(painel["municipio_id"])
    assert crescimento["municipio_id"].is_unique


# --------------------------------------------------------------------------- #
# Séries históricas
# --------------------------------------------------------------------------- #

def test_serie_de_populacao_nao_inventa_anos_de_censo():
    """2007, 2010, 2022 e 2023 não são publicados — se aparecerem, vieram de onde?"""
    populacao = uio.carregar("populacao_municipios")
    anos = set(populacao["ano"])
    assert anos.isdisjoint(POPULACAO_ESTIMADA.periodos_ausentes)
    assert anos <= set(POPULACAO_ESTIMADA.anos)


def test_serie_de_populacao_tem_uma_linha_por_municipio_e_ano():
    populacao = uio.carregar("populacao_municipios")
    assert not populacao.duplicated(["municipio_id", "ano"]).any()
    assert populacao["populacao"].notna().all()
    assert (populacao["populacao"] > 0).all()


def test_serie_de_populacao_chega_ao_ano_mais_recente(painel):
    populacao = uio.carregar("populacao_municipios")
    assert populacao["ano"].max() == painel["ano_populacao"].iloc[0]


def test_serie_de_pib_tem_uma_linha_por_municipio_e_ano():
    pib = uio.carregar("pib_municipios")
    assert not pib.duplicated(["municipio_id", "ano"]).any()
    assert pib["pib_mil_reais"].notna().all()


def test_estrutura_setorial_da_serie_fecha_em_cem_por_cento():
    """Onde há VAB positivo publicado, as quatro participações somam 100%."""
    pib = uio.carregar("pib_municipios")
    partes = [c for c in pib.columns if c.startswith("part_vab_")]
    com_vab = pib[pib["vab_total"] > 0]
    assert len(com_vab) > 60_000
    assert (com_vab[partes].sum(axis=1) - 100).abs().max() < 1e-6


def test_vab_total_negativo_nao_gera_participacao():
    """Percentual sobre base negativa não significa nada — tem de ficar nulo.

    Acontece de verdade: municípios com VAB industrial negativo num ano.
    """
    pib = uio.carregar("pib_municipios")
    partes = [c for c in pib.columns if c.startswith("part_vab_")]
    negativos = pib[pib["vab_total"] < 0]
    assert len(negativos) > 0
    assert negativos[partes].isna().all(axis=None)


def test_pib_negativo_e_raro_mas_existe():
    """Guamaré/RN 2012 tem PIB negativo (VAB industrial negativo no ano).

    O teste existe para que ninguém "conserte" o pipeline filtrando negativos:
    é dado real do IBGE, e o filtro esconderia o município da série.
    """
    pib = uio.carregar("pib_municipios")
    negativos = pib[pib["pib_mil_reais"] < 0]
    assert len(negativos) < 10


# --------------------------------------------------------------------------- #
# Painéis agregados
# --------------------------------------------------------------------------- #

def test_painel_uf_tem_as_vinte_e_sete_unidades(painel_uf):
    assert len(painel_uf) == UFS
    assert painel_uf["uf_sigla"].is_unique
    assert painel_uf["populacao_atual"].notna().all()


def test_participacoes_estaduais_fecham_em_cem(painel_uf):
    assert painel_uf["part_pib_brasil"].sum() == pytest.approx(100.0)
    assert painel_uf["part_pop_brasil"].sum() == pytest.approx(100.0)


def test_painel_regiao_tem_as_cinco_em_ordem_canonica(painel_regiao):
    assert painel_regiao["regiao_nome"].astype(str).tolist() == ORDEM_REGIOES
    assert len(painel_regiao) == REGIOES


def test_regioes_somam_as_vinte_e_sete_ufs(painel_regiao):
    assert painel_regiao["n_ufs"].sum() == UFS


def test_participacoes_regionais_fecham_em_cem(painel_regiao):
    for coluna in ("part_pib_brasil", "part_pop_brasil", "part_area_brasil"):
        assert painel_regiao[coluna].sum() == pytest.approx(100.0), coluna


def test_area_do_brasil_esta_na_ordem_de_grandeza_certa(painel_regiao):
    """~8,51 milhões de km². Erro de unidade ou de join sai desta faixa."""
    assert 8.4e6 < painel_regiao["area_km2"].sum() < 8.6e6


# --------------------------------------------------------------------------- #
# Coerência entre os três níveis
# --------------------------------------------------------------------------- #

def test_a_mesma_populacao_nos_tres_paineis(painel, painel_uf, painel_regiao):
    total_municipal = painel["populacao_atual"].sum()
    assert painel_uf["populacao_atual"].sum() == pytest.approx(total_municipal)
    assert painel_regiao["populacao_atual"].sum() == pytest.approx(total_municipal)


def test_o_mesmo_pib_nos_dois_paineis(painel, painel_uf):
    """Diferença admitida: o SIDRA arredonda cada nível em separado."""
    municipal = painel["pib_mil_reais"].sum()
    estadual = painel_uf["pib_mil_reais"].sum()
    assert abs(municipal - estadual) / estadual < 1e-6


def test_area_municipal_e_estadual_batem_com_folga(painel, painel_uf):
    """A área somada por município fica um pouco abaixo da estadual.

    O Censo atribui a municípios só a área continental; corpos d'água e faixas
    não municipalizadas entram no total da UF. A folga é de 1%.
    """
    municipal = painel["area_km2"].sum()
    estadual = painel_uf["area_km2"].sum()
    assert municipal <= estadual
    assert (estadual - municipal) / estadual < 0.01


def test_populacao_por_regiao_bate_com_a_soma_dos_municipios(painel, painel_regiao):
    por_regiao = painel.groupby("regiao_nome", observed=True)["populacao_atual"].sum()
    gravado = painel_regiao.set_index("regiao_nome")["populacao_atual"]
    for regiao in ORDEM_REGIOES:
        assert gravado.loc[regiao] == pytest.approx(por_regiao.loc[regiao])


# --------------------------------------------------------------------------- #
# Achados que o projeto documenta
# --------------------------------------------------------------------------- #

def test_boa_parte_dos_municipios_perde_populacao(crescimento):
    """O achado central da análise territorial — se sumir, algo mudou na base."""
    perdendo = (crescimento["variacao_absoluta"] < 0).mean() * 100
    assert 20 < perdendo < 45


def test_o_pib_e_extremamente_concentrado(painel):
    serie = painel["pib_mil_reais"].dropna().sort_values(ascending=False)
    acumulado = serie.cumsum() / serie.sum()
    n_metade = int((acumulado < 0.5).sum()) + 1
    assert n_metade / len(serie) < 0.05  # menos de 5% dos municípios


def test_a_ocupacao_do_territorio_e_desigual(painel_regiao):
    """O Norte tem quase metade da área e menos de 10% da gente."""
    norte = painel_regiao.set_index("regiao_nome").loc["Norte"]
    assert norte["part_area_brasil"] > 40
    assert norte["part_pop_brasil"] < 10


# --------------------------------------------------------------------------- #
# Lacuna conhecida da fonte
# --------------------------------------------------------------------------- #

@pytest.mark.xfail(
    strict=True,
    reason=(
        "O IBGE publica o valor adicionado por setor só até 2021, mas o painel é "
        "fixado em ano_pib=2023 — as colunas vab_*/part_vab_* saem 100% nulas e o "
        "gráfico de estrutura setorial do dashboard/relatório fica vazio. Quando o "
        "painel passar a casar o VAB com o último ano publicado (como já faz com a "
        "população), este teste deve passar e a marca sai."
    ),
)
def test_painel_uf_tem_estrutura_setorial(painel_uf):
    partes = [c for c in painel_uf.columns if c.startswith("part_vab_")]
    assert painel_uf[partes].notna().all(axis=None)
    assert (painel_uf[partes].sum(axis=1) - 100).abs().max() < 1e-6


def test_o_vab_da_serie_para_antes_do_pib():
    """Documenta a defasagem que causa o xfail acima, no dado de origem."""
    pib = uio.carregar("pib_municipios")
    ultimo_pib = int(pib["ano"].max())
    ultimo_vab = int(pib.loc[pib["vab_servicos"].notna(), "ano"].max())
    assert ultimo_vab <= ultimo_pib
    assert np.isnan(pib.loc[pib["ano"] == ultimo_pib, "vab_servicos"]).all()
