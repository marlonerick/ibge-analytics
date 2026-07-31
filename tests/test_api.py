"""Testes da camada de API.

O planejamento de lotes, o parsing da resposta do SIDRA, o cache do cliente HTTP
e o achatamento da hierarquia de Localidades são testados sem rede — as
respostas das APIs entram como payloads fixos. Os testes que batem na API real
ficam marcados com `network` e são pulados por padrão:

    pytest                      # só os offline
    pytest -m network           # inclui os que chamam a API
"""

from __future__ import annotations

import json
import os
import time

import pandas as pd
import pytest
import requests

from ibge_analytics import config
from ibge_analytics.api import agregados, localidades
from ibge_analytics.api.client import IBGEAPIError, IBGEClient
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
# serie_de — formato largo e anos publicados
# --------------------------------------------------------------------------- #

def _payload_censo(localidade: str = "35", nome: str = "São Paulo") -> list[dict]:
    """Resposta do agregado 4714 (Censo 2022) com as três variáveis."""
    return [
        {
            "id": str(var_id),
            "variavel": rotulo,
            "unidade": "-",
            "resultados": [
                {
                    "classificacoes": [],
                    "series": [
                        {
                            "localidade": {
                                "id": localidade,
                                "nivel": {"id": "N3", "nome": "Unidade da Federação"},
                                "nome": nome,
                            },
                            "serie": {"2022": valor},
                        }
                    ],
                }
            ],
        }
        for var_id, rotulo, valor in [
            (93, "População residente", "44411238"),
            (6318, "Área territorial", "248219.481"),
            (614, "Densidade demográfica", "178.92"),
        ]
    ]


class _ClienteFalso:
    """Cliente que devolve períodos e payload fixos, anotando as URLs pedidas."""

    def __init__(self, periodos: list[int], payload: list[dict]) -> None:
        self._periodos = periodos
        self._payload = payload
        self.urls: list[str] = []

    def get_json(self, url: str, params: dict | None = None):
        self.urls.append(url)
        if url.endswith("/periodos"):
            return [{"id": str(ano)} for ano in self._periodos]
        return self._payload


def test_serie_de_devolve_uma_coluna_por_variavel():
    """As análises consomem formato largo, com os nomes canônicos do registro."""
    cliente = _ClienteFalso([2022], _payload_censo())
    df = agregados.serie_de(config.CENSO_2022, "N3", client=cliente)

    assert len(df) == 1
    assert set(df.columns) == {
        "localidade_id", "localidade_nome", "nivel", "ano",
        "populacao_censo", "area_km2", "densidade_hab_km2",
    }
    assert df["populacao_censo"].iloc[0] == pytest.approx(44_411_238.0)
    assert df["area_km2"].iloc[0] == pytest.approx(248_219.481)


def test_serie_de_descarta_ano_que_o_agregado_nao_publica():
    """Pedir um ano inexistente não dá erro na API: ele some da resposta."""
    cliente = _ClienteFalso([2022], _payload_censo())
    agregados.serie_de(config.CENSO_2022, "N3", anos=[2022, 2023], client=cliente)

    url_dados = next(u for u in cliente.urls if "/periodos/" in u)
    assert "/periodos/2022/" in url_dados
    assert "2023" not in url_dados


def test_serie_de_consulta_os_periodos_antes_de_supor():
    cliente = _ClienteFalso([2022], _payload_censo())
    agregados.serie_de(config.CENSO_2022, "N3", client=cliente)
    assert cliente.urls[0].endswith(f"/{config.CENSO_2022.id}/periodos")


def test_serie_de_sem_dados_devolve_vazio():
    cliente = _ClienteFalso([2022], [])
    assert agregados.serie_de(config.CENSO_2022, "N3", client=cliente).empty


def test_serie_deduplica_localidade_ano_variavel():
    """Um retry pode reentregar o mesmo lote; a linha não pode duplicar."""
    cliente = _ClienteFalso([2022], _payload_censo() + _payload_censo())
    df = agregados.serie(4714, [93, 6318, 614], [2022], "N3", client=cliente)
    assert len(df) == 3  # três variáveis, uma localidade, um ano


# --------------------------------------------------------------------------- #
# Cliente HTTP — cache em disco
# --------------------------------------------------------------------------- #

