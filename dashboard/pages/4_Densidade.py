"""Densidade demográfica e ocupação do território."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ibge_analytics.analysis import densidade as an_dens  # noqa: E402
from ibge_analytics.utils import io  # noqa: E402
from ibge_analytics.viz import charts  # noqa: E402
from ibge_analytics.viz.theme import formatar_compacto, formatar_numero  # noqa: E402

st.set_page_config(page_title="Densidade — IBGE", page_icon="🗺️", layout="wide")
st.title("Densidade demográfica")
st.caption(
    "Área territorial do Censo 2022 combinada com a estimativa populacional "
    "mais recente."
)

painel = io.carregar("painel_municipios")
painel_reg = io.carregar("painel_regioes")

terr = an_dens.concentracao_territorial(painel)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Densidade nacional",
          formatar_numero(painel["populacao_atual"].sum() / painel["area_km2"].sum(), 1) + " hab/km²")
c2.metric("Metade da população vive em", formatar_numero(terr["n_municipios_metade_pop"]) + " municípios")
c3.metric("Que ocupam", f"{terr['pct_area_metade_pop']:.1f}% do território",
          formatar_compacto(terr["area_metade_pop_km2"]) + " km²")
c4.metric("Município mais denso",
          painel.nlargest(1, "densidade_atual")["municipio_nome"].iloc[0],
          formatar_numero(painel["densidade_atual"].max()) + " hab/km²")

st.divider()

col1, col2 = st.columns([3, 2])

with col1:
    st.subheader("Território x população")
    distrib = an_dens.distribuicao(painel)
    st.plotly_chart(
        charts.barras_agrupadas_comparacao(
            distrib, categoria="faixa_densidade",
            series={"pct_area": "% do território", "pct_populacao": "% da população"},
            titulo="As faixas mais vazias ocupam quase todo o país",
        ),
        use_container_width=True,
    )

with col2:
    st.subheader("Detalhamento")
    st.dataframe(
        distrib.assign(
            **{
                "Faixa (hab/km²)": distrib["faixa_densidade"],
                "Municípios": distrib["n_municipios"],
                "% área": distrib["pct_area"].map(lambda v: f"{v:.1f}%"),
                "% pop.": distrib["pct_populacao"].map(lambda v: f"{v:.1f}%"),
            }
        )[["Faixa (hab/km²)", "Municípios", "% área", "% pop."]],
        hide_index=True, use_container_width=True,
    )

st.divider()

st.subheader("Densidade por região")
reg = an_dens.densidade_por_regiao(painel_reg)
col3, col4 = st.columns([2, 3])
with col3:
    st.plotly_chart(
        charts.barras_ranking(
            reg, x="densidade_atual", y="regiao_nome",
            rotulo_valor="Densidade", sufixo=" hab/km²", casas=1,
        ),
        use_container_width=True,
    )
with col4:
    st.plotly_chart(
        charts.barras_agrupadas_comparacao(
            reg, categoria="regiao_nome",
            series={"part_area_brasil": "% do território", "part_pop_brasil": "% da população"},
            titulo="",
        ),
        use_container_width=True,
    )

st.divider()

st.subheader("Extremos")
extremos = an_dens.extremos(painel, n=12)
t1, t2, t3 = st.tabs(["Mais densos", "Mais vazios", "Maiores áreas"])
COLUNAS = {
    "municipio_nome": "Município", "uf_sigla": "UF", "regiao_nome": "Região",
    "populacao_atual": "População", "area_km2": "Área (km²)",
    "densidade_atual": "Densidade (hab/km²)",
}
for aba, chave in ((t1, "mais_densos"), (t2, "mais_vazios"), (t3, "maiores_areas")):
    with aba:
        aba.dataframe(extremos[chave].rename(columns=COLUNAS), hide_index=True,
                      use_container_width=True)

st.divider()

st.subheader("Distribuição da densidade")
st.caption(
    "Eixo logarítmico: a densidade municipal varia de menos de 0,1 a mais de "
    "10 mil hab/km², e numa escala linear tudo se acumularia numa barra só."
)
st.plotly_chart(
    charts.histograma(
        painel, coluna="densidade_atual", log_x=True, nbins=60,
        titulo="Municípios por densidade (escala log)",
    ),
    use_container_width=True,
)
