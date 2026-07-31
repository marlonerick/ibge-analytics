"""Sistema visual dos gráficos e mapas.

A paleta é a paleta de referência do sistema de design, usada sem alteração de
hex. Ela foi validada para os pares adjacentes (barras, linhas, empilhados) nos
dois modos: pior par CVD ΔE 9,1 claro / 8,4 escuro; pior par para visão normal
19,6 claro / 19,3 escuro.

Duas restrições herdadas dessa validação, respeitadas pelos módulos de gráfico:

1. `SERIES[2]`, `SERIES[3]` e `SERIES[4]` (aqua, amarelo, magenta) ficam abaixo
   de 3:1 de contraste sobre a superfície clara. Onde eles aparecem, o gráfico
   traz rótulo direto ou tabela — a cor nunca carrega o dado sozinha.
2. Formas que comparam todos os pares entre si (dispersão, coroplético
   categórico) só suportam as três primeiras cores. Por isso a dispersão por
   região é facetada, e não colorida com as cinco.
"""

from __future__ import annotations

#: Ordem fixa das cores categóricas. Nunca ciclar: uma 9ª série vira "Outros".
SERIES_CLARO = [
    "#2a78d6",  # 1 azul
    "#eb6834",  # 2 laranja
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 amarelo
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 verde
    "#4a3aa7",  # 7 violeta
    "#e34948",  # 8 vermelho
]
SERIES_ESCURO = [
    "#3987e5",
    "#d95926",
    "#199e70",
    "#c98500",
    "#d55181",
    "#008300",
    "#9085e9",
    "#e66767",
]

#: Rampa sequencial (magnitude contínua): um só matiz, claro → escuro.
SEQUENCIAL_AZUL = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec",
    "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
    "#184f95", "#104281", "#0d366b",
]

#: Segunda rampa sequencial, para quando dois contextos de magnitude coexistem.
SEQUENCIAL_LARANJA = [
    "#fde3d5", "#fbc9b0", "#f8ae8b", "#f49267", "#ef7647",
    "#eb6834", "#d4551f", "#b4471a", "#933a15", "#742e11",
]

#: Divergente (polaridade): dois matizes opostos com cinza neutro no meio.
#: Usada em crescimento populacional, onde o zero é um limiar real.
DIVERGENTE = [
    "#0d366b", "#1c5cab", "#2a78d6", "#86b6ef", "#cde2fb",
    "#f0efec",  # neutro — nunca um matiz
    "#f5b8b8", "#e88b8b", "#d03b3b", "#a82c2c", "#7d2020",
]

#: Cores de status — reservadas, nunca reaproveitadas como série.
STATUS = {
    "bom": "#0ca30c",
    "atencao": "#fab219",
    "grave": "#ec835a",
    "critico": "#d03b3b",
}

#: Cromo e tinta.
CLARO = {
    "superficie": "#fcfcfb",
    "plano": "#f9f9f7",
    "tinta_primaria": "#0b0b0b",
    "tinta_secundaria": "#52514e",
    "tinta_suave": "#898781",
    "grade": "#e1e0d9",
    "eixo": "#c3c2b7",
}
ESCURO = {
    "superficie": "#1a1a19",
    "plano": "#0d0d0d",
    "tinta_primaria": "#ffffff",
    "tinta_secundaria": "#c3c2b7",
    "tinta_suave": "#898781",
    "grade": "#2c2c2a",
    "eixo": "#383835",
}

FONTE = 'system-ui, -apple-system, "Segoe UI", sans-serif'

#: Cor fixa por região — a cor segue a entidade, nunca a posição no ranking.
#: Um filtro que muda o número de regiões visíveis não repinta as demais.
CORES_REGIAO = {
    "Norte": SERIES_CLARO[0],
    "Nordeste": SERIES_CLARO[1],
    "Sudeste": SERIES_CLARO[2],
    "Sul": SERIES_CLARO[3],
    "Centro-Oeste": SERIES_CLARO[4],
}

#: Regiões cujo contraste sobre fundo claro é inferior a 3:1 — exigem rótulo
#: direto ou tabela junto ao gráfico (a "regra do alívio").
REGIOES_EXIGEM_ROTULO = {"Sudeste", "Sul", "Centro-Oeste"}


def paleta(modo: str = "claro") -> dict:
    """Devolve o conjunto de tokens do modo pedido."""
    return CLARO if modo == "claro" else ESCURO


def cores_series(modo: str = "claro") -> list[str]:
    return SERIES_CLARO if modo == "claro" else SERIES_ESCURO


def layout_plotly(modo: str = "claro", titulo: str = "", altura: int = 420) -> dict:
    """Layout base do Plotly: grade recessiva, sem moldura, tipografia do sistema."""
    p = paleta(modo)
    return {
        "title": {
            "text": titulo,
            "font": {"size": 17, "color": p["tinta_primaria"], "family": FONTE},
            "x": 0,
            "xanchor": "left",
        },
        "height": altura,
        "font": {"family": FONTE, "size": 13, "color": p["tinta_secundaria"]},
        "paper_bgcolor": p["superficie"],
        "plot_bgcolor": p["superficie"],
        "margin": {"l": 8, "r": 16, "t": 56 if titulo else 20, "b": 8},
        "xaxis": {
            "gridcolor": p["grade"],
            "linecolor": p["eixo"],
            "zerolinecolor": p["eixo"],
            "tickfont": {"color": p["tinta_suave"], "size": 12},
            "automargin": True,
        },
        "yaxis": {
            "gridcolor": p["grade"],
            "linecolor": p["eixo"],
            "zerolinecolor": p["eixo"],
            "tickfont": {"color": p["tinta_suave"], "size": 12},
            "automargin": True,
        },
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.0,
            "x": 0,
            "font": {"color": p["tinta_secundaria"], "size": 12},
            "bgcolor": "rgba(0,0,0,0)",
        },
        "hoverlabel": {"font": {"family": FONTE, "size": 12}, "bordercolor": p["eixo"]},
        "colorway": cores_series(modo),
    }


def formatar_numero(valor: float, casas: int = 0) -> str:
    """Formata no padrão brasileiro: ponto de milhar, vírgula decimal."""
    if valor is None or valor != valor:
        return "—"
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", " ").replace(".", ",").replace(" ", ".")


def formatar_compacto(valor: float) -> str:
    """Abrevia números grandes para eixos e rótulos (2,3 mi / 45,1 mil)."""
    if valor is None or valor != valor:
        return "—"
    for limite, sufixo in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if abs(valor) >= limite:
            return formatar_numero(valor / limite, 1) + sufixo
    return formatar_numero(valor)