class _RespostaFalsa:
    def __init__(self, payload=None, status: int = 200, texto: str = "", json_valido=True):
        self._payload = payload
        self._json_valido = json_valido
        self.status_code = status
        self.text = texto
        self.url = "https://servicodados.ibge.gov.br/fake"
        self.content = b"{}"

    def json(self):
        if not self._json_valido:
            raise ValueError("resposta não é JSON")
        return self._payload


class _SessaoFalsa:
    def __init__(self, resposta: _RespostaFalsa | Exception) -> None:
        self.resposta = resposta
        self.pedidos: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, timeout=None):
        self.pedidos.append((url, params))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


@pytest.fixture
def cliente(tmp_path):
    """Cliente com cache num diretório temporário e sessão substituível."""
    def montar(resposta=None, **kwargs) -> tuple[IBGEClient, _SessaoFalsa]:
        instancia = IBGEClient(cache_dir=tmp_path, **kwargs)
        sessao = _SessaoFalsa(resposta if resposta is not None else _RespostaFalsa({"ok": 1}))
        instancia.session = sessao
        return instancia, sessao

    return montar


URL = "https://servicodados.ibge.gov.br/api/v3/agregados/4714/periodos"


def test_segunda_chamada_vem_do_cache(cliente):
    """Uma requisição municipal custa 5-15s: repeti-la é o desperdício a evitar."""
    api, sessao = cliente()
    assert api.get_json(URL) == {"ok": 1}
    assert api.get_json(URL) == {"ok": 1}
    assert len(sessao.pedidos) == 1


def test_cache_distingue_parametros_diferentes(cliente):
    """Mesma URL com `localidades` diferente é outra resposta, não um hit."""
    api, sessao = cliente()
    api.get_json(URL, params={"localidades": "N3"})
    api.get_json(URL, params={"localidades": "N6"})
    assert len(sessao.pedidos) == 2


def test_cache_e_reaproveitado_por_outro_processo(cliente, tmp_path):
    api, _ = cliente()
    api.get_json(URL)

    outro, sessao_nova = cliente()
    assert outro.get_json(URL) == {"ok": 1}
    assert sessao_nova.pedidos == []


def test_cache_desligado_nao_grava_nem_le(cliente, tmp_path):
    api, sessao = cliente(use_cache=False)
    api.get_json(URL)
    api.get_json(URL)
    assert len(sessao.pedidos) == 2
    assert list(tmp_path.glob("*.json")) == []


def test_cache_expirado_e_rebaixado(cliente, tmp_path):
    api, sessao = cliente(ttl_dias=30)
    api.get_json(URL)

    arquivo = next(tmp_path.glob("*.json"))
    antigo = time.time() - 31 * 86_400
    os.utime(arquivo, (antigo, antigo))

    api.get_json(URL)
    assert len(sessao.pedidos) == 2


def test_cache_corrompido_e_tratado_como_miss(cliente, tmp_path):
    """Escrita interrompida deixa JSON truncado — não pode derrubar o pipeline."""
    api, sessao = cliente()
    api.get_json(URL)
    next(tmp_path.glob("*.json")).write_text('{"ok": ', encoding="utf-8")

    assert api.get_json(URL) == {"ok": 1}
    assert len(sessao.pedidos) == 2


def test_escrita_do_cache_e_atomica(cliente, tmp_path):
    """Nenhum `.tmp` sobrevive à gravação — senão viraria cache fantasma."""
    api, _ = cliente()
    api.get_json(URL)
    assert list(tmp_path.glob("*.tmp")) == []
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8")) == {"ok": 1}


# --------------------------------------------------------------------------- #
# Cliente HTTP — falhas
# --------------------------------------------------------------------------- #

def test_status_de_erro_vira_ibgeapierror(cliente):
    api, _ = cliente(_RespostaFalsa(status=500, texto="Internal Server Error"))
    with pytest.raises(IBGEAPIError, match="HTTP 500"):
        api.get_json(URL)


def test_falha_de_rede_vira_ibgeapierror(cliente):
    api, _ = cliente(requests.ConnectionError("sem rota para o host"))
    with pytest.raises(IBGEAPIError, match="falha de rede"):
        api.get_json(URL)


def test_resposta_nao_json_vira_ibgeapierror(cliente):
    api, _ = cliente(_RespostaFalsa(json_valido=False))
    with pytest.raises(IBGEAPIError, match="não-JSON"):
        api.get_json(URL)


