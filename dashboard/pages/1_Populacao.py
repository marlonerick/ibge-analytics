"""População: rankings, porte municipal e concentração."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ibge_analytics.analysis import populacao  # noqa: E402
from ibge_analytics.utils import io  # noqa: E402
from ibge_analytics.viz import charts  # noqa: E402
from ibge_analytics.viz.theme import formatar_compacto, formatar_numero  # noqa: E402

st.set_page_config(page_title="População — IBGE", page_icon="👥", layout="wide")
st.title("População")

painel = io.carregar("painel_municipios")
pop_ufs = io.carregar("populacao_ufs")
ano = int(painel["ano_populacao"].iloc[0])

# Filtros numa linha só, acima dos gráficos.
f1, f2, f3 = st.columns([2, 2, 1])
regioes = f1.multiselect(
    "Regiões", sorted(painel["regiao_nome"].dropna().unique()), default=[]
)
ufs = f2.multiselect("UFs", sorted(painel["uf_sigla"].dropna().unique()), default=[])
n_top = f3.slider("Tamanho do ranking", 5, 40, 15, step=5)

filtrado = painel
if regioes:
    filtrado = filtrado[filtrado["regiao_nome"].isin(regioes)]
if ufs:
    filtrado = filtrado[filtrado["uf_sigla"].isin(ufs)]

st.caption(
    f"{formatar_numero(len(filtrado))} municípios · "
    f"{formatar_compacto(filtrado['populacao_atual'].sum())} habitantes "
    f"({filtrado['populacao_atual'].sum() / painel['populacao_atual'].sum() * 100:.1f}% do país) · "
    f"estimativa {ano}"
)

st.subheader(f"Os {n_top} municípios mais populosos")
ranking = populacao.ranking_municipios(filtrado, n=n_top)
ranking["rotulo"] = ranking["municipio_nome"] + " (" + ranking["uf_sigla"] + ")"
st.plotly_chart(
    charts.barras_ranking(
        ranking, x="populacao_atual", y="rotulo",
        rotulo_valor="População", titulo="",
    ),
    use_container_width=True,
)
with st.expander("Ver como tabela"):
    st.dataframe(
        ranking[["municipio_nome", "uf_sigla", "regiao_nome", "populacao_atual"]].rename(
            columns={
                "municipio_nome": "Município", "uf_sigla": "UF",
                "regiao_nome": "Região", "populacao_atual": "População",
            }
        ),
        hide_index=True, use_container_width=True,
    )

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Porte dos municípios")
    porte = populacao.distribuicao_por_porte(filtrado)
    st.plotly_chart(
        charts.barras_agrupadas_comparacao(
            porte, categoria="porte",
            series={
                "pct_municipios": "% dos municípios",
                "pct_populacao": "% da população",
            },
            titulo="Municípios pequenos são muitos, mas concentram pouca gente",
        ),
        use_container_width=True,
    )
    st.dataframe(
        porte.assign(
            **{
                "Faixa": porte["porte"],
                "Municípios": porte["n_municipios"],
                "População": porte["populacao"].map(formatar_compacto),
                "% mun.": porte["pct_municipios"].map(lambda v: f"{v:.1f}%"),
                "% pop.": porte["pct_populacao"].map(lambda v: f"{v:.1f}%"),
            }
        )[["Faixa", "Municípios", "População", "% mun.", "% pop."]],
        hide_index=True, use_container_width=True,
    )

with col2:
    st.subheader("Concentração populacional")
    metricas = populacao.metricas_concentracao(filtrado)
    m1, m2, m3 = st.columns(3)
    m1.metric("Índice de Gini", f"{metricas['gini']:.3f}")
    m2.metric("10% maiores", f"{metricas['share_top_10pct']:.0f}%", help="da população total")
    m3.metric("100 maiores", f"{metricas['share_top_100']:.0f}%", help="da população total")
    st.plotly_chart(
        charts.lorenz(
            populacao.curva_lorenz(filtrado),
            titulo="Curva de Lorenz da população municipal",
        ),
        use_container_width=True,
    )

st.divider()

st.subheader("Trajetória por UF")
st.caption(
    "Séries indexadas a 100 no primeiro ano — permite comparar estados de "
    "tamanhos muito diferentes num eixo só."
)
serie_uf = pop_ufs.copy()
if regioes:
    serie_uf = serie_uf[serie_uf["regiao_nome"].isin(regioes)]
if ufs:
    serie_uf = serie_uf[serie_uf["uf_sigla"].isin(ufs)]

por_regiao = (
    serie_uf.groupby(["ano", "regiao_nome"], observed=True, as_index=False)["populacao"].sum()
)
base = por_regiao[por_regiao["ano"] == por_regiao["ano"].min()].set_index("regiao_nome")["populacao"]
por_regiao["indice"] = por_regiao["populacao"] / por_regiao["regiao_nome"].map(base) * 100

st.plotly_chart(
    charts.linha_temporal(
        por_regiao, x="ano", y="indice", cor="regiao_nome",
        titulo=f"População por região (base 100 = {int(por_regiao['ano'].min())})",
    ),
    use_container_width=True,
)
st.caption(
    "A série de população estimada não cobre 2007, 2010, 2022 e 2023 — anos de "
    "Censo/Contagem ou de estimativa suspensa para revisão."
)
