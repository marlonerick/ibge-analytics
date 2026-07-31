"""Testes do registro de agregados e da camada de extração.

O registro em `config.py` é dado de entrada do pipeline: um nível inexistente
ou um ano fora da série vira requisição inútil (ou pior, coluna vazia lá na
frente). Aqui ele é conferido como qualquer outro dado.

Da extração, o que se testa é a **política de janela**: quais anos e quais
níveis cada função pede. As chamadas de API são substituídas por gravadores que
apenas anotam o que foi pedido — nenhuma rede.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ibge_analytics import config
from ibge_analytics.etl import extract


# --------------------------------------------------------------------------- #
# Registro de agregados
# --------------------------------------------------------------------------- #

def test_populacao_estimada_declara_os_buracos_da_serie():
    """2007 e 2010 são anos de Contagem/Censo; 2022-2023, estimativa suspensa."""
    anos = config.POPULACAO_ESTIMADA.anos
    for ausente in (2007, 2010, 2022, 2023):
        assert ausente not in anos
    assert anos[0] == 2001 and anos[-1] == 2025
    # 25 anos de intervalo, 21 de série.
    assert len(anos) == 21


def test_anos_do_censo_2022_tem_um_ponto_so():
    assert config.CENSO_2022.anos == [2022]


def test_pib_termina_antes_da_populacao():
    """A defasagem entre as duas séries é o que obriga o painel a casar anos."""
    assert config.PIB.periodo_fim < config.POPULACAO_ESTIMADA.periodo_fim


@pytest.mark.parametrize("nome", sorted(config.AGREGADOS))
def test_agregado_declara_niveis_conhecidos(nome):
    agregado = config.AGREGADOS[nome]
    for nivel in agregado.niveis:
        assert nivel in config.NIVEL_LABEL, f"{nome}: nível {nivel} sem rótulo"
        assert nivel in config.LOCALIDADES_POR_NIVEL, f"{nome}: nível {nivel} sem tamanho"


@pytest.mark.parametrize("nome", sorted(config.AGREGADOS))
def test_nomes_de_variaveis_nao_colidem(nome):
    """Dois ids apontando para o mesmo nome fariam o pivot perder uma coluna."""
    variaveis = config.AGREGADOS[nome].variaveis
    assert len(set(variaveis.values())) == len(variaveis)


@pytest.mark.parametrize("nome", sorted(config.AGREGADOS))
def test_periodo_do_agregado_e_coerente(nome):
    agregado = config.AGREGADOS[nome]
    assert agregado.periodo_inicio <= agregado.periodo_fim
    assert all(
        agregado.periodo_inicio <= a <= agregado.periodo_fim
        for a in agregado.periodos_ausentes
    )


def test_niveis_da_classe_estao_dimensionados():
    declarados = {v for k, v in vars(config.Nivel).items() if not k.startswith("_")}
    assert declarados <= set(config.LOCALIDADES_POR_NIVEL)


def test_ordem_das_regioes_cobre_as_cinco():
    assert set(config.ORDEM_REGIOES) == set(config.REGIOES.values())
    assert len(config.ORDEM_REGIOES) == 5
    # Ordem canônica do IBGE: norte → sul, e não a ordem alfabética.
    assert config.ORDEM_REGIOES == list(config.REGIOES.values())


def test_teto_de_celulas_cabe_no_pior_nivel():
    """Um único ano de uma variável municipal precisa caber numa requisição."""
    assert config.LOCALIDADES_POR_NIVEL["N6"] <= config.MAX_CELULAS_POR_REQUISICAO


# --------------------------------------------------------------------------- #
# extract — janela de anos e níveis pedidos
# --------------------------------------------------------------------------- #

@pytest.fixture
def api_gravada(monkeypatch, tmp_path):
    """Substitui o SIDRA por um gravador e desvia a escrita para tmp_path."""
    chamadas: list[dict] = []

    def falso_serie_de(agregado, nivel, anos=None, client=None):
        chamadas.append({"agregado": agregado, "nivel": nivel, "anos": anos})
        return pd.DataFrame({"localidade_id": ["1"], "ano": [2025], "valor": [1.0]})

    monkeypatch.setattr(extract, "RAW_DIR", tmp_path)
    monkeypatch.setattr(extract.agregados, "serie_de", falso_serie_de)
    return chamadas


def _pedido(chamadas: list[dict], nivel: str) -> dict:
    return next(c for c in chamadas if c["nivel"] == nivel)


def test_populacao_baixa_os_quatro_niveis(api_gravada, tmp_path):
    extract.extrair_populacao()
    assert {c["nivel"] for c in api_gravada} == {"N1", "N2", "N3", "N6"}
    assert {p.stem for p in tmp_path.glob("*.parquet")} == {
        "pop_municipios", "pop_ufs", "pop_regioes", "pop_brasil"
    }


def test_populacao_pede_a_serie_declarada_no_registro(api_gravada):
    extract.extrair_populacao()
    for chamada in api_gravada:
        assert chamada["anos"] == config.POPULACAO_ESTIMADA.anos
        assert 2022 not in chamada["anos"]


def test_populacao_aceita_janela_explicita(api_gravada):
    extract.extrair_populacao(anos=[2024, 2025])
    assert all(c["anos"] == [2024, 2025] for c in api_gravada)


def test_censo_nao_pede_ano_nenhum(api_gravada):
    """O agregado 4714 tem um período só; deixar `anos=None` evita filtrá-lo."""
    extract.extrair_censo()
    assert all(c["anos"] is None for c in api_gravada)
    assert {c["nivel"] for c in api_gravada} == {"N2", "N3", "N6"}


def test_pib_municipal_baixa_janela_curta_e_agregados_a_serie_inteira(api_gravada):
    """6 variáveis × 5.570 municípios × 22 anos é caro demais para a série toda."""
    extract.extrair_pib()

    municipal = _pedido(api_gravada, "N6")["anos"]
    estadual = _pedido(api_gravada, "N3")["anos"]

    assert min(municipal) == 2010
    assert estadual == config.PIB.anos
    assert len(municipal) < len(estadual)
    assert max(municipal) == max(estadual)


def test_pib_com_janela_explicita_vale_para_todos_os_niveis(api_gravada):
    extract.extrair_pib(anos=[2022, 2023])
    assert all(c["anos"] == [2022, 2023] for c in api_gravada)


def test_extract_salva_parquet_relegivel(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "RAW_DIR", tmp_path)
    df = pd.DataFrame({"localidade_id": ["3550308"], "populacao": [11_900_000.0]})

    extract._salvar(df, "pop_municipios")

    assert pd.read_parquet(tmp_path / "pop_municipios.parquet").equals(df)


def test_dimensoes_salvam_as_tres_tabelas(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "RAW_DIR", tmp_path)
    monkeypatch.setattr(
        extract.localidades, "municipios", lambda: pd.DataFrame({"municipio_id": ["3550308"]})
    )
    monkeypatch.setattr(extract.localidades, "estados", lambda: pd.DataFrame({"uf_id": [35]}))
    monkeypatch.setattr(extract.localidades, "regioes", lambda: pd.DataFrame({"regiao_id": [3]}))

    dims = extract.extrair_dimensoes()

    assert set(dims) == {"municipios", "estados", "regioes"}
    assert {p.stem for p in tmp_path.glob("*.parquet")} == {
        "dim_municipios", "dim_estados", "dim_regioes"
    }


# --------------------------------------------------------------------------- #
# extract — malhas
# --------------------------------------------------------------------------- #

@pytest.fixture
def malhas_gravadas(monkeypatch):
    salvas: list[str] = []
    monkeypatch.setattr(extract.malhas, "malha_ufs", lambda: {"ufs": True})
    monkeypatch.setattr(extract.malhas, "malha_regioes", lambda: {"regioes": True})
    monkeypatch.setattr(extract.malhas, "malha_municipios_brasil", lambda ufs: {"ufs_pedidas": ufs})
    monkeypatch.setattr(extract.malhas, "salvar", lambda malha, nome: salvas.append(nome))
    return salvas


def test_malhas_baixa_os_tres_recortes(malhas_gravadas):
    extract.extrair_malhas([35, 33])
    assert malhas_gravadas == ["ufs", "regioes", "municipios"]


def test_malha_municipal_pode_ser_pulada(malhas_gravadas):
    """A municipal é a cara: 27 requisições e vários MB."""
    extract.extrair_malhas([35, 33], incluir_municipios=False)
    assert malhas_gravadas == ["ufs", "regioes"]
