"""Gráficos Plotly.

Convenções aplicadas em todos os gráficos deste módulo:
  - marcas finas, grade recessiva, sem moldura;
  - um único eixo y — nunca dois eixos com escalas diferentes; séries de
    grandezas distintas vão para facetas ou são indexadas a uma base comum;
  - legenda sempre presente a partir de 2 séries, com rótulo direto quando são
    poucas — a identidade nunca depende só da cor;
  - hover ativo por padrão.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..config import ORDEM_REGIOES
from .theme import (
    CORES_REGIAO,
    DIVERGENTE,
    SEQUENCIAL_AZUL,
    cores_series,
    formatar_compacto,
    formatar_numero,
    layout_plotly,
    paleta,
)

#: Cantos arredondados nas pontas de dado das barras.
RAIO_BARRA = 4


def barras_ranking(
    df: pd.DataFrame,
    x: str,
    y: str,
    titulo: str = "",
    rotulo_valor: str | None = None,
    cor_por_regiao: bool = True,
    modo: str = "claro",
    sufixo: str = "",
    casas: int = 0,
) -> go.Figure:
    """Barras horizontais ordenadas — a forma padrão para comparar magnitudes.

    Rótulos diretos em todas as barras: além de dispensarem a leitura no eixo,
    são o que satisfaz a regra do alívio para as cores de menor contraste.
    """
    p = paleta(modo)
    dados = df.sort_values(x)
    rotulo_valor = rotulo_valor or x

    cores = (
        [CORES_REGIAO.get(r, cores_series(modo)[0]) for r in dados["regiao_nome"]]
        if cor_por_regiao and "regiao_nome" in dados.columns
        else cores_series(modo)[0]
    )

    fig = go.Figure(
        go.Bar(
            x=dados[x],
            y=dados[y],
            orientation="h",
            marker={"color": cores, "line": {"width": 0}},
            text=[f"{formatar_numero(v, casas)}{sufixo}" for v in dados[x]],
            textposition="outside",
            textfont={"color": p["tinta_secundaria"], "size": 12},
            hovertemplate="<b>%{y}</b><br>" + f"{rotulo_valor}: " + "%{text}<extra></extra>",
            cliponaxis=False,
        )
    )
    layout = layout_plotly(modo, titulo, altura=max(320, 22 * len(dados) + 90))
    layout["xaxis"]["showgrid"] = False
    layout["xaxis"]["showticklabels"] = False
    layout["yaxis"]["showgrid"] = False
    fig.update_layout(**layout, bargap=0.25)
    fig.update_traces(marker_cornerradius=RAIO_BARRA)
    return fig


def linha_temporal(
    df: pd.DataFrame,
    x: str = "ano",
    y: str = "populacao",
    cor: str | None = None,
    titulo: str = "",
    modo: str = "claro",
    rotulo_direto: bool = True,
) -> go.Figure:
    """Série temporal. Rótulo direto no fim de cada linha quando são ≤ 4 séries."""
    p = paleta(modo)
    fig = go.Figure()

    if cor is None:
        fig.add_trace(
            go.Scatter(
                x=df[x], y=df[y], mode="lines", name=y,
                line={"width": 2, "color": cores_series(modo)[0]},
                hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>",
            )
        )
    else:
        categorias = [c for c in ORDEM_REGIOES if c in df[cor].unique()] or sorted(
            df[cor].dropna().unique()
        )
        for i, categoria in enumerate(categorias):
            sub = df[df[cor] == categoria].sort_values(x)
            cor_linha = CORES_REGIAO.get(categoria, cores_series(modo)[i % 8])
            fig.add_trace(
                go.Scatter(
                    x=sub[x], y=sub[y], mode="lines", name=str(categoria),
                    line={"width": 2, "color": cor_linha},
                    hovertemplate=f"<b>{categoria}</b><br>%{{x}}<br>%{{y:,.1f}}<extra></extra>",
                )
            )
            # Rótulo direto: a identidade não depende só da cor.
            if rotulo_direto and len(categorias) <= 5 and not sub.empty:
                ultimo = sub.iloc[-1]
                fig.add_annotation(
                    x=ultimo[x], y=ultimo[y], text=f"  {categoria}",
                    showarrow=False, xanchor="left",
                    font={"color": cor_linha, "size": 12},
                )

    layout = layout_plotly(modo, titulo)
    layout["hovermode"] = "x unified"
    layout["xaxis"]["showgrid"] = False
    if cor is not None and rotulo_direto:
        layout["margin"]["r"] = 110
    fig.update_layout(**layout)
    return fig


def barras_empilhadas(
    df: pd.DataFrame,
    x: str,
    y: str,
    cor: str,
    titulo: str = "",
    modo: str = "claro",
) -> go.Figure:
    """Composição percentual — ex.: estrutura setorial do PIB por UF.

    Os segmentos levam um anel de 2px na cor da superfície: é o espaçador que
    impede duas faixas adjacentes de se fundirem numa só massa.
    """
    p = paleta(modo)
    fig = go.Figure()
    for i, categoria in enumerate(df[cor].unique()):
        sub = df[df[cor] == categoria]
        fig.add_trace(
            go.Bar(
                x=sub[y], y=sub[x], name=str(categoria), orientation="h",
                marker={
                    "color": cores_series(modo)[i % 8],
                    "line": {"width": 2, "color": p["superficie"]},
                },
                hovertemplate=f"<b>{categoria}</b><br>%{{y}}: %{{x:.1f}}%<extra></extra>",
            )
        )
    layout = layout_plotly(modo, titulo, altura=max(360, 20 * df[x].nunique() + 120))
    layout["yaxis"]["showgrid"] = False
    fig.update_layout(**layout, barmode="stack", bargap=0.3)
    return fig


def dispersao_facetada(
    df: pd.DataFrame,
    x: str,
    y: str,
    faceta: str = "regiao_nome",
    hover: str = "municipio_nome",
    titulo: str = "",
    modo: str = "claro",
    log_x: bool = True,
    log_y: bool = True,
) -> go.Figure:
    """Dispersão em pequenos múltiplos, uma faceta por região.

    Facetado em vez de colorido de propósito: numa dispersão todos os pares de
    cores concorrem entre si, e a paleta só garante separação para três séries
    simultâneas. Cinco regiões em cinco painéis resolvem isso sem perder
    nenhuma delas — e cada painel ainda mostra a nuvem completa em cinza como
    referência de fundo.
    """
    p = paleta(modo)
    regioes = [r for r in ORDEM_REGIOES if r in df[faceta].unique()]
    fig = make_subplots(
        rows=1, cols=len(regioes), shared_yaxes=True, subplot_titles=regioes,
        horizontal_spacing=0.012,
    )

    for i, regiao in enumerate(regioes, start=1):
        sub = df[df[faceta] == regiao]
        # Nuvem de referência: todos os municípios, recessiva.
        fig.add_trace(
            go.Scattergl(
                x=df[x], y=df[y], mode="markers", showlegend=False, hoverinfo="skip",
                marker={"size": 3, "color": p["grade"], "opacity": 0.5},
            ),
            row=1, col=i,
        )
        fig.add_trace(
            go.Scattergl(
                x=sub[x], y=sub[y], mode="markers", name=regiao, showlegend=False,
                text=sub[hover],
                marker={
                    "size": 5,
                    "color": CORES_REGIAO[regiao],
                    "line": {"width": 1, "color": p["superficie"]},
                },
                hovertemplate="<b>%{text}</b><br>" + f"{x}: %{{x:,.1f}}<br>{y}: %{{y:,.1f}}<extra></extra>",
            ),
            row=1, col=i,
        )

    layout = layout_plotly(modo, titulo, altura=380)
    layout.pop("xaxis"); layout.pop("yaxis")
    fig.update_layout(**layout, showlegend=False)
    fig.update_xaxes(
        type="log" if log_x else "linear", gridcolor=p["grade"],
        linecolor=p["eixo"], tickfont={"color": p["tinta_suave"], "size": 11},
    )
    fig.update_yaxes(
        type="log" if log_y else "linear", gridcolor=p["grade"],
        linecolor=p["eixo"], tickfont={"color": p["tinta_suave"], "size": 11},
    )
    for anotacao in fig.layout.annotations:
        anotacao.font.update(size=12, color=p["tinta_secundaria"])
    return fig


def histograma(
    df: pd.DataFrame, coluna: str, titulo: str = "", modo: str = "claro", nbins: int = 50,
    log_x: bool = False,
) -> go.Figure:
    """Distribuição de uma variável contínua."""
    p = paleta(modo)
    serie = df[coluna].dropna()
    if log_x:
        serie = serie[serie > 0]
    fig = go.Figure(
        go.Histogram(
            x=serie, nbinsx=nbins,
            marker={"color": cores_series(modo)[0], "line": {"width": 0}},
            hovertemplate="%{x}<br>%{y} municípios<extra></extra>",
        )
    )
    layout = layout_plotly(modo, titulo)
    layout["xaxis"]["showgrid"] = False
    if log_x:
        layout["xaxis"]["type"] = "log"
    fig.update_layout(**layout, bargap=0.02)
    return fig


def lorenz(pontos: pd.DataFrame, titulo: str = "", modo: str = "claro") -> go.Figure:
    """Curva de Lorenz com a linha de igualdade perfeita como referência."""
    p = paleta(modo)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[0, 100], y=[0, 100], mode="lines", name="Igualdade perfeita",
            line={"width": 2, "color": p["eixo"], "dash": "dot"},
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=pontos["pct_municipios"], y=pontos["pct_populacao"], mode="lines",
            name="Distribuição observada",
            line={"width": 2, "color": cores_series(modo)[0]},
            fill="tonexty", fillcolor="rgba(42,120,214,0.10)",
            hovertemplate="%{x:.0f}% dos municípios<br>%{y:.1f}% do total<extra></extra>",
        )
    )
    layout = layout_plotly(modo, titulo)
    layout["xaxis"]["title"] = {"text": "% dos municípios (do menor ao maior)"}
    layout["yaxis"]["title"] = {"text": "% acumulado"}
    fig.update_layout(**layout)
    return fig


def barras_agrupadas_comparacao(
    df: pd.DataFrame,
    categoria: str,
    series: dict[str, str],
    titulo: str = "",
    modo: str = "claro",
) -> go.Figure:
    """Barras agrupadas para comparar duas grandezas já na mesma escala (%).

    Só é válido porque ambas as séries são percentuais do mesmo total — daí um
    eixo só. Grandezas de escalas diferentes nunca compartilham eixo aqui.
    """
    p = paleta(modo)
    fig = go.Figure()
    for i, (coluna, rotulo) in enumerate(series.items()):
        fig.add_trace(
            go.Bar(
                x=df[categoria], y=df[coluna], name=rotulo,
                marker={
                    "color": cores_series(modo)[i],
                    "line": {"width": 2, "color": p["superficie"]},
                },
                text=[f"{v:.1f}%" for v in df[coluna]],
                textposition="outside",
                textfont={"color": p["tinta_secundaria"], "size": 11},
                hovertemplate=f"<b>%{{x}}</b><br>{rotulo}: %{{y:.1f}}%<extra></extra>",
                cliponaxis=False,
            )
        )
    layout = layout_plotly(modo, titulo)
    layout["xaxis"]["showgrid"] = False
    fig.update_layout(**layout, barmode="group", bargap=0.28, bargroupgap=0.08)
    fig.update_traces(marker_cornerradius=RAIO_BARRA)
    return fig
