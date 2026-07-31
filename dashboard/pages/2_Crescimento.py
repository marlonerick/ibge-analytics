"""Crescimento populacional: quem cresce, quem encolhe e em que ritmo."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ibge_analytics.analysis import crescimento  # noqa: E402
from ibge_analytics.utils import io  # noqa: E402
from ibge_analytics.viz import charts  # noqa: E402
from ibge_analytics.viz.theme import formatar_compacto, formatar_numero  # noqa: E402

st.set_page_config(page_title="Crescimento — IBGE", page_icon="📈", layout="wide")
st.title("Crescimento populacional")

cresc = io.carregar("crescimento_municipios")
ano_ini, ano_fim = int(cresc["ano_inicial"].min()), int(cresc["ano_final"].max())
st.caption(
    f"Taxa média de crescimento anual composta (CAGR) entre {ano_ini} e {ano_fim}. "
    "O CAGR é usado no lugar da variação simples porque compara ritmos, não saltos."
)

f1, f2 = st.columns([3, 1])
regioes = f1.multiselect(
    "Regiões", sorted(cresc["regiao_nome"].dropna().unique()), default=[]
)
pop_min = f2.number_input(
    "População mínima", min_value=0, value=20_000, step=5_000,
    help="Filtra municípios pequenos, cujo CAGR oscila muito por efeito de base.",
)

filtrado = cresc[cresc["regiao_nome"].isin(regioes)] if regioes else cresc

resumo = crescimento.resumo_declinio(filtrado)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Municípios analisados", formatar_numero(resumo["total_municipios"]))
c2.metric("Perdendo população", formatar_numero(resumo["n_perdendo"]),
          f"{resumo['pct_perdendo']:.1f}% do total", delta_color="inverse")
c3.metric("População perdida", formatar_compacto(resumo["populacao_perdida"]),
          "soma dos que encolheram", delta_color="off")
c4.metric("CAGR mediano", f"{resumo['cagr_mediano']:.2f}% a.a.")

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader(f"Maior crescimento")
    top = crescimento.top_crescimento(filtrado, n=15, populacao_minima=pop_min)
    top["rotulo"] = top["municipio_nome"] + " (" + top["uf_sigla"] + ")"
    st.plotly_chart(
        charts.barras_ranking(
            top, x="cagr_pct", y="rotulo", rotulo_valor="CAGR",
            sufixo="% a.a.", casas=2,
        ),
        use_container_width=True,
    )

with col2:
    st.subheader("Maior retração")
    baixo = crescimento.top_declinio(filtrado, n=15, populacao_minima=pop_min)
    baixo["rotulo"] = baixo["municipio_nome"] + " (" + baixo["uf_sigla"] + ")"
    st.plotly_chart(
        charts.barras_ranking(
            baixo, x="cagr_pct", y="rotulo", rotulo_valor="CAGR",
            sufixo="% a.a.", casas=2,
        ),
        use_container_width=True,
    )

st.caption(
    f"Ambos os rankings consideram apenas municípios com pelo menos "
    f"{formatar_numero(pop_min)} habitantes no fim da série."
)

st.divider()

col3, col4 = st.columns([1, 1])

with col3:
    st.subheader("Distribuição do ritmo")
    faixas = crescimento.distribuicao_faixas(filtrado)
    st.plotly_chart(
        charts.barras_ranking(
            faixas, x="n_municipios", y="faixa_crescimento",
            rotulo_valor="Municípios", cor_por_regiao=False,
            titulo="Municípios por faixa de crescimento",
        ),
        use_container_width=True,
    )

with col4:
    st.subheader("Panorama por região")
    por_regiao = crescimento.crescimento_por_regiao(filtrado)
    st.dataframe(
        por_regiao.assign(
            **{
                "Região": por_regiao["regiao_nome"],
                "Municípios": por_regiao["n_municipios"],
                "% encolhendo": por_regiao["pct_perdendo"].map(lambda v: f"{v:.1f}%"),
                "CAGR mediano": por_regiao["cagr_mediano"].map(lambda v: f"{v:.2f}%"),
                "Crescimento total": por_regiao["crescimento_regional_pct"].map(
                    lambda v: f"{v:+.1f}%"
                ),
            }
        )[["Região", "Municípios", "% encolhendo", "CAGR mediano", "Crescimento total"]],
        hide_index=True, use_container_width=True,
    )
    st.caption(
        "«Crescimento total» é a variação da população somada da região no "
        "período — diferente da mediana dos municípios, que dá peso igual a "
        "cada um deles."
    )

st.divider()
st.subheader("Tabela completa")
st.dataframe(
    filtrado[
        ["municipio_nome", "uf_sigla", "regiao_nome", "valor_inicial", "valor_final",
         "variacao_pct", "cagr_pct", "faixa_crescimento"]
    ]
    .sort_values("cagr_pct", ascending=False)
    .rename(
        columns={
            "municipio_nome": "Município", "uf_sigla": "UF", "regiao_nome": "Região",
            "valor_inicial": f"Pop. {ano_ini}", "valor_final": f"Pop. {ano_fim}",
            "variacao_pct": "Variação %", "cagr_pct": "CAGR % a.a.",
            "faixa_crescimento": "Faixa",
        }
    ),
    hide_index=True, use_container_width=True, height=400,
)
