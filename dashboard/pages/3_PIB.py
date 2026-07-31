"""PIB: riqueza, produtividade e estrutura setorial."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ibge_analytics.analysis import pib as an_pib  # noqa: E402
from ibge_analytics.utils import io  # noqa: E402
from ibge_analytics.viz import charts  # noqa: E402
from ibge_analytics.viz.theme import formatar_compacto, formatar_numero  # noqa: E402

st.set_page_config(page_title="PIB — IBGE", page_icon="💰", layout="wide")
st.title("Produto Interno Bruto")

painel = io.carregar("painel_municipios")
painel_uf = io.carregar("painel_ufs")
pib_ufs = io.carregar("pib_ufs")

ano_pib = int(painel["ano_pib"].iloc[0])
ano_pop_pib = int(painel["ano_populacao_pib"].iloc[0])
st.caption(
    f"PIB a preços correntes de {ano_pib} (agregado 5938). O PIB per capita usa "
    f"a população de {ano_pop_pib}, o ano publicado mais próximo — a série de "
    "estimativas não cobre 2022 nem 2023."
)

conc = an_pib.resumo_concentracao_municipal(painel)
c1, c2, c3, c4 = st.columns(4)
c1.metric("PIB nacional", "R$ " + formatar_compacto(painel["pib_mil_reais"].sum() * 1_000))
c2.metric("PIB per capita", "R$ " + formatar_numero(
    painel["pib_mil_reais"].sum() * 1_000 / painel["populacao_ano_pib"].sum()))
c3.metric("Municípios = metade do PIB", formatar_numero(conc["n_municipios_metade_pib"]),
          f"{conc['pct_municipios_metade_pib']:.1f}% dos municípios")
c4.metric("Gini do PIB municipal", f"{conc['gini']:.3f}")

st.divider()

tab1, tab2, tab3 = st.tabs(["Por UF", "Estrutura setorial", "Municípios"])

with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("PIB por UF")
        ranking = an_pib.ranking_ufs(painel_uf)
        st.plotly_chart(
            charts.barras_ranking(
                ranking, x="pib_mil_reais", y="uf_sigla",
                rotulo_valor="PIB (mil R$)", titulo="",
            ),
            use_container_width=True,
        )
    with col2:
        st.subheader("PIB per capita por UF")
        st.plotly_chart(
            charts.barras_ranking(
                painel_uf, x="pib_per_capita", y="uf_sigla",
                rotulo_valor="PIB per capita", titulo="",
            ),
            use_container_width=True,
        )

    st.subheader("Riqueza x população")
    st.caption(
        "As duas séries são percentuais do mesmo total nacional, então dividem "
        "um eixo. Onde a barra do PIB supera a da população, a UF concentra "
        "mais riqueza do que gente."
    )
    desc = an_pib.descolamento_pib_populacao(painel_uf)
    st.plotly_chart(
        charts.barras_agrupadas_comparacao(
            desc, categoria="uf_sigla",
            series={"part_pib_brasil": "% do PIB", "part_pop_brasil": "% da população"},
        ),
        use_container_width=True,
    )
    st.dataframe(
        desc.assign(
            **{
                "UF": desc["uf_nome"], "Região": desc["regiao_nome"],
                "% do PIB": desc["part_pib_brasil"].map(lambda v: f"{v:.2f}%"),
                "% da pop.": desc["part_pop_brasil"].map(lambda v: f"{v:.2f}%"),
                "Razão PIB/pop.": desc["razao_pib_pop"].map(lambda v: f"{v:.2f}"),
                "PIB per capita": desc["pib_per_capita"].map(
                    lambda v: "R$ " + formatar_numero(v)),
            }
        )[["UF", "Região", "% do PIB", "% da pop.", "Razão PIB/pop.", "PIB per capita"]],
        hide_index=True, use_container_width=True,
    )

with tab2:
    st.subheader("Composição do valor adicionado por UF")
    estrutura = an_pib.estrutura_setorial(painel_uf, chave="uf_sigla")
    st.plotly_chart(
        charts.barras_empilhadas(
            estrutura, x="uf_sigla", y="participacao", cor="setor",
            titulo="Participação de cada setor no valor adicionado bruto (%)",
        ),
        use_container_width=True,
    )
    st.caption(
        "Serviços exclui administração, defesa, educação e saúde públicas, que "
        "aparecem em sua própria categoria — é a desagregação publicada pelo IBGE."
    )

    st.subheader("Evolução da participação regional no PIB")
    evolucao = an_pib.evolucao_participacao_regional(pib_ufs)
    st.plotly_chart(
        charts.linha_temporal(
            evolucao, x="ano", y="part_pib_brasil", cor="regiao_nome",
            titulo="Participação de cada região no PIB nacional (%)",
        ),
        use_container_width=True,
    )

with tab3:
    st.subheader("Maiores PIBs municipais")
    top = an_pib.top_municipios_pib(painel, n=20)
    top["rotulo"] = top["municipio_nome"] + " (" + top["uf_sigla"] + ")"
    st.plotly_chart(
        charts.barras_ranking(top, x="pib_mil_reais", y="rotulo", rotulo_valor="PIB (mil R$)"),
        use_container_width=True,
    )

    st.subheader("Riqueza x tamanho")
    st.caption(
        "Um painel por região, em vez de cinco cores num gráfico só: numa "
        "dispersão todos os pares de cor competem entre si, e cinco séries "
        "sobrepostas deixariam de ser distinguíveis. A nuvem cinza ao fundo é "
        "o país inteiro, para comparação."
    )
    st.plotly_chart(
        charts.dispersao_facetada(
            painel.dropna(subset=["pib_per_capita", "populacao_atual"]),
            x="populacao_atual", y="pib_per_capita",
            titulo="População (log) x PIB per capita (log)",
        ),
        use_container_width=True,
    )
