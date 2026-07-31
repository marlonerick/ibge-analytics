"""API de Agregados v3 (SIDRA) — a fonte de todos os indicadores.

O formato de resposta é aninhado em 4 níveis:

    [ {variavel, unidade, resultados: [ {classificacoes, series: [
        {localidade: {id, nivel, nome}, serie: {ano: valor}} ]} ]} ]

`serie()` achata isso num DataFrame tidy (uma linha por localidade × ano ×
variável) e cuida das duas armadilhas do endpoint: o limite de tamanho da
resposta e os sentinelas de valor ausente.
"""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

import pandas as pd

from ..config import (
    AGREGADOS_URL,
    LOCALIDADES_POR_NIVEL,
    MAX_CELULAS_POR_REQUISICAO,
    Agregado,
)
from .client import IBGEClient, get_client

log = logging.getLogger(__name__)

#: O SIDRA usa strings sentinela em vez de null. Significados (doc do IBGE):
#:   "..."  não se aplica       "-"  zero absoluto
#:   ".."   valor não disponível "X"  omitido para não identificar informante
SENTINELAS_NULOS = {"...", "..", "X", "-", ""}


# --------------------------------------------------------------------------- #
# Metadados
# --------------------------------------------------------------------------- #

def metadados(agregado: int, client: IBGEClient | None = None) -> dict:
    client = client or get_client()
    return client.get_json(f"{AGREGADOS_URL}/{agregado}/metadados")


def periodos(agregado: int, client: IBGEClient | None = None) -> list[str]:
    client = client or get_client()
    return [p["id"] for p in client.get_json(f"{AGREGADOS_URL}/{agregado}/periodos")]


def anos_disponiveis(agregado: int, client: IBGEClient | None = None) -> list[int]:
    """Anos que o agregado realmente publica — a fonte da verdade.

    Séries do IBGE têm buracos que não dá para deduzir do intervalo declarado:
    o agregado 6579 (população estimada) não publica 2007, 2010, 2022 nem 2023
    — anos de Contagem/Censo, ou de estimativa suspensa para revisão pós-Censo.
    Pedir um ano inexistente não dá erro: ele simplesmente some da resposta, o
    que vira coluna vazia lá na frente. Por isso consultamos em vez de supor.
    """
    return sorted(int(p) for p in periodos(agregado, client))


def listar_agregados(client: IBGEClient | None = None) -> pd.DataFrame:
    """Catálogo completo de agregados, achatado por pesquisa."""
    client = client or get_client()
    dados = client.get_json(AGREGADOS_URL)
    return pd.DataFrame(
        [
            {
                "pesquisa_id": pesquisa["id"],
                "pesquisa_nome": pesquisa["nome"],
                "agregado_id": int(ag["id"]),
                "agregado_nome": ag["nome"],
            }
            for pesquisa in dados
            for ag in pesquisa["agregados"]
        ]
    )


# --------------------------------------------------------------------------- #
# Séries
# --------------------------------------------------------------------------- #

def _para_numero(valor: str | None) -> float | None:
    if valor is None or valor in SENTINELAS_NULOS:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _achatar(payload: list[dict], nivel: str) -> list[dict]:
    """Converte a resposta aninhada do SIDRA em linhas tidy."""
    linhas: list[dict] = []
    for variavel in payload:
        var_id = int(variavel["id"])
        var_nome = variavel["variavel"]
        unidade = variavel.get("unidade")
        for resultado in variavel["resultados"]:
            # `classificacoes` só é preenchido quando pedimos corte por
            # classificação; nas nossas consultas vem vazio.
            for serie in resultado["series"]:
                loc = serie["localidade"]
                for ano, valor in serie["serie"].items():
                    linhas.append(
                        {
                            "localidade_id": loc["id"],
                            "localidade_nome": loc["nome"],
                            "nivel": loc["nivel"]["id"],
                            "ano": int(ano),
                            "variavel_id": var_id,
                            "variavel_nome": var_nome,
                            "unidade": unidade,
                            "valor": _para_numero(valor),
                        }
                    )
    return linhas


def _lotes(itens: Sequence, tamanho: int) -> list[Sequence]:
    return [itens[i : i + tamanho] for i in range(0, len(itens), tamanho)]


