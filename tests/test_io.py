"""Testes da camada de leitura (`utils.io`).

Dashboard, notebooks e relatório leem por aqui — é a porta que garante que os
três vejam os mesmos dados. O que se testa: a mensagem quando o pipeline ainda
não rodou, a memoização, a reorientação das malhas na carga e a coerência do
inventário `TABELAS` com o que o pipeline de fato grava.
"""

from __future__ import annotations

import inspect
import json
import re

import pandas as pd
import pytest

from ibge_analytics.etl import pipeline
from ibge_analytics.utils import io as uio
from ibge_analytics.viz import maps


@pytest.fixture
def io_isolado(monkeypatch, tmp_path):
    """Aponta `io` para diretórios vazios e zera o cache entre os testes."""
    processed = tmp_path / "processed"
    geo = tmp_path / "geo"
    processed.mkdir()
    geo.mkdir()
    monkeypatch.setattr(uio, "PROCESSED_DIR", processed)
    monkeypatch.setattr(uio, "GEO_DIR", geo)

    uio.carregar.cache_clear()
    uio.carregar_malha.cache_clear()
    yield tmp_path
    # O cache é global: sem limpar, o próximo teste leria o tmp_path deste.
    uio.carregar.cache_clear()
    uio.carregar_malha.cache_clear()


def _gravar(processed, nome: str, df: pd.DataFrame) -> None:
    df.to_parquet(processed / f"{nome}.parquet", index=False)


# --------------------------------------------------------------------------- #
# carregar
# --------------------------------------------------------------------------- #

def test_carregar_le_a_tabela_processada(io_isolado):
    df = pd.DataFrame({"municipio_id": ["3550308"], "populacao_atual": [11_900_000.0]})
    _gravar(io_isolado / "processed", "painel_municipios", df)

    assert uio.carregar("painel_municipios").equals(df)


def test_tabela_ausente_ensina_a_rodar_o_pipeline(io_isolado):
    with pytest.raises(uio.DadosAusentesError, match="ibge_analytics.etl.pipeline"):
        uio.carregar("painel_municipios")


def test_dados_ausentes_continua_sendo_filenotfound(io_isolado):
    """Quem só captura FileNotFoundError não pode ser surpreendido."""
    assert issubclass(uio.DadosAusentesError, FileNotFoundError)
    with pytest.raises(FileNotFoundError):
        uio.carregar("painel_ufs")


def test_carregar_memoiza_a_leitura(io_isolado):
    """O dashboard relê a mesma tabela a cada interação — ler o disco toda vez custa."""
    caminho = io_isolado / "processed" / "painel_ufs.parquet"
    _gravar(io_isolado / "processed", "painel_ufs", pd.DataFrame({"uf_sigla": ["SP"]}))

    primeira = uio.carregar("painel_ufs")
    caminho.unlink()
    segunda = uio.carregar("painel_ufs")

    assert segunda is primeira


def test_dados_disponiveis_reflete_o_painel_municipal(io_isolado):
    assert uio.dados_disponiveis() is False
    _gravar(io_isolado / "processed", "painel_municipios", pd.DataFrame({"x": [1]}))
    assert uio.dados_disponiveis() is True


# --------------------------------------------------------------------------- #
# resumo_datasets
# --------------------------------------------------------------------------- #

def test_resumo_lista_apenas_o_que_existe(io_isolado):
    _gravar(io_isolado / "processed", "painel_ufs", pd.DataFrame({"uf_sigla": ["SP", "RJ"]}))

    resumo = uio.resumo_datasets()

    assert resumo["tabela"].tolist() == ["painel_ufs"]
    assert resumo["linhas"].iloc[0] == 2
    assert resumo["colunas"].iloc[0] == 1
    assert resumo["tamanho_kb"].iloc[0] > 0
    assert resumo["descrição"].iloc[0] == uio.TABELAS["painel_ufs"]


def test_resumo_vazio_nao_quebra(io_isolado):
    assert uio.resumo_datasets().empty


# --------------------------------------------------------------------------- #
# Inventário × pipeline
# --------------------------------------------------------------------------- #

def _tabelas_gravadas_pelo_pipeline() -> set[str]:
    fonte = inspect.getsource(pipeline)
    return set(re.findall(r'_salvar\([^,]+,\s*"([^"]+)"\)', fonte))


def test_toda_tabela_do_inventario_e_produzida_pelo_pipeline():
    """Uma entrada órfã em TABELAS vira uma linha que nunca aparece no resumo."""
    assert set(uio.TABELAS) <= _tabelas_gravadas_pelo_pipeline()


def test_toda_tabela_do_pipeline_esta_no_inventario():
    """E o contrário: uma tabela nova que ninguém descreve fica invisível."""
    assert _tabelas_gravadas_pelo_pipeline() <= set(uio.TABELAS)


def test_inventario_descreve_cada_tabela():
    assert all(descricao.strip() for descricao in uio.TABELAS.values())


# --------------------------------------------------------------------------- #
# carregar_malha
# --------------------------------------------------------------------------- #

#: Quadrado anti-horário — a orientação em que o IBGE publica (RFC 7946).
QUADRADO_ANTI_HORARIO = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]


def _malha(anel: list) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"codarea": "35"},
                "geometry": {"type": "Polygon", "coordinates": [anel]},
            }
        ],
    }


def test_malha_e_reorientada_na_carga(io_isolado):
    """O Plotly usa winding esférico: anel externo anti-horário pinta o avesso."""
    caminho = io_isolado / "geo" / "ufs.geojson"
    caminho.write_text(json.dumps(_malha(QUADRADO_ANTI_HORARIO)), encoding="utf-8")

    carregada = uio.carregar_malha("ufs")

    anel = carregada["features"][0]["geometry"]["coordinates"][0]
    assert maps._area_assinada([(x, y) for x, y in anel]) > 0  # horário
    assert anel[::-1] == QUADRADO_ANTI_HORARIO


def test_malha_ausente_ensina_a_baixar(io_isolado):
    with pytest.raises(uio.DadosAusentesError, match="--sem-malhas"):
        uio.carregar_malha("municipios")


def test_malha_e_memoizada(io_isolado):
    caminho = io_isolado / "geo" / "regioes.geojson"
    caminho.write_text(json.dumps(_malha(QUADRADO_ANTI_HORARIO)), encoding="utf-8")

    primeira = uio.carregar_malha("regioes")
    caminho.unlink()

    assert uio.carregar_malha("regioes") is primeira
