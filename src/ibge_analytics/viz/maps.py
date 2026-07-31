"""Mapas coropléticos sobre as malhas GeoJSON do IBGE.

Duas implementações, por finalidade distinta:
  - `coropletico_plotly`: integra ao dashboard, compartilha o tema dos gráficos;
  - `coropletico_folium`: mapa com tiles navegáveis, melhor para exportar HTML
    autocontido nos relatórios.

Regra de cor: magnitude contínua usa a rampa sequencial de um matiz só;
crescimento populacional usa a divergente azul↔vermelho, porque o zero é um
limiar real (crescer vs. encolher) e não um ponto qualquer da escala.
"""

from __future__ import annotations

import folium
import pandas as pd
import plotly.graph_objects as go

from .theme import DIVERGENTE, SEQUENCIAL_AZUL, formatar_numero, layout_plotly, paleta


def _escala_plotly(cores: list[str]) -> list[list]:
    n = len(cores) - 1
    return [[i / n, cor] for i, cor in enumerate(cores)]


# --------------------------------------------------------------------------- #
# Orientação dos polígonos
# --------------------------------------------------------------------------- #

def _area_assinada(anel: list) -> float:
    """Área assinada pelo método do shoelace. Positiva = sentido horário."""
    return sum(
        (x2 - x1) * (y2 + y1)
        for (x1, y1), (x2, y2) in zip(anel, anel[1:])
    )


def _corrigir_anel(anel: list, horario: bool) -> list:
    """Força o anel a ter a orientação pedida."""
    if not anel or len(anel) < 4:
        return anel
    esta_horario = _area_assinada([(p[0], p[1]) for p in anel]) > 0
    return anel if esta_horario == horario else anel[::-1]


def _corrigir_poligono(coordenadas: list) -> list:
    """Anel externo horário, buracos anti-horários (convenção esférica do d3)."""
    if not coordenadas:
        return coordenadas
    return [
        _corrigir_anel(anel, horario=(i == 0)) for i, anel in enumerate(coordenadas)
    ]


def reorientar_malha(geojson: dict) -> dict:
    """Reorienta os polígonos para a convenção esférica que o Plotly espera.

    As malhas do IBGE vêm com o anel externo em sentido anti-horário, que é o
    que o RFC 7946 pede. Mas o Plotly renderiza com d3-geo, que usa winding
    *esférico*: ali o anel externo precisa ser horário, e um anel anti-horário
    é lido como o complemento do polígono — a projeção inteira sai pintada, com
    o formato do estado vazado nela, em vez do estado preenchido.

    Invertemos o sentido na carga. O Leaflet (Folium) ignora a orientação, então
    a mesma malha serve aos dois renderizadores.
    """
    for feature in geojson.get("features", []):
        geometria = feature.get("geometry") or {}
        tipo = geometria.get("type")
        if tipo == "Polygon":
            geometria["coordinates"] = _corrigir_poligono(geometria["coordinates"])
        elif tipo == "MultiPolygon":
            geometria["coordinates"] = [
                _corrigir_poligono(p) for p in geometria["coordinates"]
            ]
    return geojson


def _quantis(serie: pd.Series, n: int = 7) -> list[float]:
    """Cortes por quantil.

    Indicadores territoriais brasileiros são extremamente assimétricos —
    densidade vai de 0,01 a 13.000 hab/km². Uma escala linear pintaria o país
    inteiro da cor mais clara; os quantis distribuem a variação onde os dados
    de fato estão.
    """
    validos = serie.dropna()
    return sorted(set(validos.quantile([i / n for i in range(n + 1)]).tolist()))