def _planejar_lotes(
    variaveis: Sequence[int],
    anos: Sequence[int],
    nivel: str,
    n_localidades: int,
) -> list[tuple[Sequence[int], Sequence[int]]]:
    """Divide a consulta em requisições que cabem no limite de tamanho da API.

    O custo de uma requisição é `variáveis × períodos × localidades`. Preferimos
    fatiar por período (mantém as variáveis juntas, o que rende menos
    requisições); só quando um único período já estoura o teto é que fatiamos
    também por variável — caso do PIB municipal, com 6 variáveis × 5.570.
    """
    custo_por_periodo = len(variaveis) * n_localidades

    if custo_por_periodo <= MAX_CELULAS_POR_REQUISICAO:
        periodos_por_lote = max(1, MAX_CELULAS_POR_REQUISICAO // custo_por_periodo)
        return [(variaveis, lote) for lote in _lotes(list(anos), periodos_por_lote)]

    # Uma variável sozinha, um período: o menor pedido possível.
    vars_por_lote = max(1, MAX_CELULAS_POR_REQUISICAO // n_localidades)
    return [
        (lote_var, [ano])
        for lote_var in _lotes(list(variaveis), vars_por_lote)
        for ano in anos
    ]


def serie(
    agregado: int,
    variaveis: Sequence[int],
    periodos_: Sequence[int] | str,
    nivel: str,
    localidades: Sequence[str] | None = None,
    client: IBGEClient | None = None,
) -> pd.DataFrame:
    """Baixa uma série do SIDRA como DataFrame tidy.

    Args:
        agregado: id do agregado (ex.: 6579).
        variaveis: ids das variáveis (ex.: [9324]).
        periodos_: lista de anos, ou "all".
        nivel: nível territorial ("N3", "N6", ...).
        localidades: códigos específicos; None = todas do nível.

    Requisições de nível municipal com muitos períodos estouram o limite do
    servidor (HTTP 500), então elas são quebradas em lotes de períodos e
    reconcatenadas. Níveis agregados (N1/N2/N3) cabem numa requisição só.
    """
    client = client or get_client()
    alvo = f"{nivel}[{','.join(localidades)}]" if localidades else nivel

    n_localidades = len(localidades) if localidades else LOCALIDADES_POR_NIVEL.get(nivel, 1)

    if periodos_ == "all":
        # "all" não permite estimar custo; só é seguro em níveis pequenos.
        planos: list[tuple[Sequence[int], Sequence[int] | str]] = [(variaveis, "all")]
    else:
        planos = _planejar_lotes(variaveis, list(periodos_), nivel, n_localidades)

    partes: list[pd.DataFrame] = []
    for i, (vars_lote, anos_lote) in enumerate(planos, start=1):
        var_path = "|".join(str(v) for v in vars_lote)
        bloco = anos_lote if isinstance(anos_lote, str) else "|".join(str(a) for a in anos_lote)
        url = f"{AGREGADOS_URL}/{agregado}/periodos/{bloco}/variaveis/{var_path}"
        log.info(
            "agregado %s | %s | lote %d/%d (%d var × %d per)",
            agregado, nivel, i, len(planos), len(vars_lote),
            1 if isinstance(anos_lote, str) else len(anos_lote),
        )
        payload = client.get_json(url, params={"localidades": alvo})
        partes.append(pd.DataFrame(_achatar(payload, nivel)))

    df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if df.empty:
        return df
    # Lotes distintos nunca compartilham ano, mas um retry pode duplicar.
    return df.drop_duplicates(subset=["localidade_id", "ano", "variavel_id"], ignore_index=True)


def serie_de(
    agregado: Agregado,
    nivel: str,
    anos: Sequence[int] | None = None,
    client: IBGEClient | None = None,
) -> pd.DataFrame:
    """Como `serie()`, mas dirigido por um `Agregado` do config.

    Renomeia as variáveis para os nomes canônicos do registro e devolve em
    formato largo (uma coluna por variável), que é o formato que as análises
    consomem.
    """
    # Sem lista explícita, usamos os anos que a API declara publicar — nunca o
    # intervalo teórico, que inclui buracos (ver `anos_disponiveis`).
    if anos is None:
        anos = anos_disponiveis(agregado.id, client)
    else:
        publicados = set(anos_disponiveis(agregado.id, client))
        pedidos = list(anos)
        anos = [a for a in pedidos if a in publicados]
        if ignorados := sorted(set(pedidos) - publicados):
            log.warning("agregado %s não publica %s — anos ignorados", agregado.id, ignorados)
    bruto = serie(
        agregado=agregado.id,
        variaveis=list(agregado.variaveis),
        periodos_=anos,
        nivel=nivel,
        client=client,
    )
    if bruto.empty:
        return bruto

    bruto["variavel"] = bruto["variavel_id"].map(agregado.variaveis)
    largo = bruto.pivot_table(
        index=["localidade_id", "localidade_nome", "nivel", "ano"],
        columns="variavel",
        values="valor",
        aggfunc="first",
    ).reset_index()
    largo.columns.name = None
    return largo