def test_resposta_com_erro_nao_e_cacheada(cliente, tmp_path):
    api, _ = cliente(_RespostaFalsa(status=500, texto="boom"))
    with pytest.raises(IBGEAPIError):
        api.get_json(URL)
    assert list(tmp_path.glob("*.json")) == []


def test_geojson_exige_featurecollection(cliente):
    api, _ = cliente(_RespostaFalsa({"erro": "parâmetro inválido"}))
    with pytest.raises(IBGEAPIError, match="FeatureCollection"):
        api.get_geojson(URL)


def test_geojson_valido_passa(cliente):
    malha = {"type": "FeatureCollection", "features": []}
    api, _ = cliente(_RespostaFalsa(malha))
    assert api.get_geojson(URL) == malha


# --------------------------------------------------------------------------- #
# Localidades — achatamento da hierarquia
# --------------------------------------------------------------------------- #

MUNICIPIO_COMPLETO = {
    "id": 3550308,
    "nome": "São Paulo",
    "microrregiao": {
        "id": 35061,
        "nome": "São Paulo",
        "mesorregiao": {
            "id": 3515,
            "nome": "Metropolitana de São Paulo",
            "UF": {
                "id": 35,
                "sigla": "SP",
                "nome": "São Paulo",
                "regiao": {"id": 3, "sigla": "SE", "nome": "Sudeste"},
            },
        },
    },
}

#: Município novo: sem microrregião, a UF só aparece pela região imediata.
MUNICIPIO_SEM_MICRORREGIAO = {
    "id": 5101837,
    "nome": "Boa Esperança do Norte",
    "microrregiao": None,
    "regiao-imediata": {
        "id": 510031,
        "nome": "Sorriso",
        "regiao-intermediaria": {
            "id": 5104,
            "nome": "Sinop",
            "UF": {
                "id": 51,
                "sigla": "MT",
                "nome": "Mato Grosso",
                "regiao": {"id": 5, "sigla": "CO", "nome": "Centro-Oeste"},
            },
        },
    },
}

MUNICIPIO_ORFAO = {"id": 9999999, "nome": "Sem hierarquia", "microrregiao": None}


class _ClienteLocalidades:
    def __init__(self, payload) -> None:
        self._payload = payload

    def get_json(self, url, params=None):
        return self._payload


def test_municipio_traz_a_hierarquia_achatada():
    df = localidades.municipios(_ClienteLocalidades([MUNICIPIO_COMPLETO]))
    linha = df.iloc[0]
    assert linha["municipio_id"] == 3550308
    assert linha["mesorregiao_nome"] == "Metropolitana de São Paulo"
    assert linha["uf_sigla"] == "SP"
    assert linha["regiao_nome"] == "Sudeste"


def test_municipio_sem_microrregiao_ainda_encontra_a_uf():
    """Municípios recém-instalados só têm região imediata — e não podem sumir."""
    df = localidades.municipios(_ClienteLocalidades([MUNICIPIO_SEM_MICRORREGIAO]))
    linha = df.iloc[0]
    assert linha["uf_sigla"] == "MT"
    assert linha["regiao_nome"] == "Centro-Oeste"
    assert pd.isna(linha["microrregiao_id"]) and pd.isna(linha["mesorregiao_nome"])


def test_municipio_sem_uf_nenhuma_e_descartado():
    """Sem UF não há como cruzar com os fatos; entrar no dim quebraria o join."""
    payload = [MUNICIPIO_COMPLETO, MUNICIPIO_ORFAO]
    df = localidades.municipios(_ClienteLocalidades(payload))
    assert df["municipio_id"].tolist() == [3550308]


def test_estados_achata_a_regiao():
    payload = [
        {
            "id": 35,
            "sigla": "SP",
            "nome": "São Paulo",
            "regiao": {"id": 3, "sigla": "SE", "nome": "Sudeste"},
        }
    ]
    df = localidades.estados(_ClienteLocalidades(payload))
    assert df.columns.tolist() == [
        "uf_id", "uf_sigla", "uf_nome", "regiao_id", "regiao_sigla", "regiao_nome"
    ]
    assert df["regiao_sigla"].iloc[0] == "SE"


def test_regioes_traz_as_cinco_colunas_canonicas():
    payload = [{"id": 3, "sigla": "SE", "nome": "Sudeste"}]
    df = localidades.regioes(_ClienteLocalidades(payload))
    assert df.columns.tolist() == ["regiao_id", "regiao_sigla", "regiao_nome"]


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
