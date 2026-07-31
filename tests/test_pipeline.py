"""Testes da orquestração do pipeline.

Rodam o pipeline inteiro sobre o Brasil em miniatura de `conftest.py`, com a
extração trocada por fatos sintéticos e a escrita apontada para `tmp_path`.
Nenhuma rede, nenhum arquivo do projeto tocado.

O que vale travar aqui não é a aritmética (isso é `test_transform.py`), e sim as
decisões de **montagem**: qual ano casa com qual, que join não pode perder
linha, e o que acontece quando falta uma etapa.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from ibge_analytics.etl import pipeline

from conftest import ANOS_PIB, CENSO, MUNICIPIOS, PIB_MIL_REAIS, POPULACAO


# --------------------------------------------------------------------------- #
# _ano_populacao_mais_proximo
# --------------------------------------------------------------------------- #

def _populacao(anos: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"ano": anos, "populacao": [1.0] * len(anos)})


def test_ano_de_populacao_exato_quando_existe():
    assert pipeline._ano_populacao_mais_proximo(_populacao([2020, 2021, 2023]), 2023) == 2023


def test_ano_de_populacao_pula_o_buraco_da_serie():
    """2022 e 2023 não são publicados: o PIB de 2023 casa com a população de 2024."""
    assert pipeline._ano_populacao_mais_proximo(_populacao([2020, 2021, 2024, 2025]), 2023) == 2024


def test_empate_de_distancia_escolhe_o_ano_anterior():
    """Entre dois anos igualmente próximos, o mais antigo — não interpolar para frente."""
    assert pipeline._ano_populacao_mais_proximo(_populacao([2021, 2023]), 2022) == 2021


def test_ano_de_populacao_aceita_serie_de_um_ano_so():
    assert pipeline._ano_populacao_mais_proximo(_populacao([2010]), 2023) == 2010


# --------------------------------------------------------------------------- #
# _salvar
# --------------------------------------------------------------------------- #

def test_salvar_grava_parquet_sem_indice(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "PROCESSED_DIR", tmp_path)
    df = pd.DataFrame({"municipio_id": ["3550308"], "populacao": [11_900_000.0]})

    devolvido = pipeline._salvar(df, "teste")

    lido = pd.read_parquet(tmp_path / "teste.parquet")
    assert lido.columns.tolist() == ["municipio_id", "populacao"]
    assert lido.equals(df)
    # Devolve o próprio DataFrame para poder ser usado em cadeia.
    assert devolvido is df


# --------------------------------------------------------------------------- #
# construir_populacao / construir_censo / construir_pib
# --------------------------------------------------------------------------- #

def test_populacao_produz_as_quatro_tabelas(pipeline_isolado, dims):
    pipeline.construir_populacao(dims)
    produzidos = {p.stem for p in pipeline_isolado.glob("*.parquet")}
    assert produzidos == {
        "populacao_municipios",
        "populacao_ufs",
        "crescimento_municipios",
        "crescimento_ufs",
    }


def test_crescimento_municipal_cobre_todos_os_municipios(pipeline_isolado, dims):
    resultado = pipeline.construir_populacao(dims)
    assert len(resultado["crescimento_municipios"]) == len(MUNICIPIOS)


def test_crescimento_municipal_carrega_o_nome_do_municipio(pipeline_isolado, dims):
    """Sem o merge com a dimensão, a tabela sairia só com códigos."""
    cresc = pipeline.construir_populacao(dims)["crescimento_municipios"]
    linha = cresc.set_index("municipio_id").loc["1100015"]
    assert linha["municipio_nome"] == "Alta Floresta D'Oeste"
    assert linha["uf_sigla"] == "RO"
    # Único município que encolhe na série sintética.
    assert linha["variacao_absoluta"] < 0
    assert linha["faixa_crescimento"] == "Perda acentuada"


def test_censo_recalcula_a_densidade_e_bate_com_a_publicada(pipeline_isolado, dims):
    """A variável 614 do IBGE é a conferência da nossa própria conta."""
    mun = pipeline.construir_censo(dims)["municipios"].set_index("municipio_id")
    assert mun["densidade_calculada"].round(2).equals(mun["densidade_hab_km2"].round(2))


def test_pib_calcula_a_estrutura_setorial(pipeline_isolado, dims):
    mun = pipeline.construir_pib(dims)["municipios"]
    partes = [c for c in mun.columns if c.startswith("part_vab_")]
    assert len(partes) == 4
    assert mun[partes].sum(axis=1).round(6).eq(100.0).all()


# --------------------------------------------------------------------------- #
# construir_painel — municipal
# --------------------------------------------------------------------------- #

def test_painel_tem_uma_linha_por_municipio(painel):
    assert len(painel) == len(MUNICIPIOS)
    assert painel["municipio_id"].is_unique


def test_painel_usa_o_ano_mais_recente_de_populacao(painel):
    assert painel["ano_populacao"].eq(2025).all()
    sp = painel.set_index("municipio_id").loc["3550308"]
    assert sp["populacao_atual"] == pytest.approx(POPULACAO["3550308"][2025])


def test_pib_per_capita_usa_a_populacao_contemporanea_do_pib(painel):
    """Dividir o PIB de 2023 pela população de 2025 subestimaria o indicador.

    A regra é casar o PIB com o ano de população mais próximo *publicado* — aqui
    2024 — e registrar em `ano_populacao_pib` qual foi usado.
    """
    sp = painel.set_index("municipio_id").loc["3550308"]
    assert sp["ano_pib"] == 2023
    assert sp["ano_populacao_pib"] == 2024

    esperado = PIB_MIL_REAIS["3550308"][2023] * 1_000 / POPULACAO["3550308"][2024]
    assert sp["pib_per_capita"] == pytest.approx(esperado)
    # E não a conta ingênua com a população mais recente.
    ingenuo = PIB_MIL_REAIS["3550308"][2023] * 1_000 / POPULACAO["3550308"][2025]
    assert sp["pib_per_capita"] != pytest.approx(ingenuo)


def test_municipio_sem_pib_permanece_no_painel(painel):
    """Vigência territorial, não erro de join: o município fica, o PIB fica nulo."""
    campinas = painel.set_index("municipio_id").loc["3509502"]
    assert pd.isna(campinas["pib_mil_reais"])
    assert pd.isna(campinas["pib_per_capita"])
    # O resto da linha continua preenchido.
    assert campinas["populacao_atual"] == pytest.approx(POPULACAO["3509502"][2025])
    assert campinas["uf_sigla"] == "SP"


def test_painel_avisa_quantos_municipios_ficaram_sem_pib(pipeline_isolado, dims, caplog):
    pop = pipeline.construir_populacao(dims)
    censo = pipeline.construir_censo(dims)
    pib = pipeline.construir_pib(dims)
    with caplog.at_level(logging.INFO, logger=pipeline.log.name):
        pipeline.construir_painel(pop, censo, pib, dims)
    assert any("1 municípios sem PIB" in m for m in caplog.messages)


def test_densidade_do_painel_usa_a_populacao_atual(painel):
    """O painel é o retrato mais recente; a densidade do Censo fica ao lado."""
    fortaleza = painel.set_index("municipio_id").loc["2304400"]
    pop_censo, area = CENSO["2304400"]
    assert fortaleza["densidade_atual"] == pytest.approx(POPULACAO["2304400"][2025] / area)
    assert fortaleza["densidade_hab_km2"] == pytest.approx(round(pop_censo / area, 2))


def test_area_zerada_nao_derruba_o_painel(pipeline_isolado, dims, fatos_censo):
    """Área ausente vira densidade nula — no pandas 3 a divisão crua levantaria."""
    fatos_censo["municipios"].loc[
        fatos_censo["municipios"]["localidade_id"] == "1100015", "area_km2"
    ] = 0.0

    pop = pipeline.construir_populacao(dims)
    censo = pipeline.construir_censo(dims)
    pib = pipeline.construir_pib(dims)
    resultado = pipeline.construir_painel(pop, censo, pib, dims).set_index("municipio_id")

    assert pd.isna(resultado.loc["1100015", "densidade_atual"])
    assert resultado["densidade_atual"].notna().sum() == len(MUNICIPIOS) - 1


def test_painel_traz_crescimento_e_territorio_na_mesma_linha(painel):
    """A razão de ser da tabela: um retrato por município, sem novos joins."""
    for coluna in (
        "populacao_atual", "area_km2", "densidade_atual", "pib_per_capita",
        "cagr_pct", "faixa_crescimento", "uf_sigla", "regiao_nome",
    ):
        assert coluna in painel.columns, coluna


# --------------------------------------------------------------------------- #
# construir_painel_uf
# --------------------------------------------------------------------------- #

def test_painel_uf_tem_uma_linha_por_uf(paineis):
    ufs = paineis["ufs"]
    assert len(ufs) == 6
    assert ufs["uf_id"].is_unique


def test_participacoes_do_painel_uf_somam_cem(paineis):
    ufs = paineis["ufs"]
    assert ufs["part_pib_brasil"].sum() == pytest.approx(100.0)
    assert ufs["part_pop_brasil"].sum() == pytest.approx(100.0)


def test_painel_uf_sai_na_ordem_canonica_das_regioes(paineis):
    """Norte→Centro-Oeste, como o IBGE publica — não em ordem alfabética."""
    regioes = paineis["ufs"]["regiao_nome"].astype(str).tolist()
    assert regioes == ["Norte", "Nordeste", "Sudeste", "Sudeste", "Sul", "Centro-Oeste"]


def test_painel_uf_usa_a_mesma_regra_de_ano_do_municipal(paineis):
    ufs = paineis["ufs"]
    assert ufs["ano_pib"].eq(max(ANOS_PIB)).all()
    assert ufs["ano_populacao_pib"].eq(2024).all()


# --------------------------------------------------------------------------- #
# construir_painel_regiao
# --------------------------------------------------------------------------- #

def test_painel_regiao_tem_as_cinco_regioes_em_ordem(paineis):
    regioes = paineis["regioes"]
    assert regioes["regiao_nome"].astype(str).tolist() == [
        "Norte", "Nordeste", "Sudeste", "Sul", "Centro-Oeste"
    ]


def test_painel_regiao_conta_as_ufs_de_cada_regiao(paineis):
    contagem = paineis["regioes"].set_index("regiao_nome")["n_ufs"]
    assert contagem.loc["Sudeste"] == 2
    assert contagem.loc["Norte"] == 1
    assert contagem.sum() == 6


def test_densidade_regional_e_soma_sobre_soma(paineis):
    """Não a média das densidades estaduais — RJ e SP têm áreas muito diferentes."""
    sudeste = paineis["regioes"].set_index("regiao_nome").loc["Sudeste"]
    ufs_sudeste = paineis["ufs"].query("regiao_nome == 'Sudeste'")

    esperado = ufs_sudeste["populacao_atual"].sum() / ufs_sudeste["area_km2"].sum()
    assert sudeste["densidade_atual"] == pytest.approx(esperado)

    media_ingenua = ufs_sudeste["densidade_atual"].mean()
    assert sudeste["densidade_atual"] != pytest.approx(media_ingenua)


def test_participacoes_regionais_somam_cem(paineis):
    regioes = paineis["regioes"]
    for coluna in ("part_pib_brasil", "part_pop_brasil", "part_area_brasil"):
        assert regioes[coluna].sum() == pytest.approx(100.0), coluna


def test_populacao_regional_bate_com_a_municipal(paineis):
    """Os três painéis contam a mesma gente."""
    total_regiao = paineis["regioes"]["populacao_atual"].sum()
    total_uf = paineis["ufs"]["populacao_atual"].sum()
    total_municipal = paineis["municipios"]["populacao_atual"].sum()
    assert total_regiao == pytest.approx(total_uf) == pytest.approx(total_municipal)


# --------------------------------------------------------------------------- #
# executar — orquestração
# --------------------------------------------------------------------------- #

def test_executar_completo_produz_todas_as_tabelas(pipeline_isolado):
    pipeline.executar({"populacao", "censo", "pib"}, com_malhas=False)
    produzidos = {p.stem for p in pipeline_isolado.glob("*.parquet")}
    assert produzidos == {
        "populacao_municipios", "populacao_ufs",
        "crescimento_municipios", "crescimento_ufs",
        "densidade_municipios", "densidade_ufs",
        "pib_municipios", "pib_ufs",
        "painel_municipios", "painel_ufs", "painel_regioes",
    }


def test_executar_parcial_nao_tenta_montar_os_paineis(pipeline_isolado):
    """Sem PIB não há painel — e a falta tem de ser silenciosa, não um KeyError."""
    pipeline.executar({"populacao"}, com_malhas=False)
    produzidos = {p.stem for p in pipeline_isolado.glob("*.parquet")}
    assert "painel_municipios" not in produzidos
    assert "populacao_municipios" in produzidos


def test_sem_malhas_nao_baixa_geojson(pipeline_isolado, monkeypatch):
    chamadas = []
    monkeypatch.setattr(pipeline.extract, "extrair_malhas", lambda *a: chamadas.append(a))
    pipeline.executar({"populacao"}, com_malhas=False)
    assert chamadas == []


def test_com_malhas_passa_as_ufs_das_dimensoes(pipeline_isolado, monkeypatch):
    chamadas = []
    monkeypatch.setattr(pipeline.extract, "extrair_malhas", lambda ufs: chamadas.append(ufs))
    pipeline.executar({"populacao"}, com_malhas=True)
    assert chamadas == [[11, 23, 33, 35, 43, 52]]


# --------------------------------------------------------------------------- #
# main — interface de linha de comando
# --------------------------------------------------------------------------- #

def test_main_roda_tudo_por_padrao(pipeline_isolado, monkeypatch):
    recebido = {}
    monkeypatch.setattr(pipeline, "executar", lambda etapas, com_malhas: recebido.update(
        etapas=etapas, com_malhas=com_malhas
    ))
    monkeypatch.setattr("sys.argv", ["ibge-etl"])
    pipeline.main()
    assert recebido == {"etapas": {"populacao", "censo", "pib"}, "com_malhas": True}


def test_main_respeita_sem_malhas_e_etapas(pipeline_isolado, monkeypatch):
    recebido = {}
    monkeypatch.setattr(pipeline, "executar", lambda etapas, com_malhas: recebido.update(
        etapas=etapas, com_malhas=com_malhas
    ))
    monkeypatch.setattr("sys.argv", ["ibge-etl", "--etapas", "populacao", "pib", "--sem-malhas"])
    pipeline.main()
    assert recebido == {"etapas": {"populacao", "pib"}, "com_malhas": False}


def test_main_rejeita_etapa_inexistente(monkeypatch):
    monkeypatch.setattr("sys.argv", ["ibge-etl", "--etapas", "inflacao"])
    with pytest.raises(SystemExit):
        pipeline.main()