def coropletico_plotly(
    dados: pd.DataFrame,
    geojson: dict,
    id_col: str,
    valor_col: str,
    nome_col: str,
    titulo: str = "",
    rotulo: str = "",
    modo: str = "claro",
    divergente: bool = False,
    escala_log: bool = False,
    altura: int = 620,
) -> go.Figure:
    """Coroplético Plotly casado com a malha do IBGE pela propriedade `codarea`."""
    p = paleta(modo)
    df = dados.dropna(subset=[valor_col]).copy()
    df[id_col] = df[id_col].astype(str)

    cores = DIVERGENTE[::-1] if divergente else SEQUENCIAL_AZUL

    if escala_log:
        # Colorir pelo log e rotular pelo valor real: preserva a leitura do
        # número original sem deixar a cauda longa achatar a escala.
        import numpy as np

        z = np.log10(df[valor_col].clip(lower=df[valor_col][df[valor_col] > 0].min()))
        rotulo_barra = f"{rotulo} (log₁₀)"
    else:
        z = df[valor_col]
        rotulo_barra = rotulo

    ponto_medio = 0 if divergente and not escala_log else None

    fig = go.Figure(
        go.Choropleth(
            geojson=geojson,
            locations=df[id_col],
            z=z,
            featureidkey="properties.codarea",
            colorscale=_escala_plotly(cores),
            zmid=ponto_medio,
            marker={"line": {"width": 0.3, "color": p["superficie"]}},
            customdata=df[[nome_col, valor_col]].values,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>" + f"{rotulo}: " + "%{customdata[1]:,.2f}<extra></extra>"
            ),
            colorbar={
                "title": {"text": rotulo_barra, "font": {"size": 12, "color": p["tinta_secundaria"]}},
                "thickness": 12,
                "len": 0.55,
                "outlinewidth": 0,
                "tickfont": {"color": p["tinta_suave"], "size": 11},
            },
        )
    )
    layout = layout_plotly(modo, titulo, altura=altura)
    layout.pop("xaxis"); layout.pop("yaxis")
    fig.update_layout(
        **layout,
        geo={
            "visible": False,
            "fitbounds": "locations",
            "bgcolor": p["superficie"],
            "projection": {"type": "mercator"},
        },
    )
    return fig


def coropletico_folium(
    dados: pd.DataFrame,
    geojson: dict,
    id_col: str,
    valor_col: str,
    nome_col: str,
    rotulo: str = "",
    divergente: bool = False,
    tiles: str = "cartodbpositron",
) -> folium.Map:
    """Mapa Folium navegável, com tooltip por área e classes por quantil."""
    df = dados.dropna(subset=[valor_col]).copy()
    df[id_col] = df[id_col].astype(str)

    mapa = folium.Map(location=[-14.5, -52.0], zoom_start=4, tiles=tiles, control_scale=True)

    cores = "RdBu" if divergente else "Blues"
    folium.Choropleth(
        geo_data=geojson,
        data=df,
        columns=[id_col, valor_col],
        key_on="feature.properties.codarea",
        fill_color=cores,
        fill_opacity=0.85,
        line_opacity=0.25,
        line_weight=0.4,
        nan_fill_color="#f0efec",
        nan_fill_opacity=0.4,
        legend_name=rotulo,
        bins=_quantis(df[valor_col]),
        highlight=True,
        name=rotulo,
    ).add_to(mapa)

    # Camada transparente só para o tooltip — o Choropleth não carrega os
    # atributos originais nas suas features.
    consulta = df.set_index(id_col)[[nome_col, valor_col]].to_dict("index")
    for feature in geojson["features"]:
        feature["properties"]["_nome"] = consulta.get(
            feature["properties"]["codarea"], {}
        ).get(nome_col, "—")
        valor = consulta.get(feature["properties"]["codarea"], {}).get(valor_col)
        feature["properties"]["_valor"] = formatar_numero(valor, 2) if valor is not None else "—"

    folium.GeoJson(
        geojson,
        style_function=lambda _: {"fillOpacity": 0, "weight": 0},
        tooltip=folium.GeoJsonTooltip(
            fields=["_nome", "_valor"],
            aliases=["", f"{rotulo}:"],
            sticky=True,
            style=(
                "background-color:#fcfcfb;border:1px solid #c3c2b7;border-radius:4px;"
                'padding:6px;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:12px;'
            ),
        ),
        name="Detalhes",
    ).add_to(mapa)

    folium.LayerControl(collapsed=True).add_to(mapa)
    return mapa


def filtrar_malha(geojson: dict, codigos: set[str]) -> dict:
    """Recorta a malha para um subconjunto de áreas.

    O GeoJSON municipal nacional tem 5.570 polígonos (~3,6 MB); enviar tudo ao
    navegador quando o usuário filtrou uma UF trava a renderização.
    """
    return {
        "type": "FeatureCollection",
        "features": [
            f for f in geojson["features"] if str(f["properties"]["codarea"]) in codigos
        ],
    }
