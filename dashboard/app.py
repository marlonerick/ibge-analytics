"""Dashboard IBGE — página inicial.

Executar a partir da raiz do projeto:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ibge_analytics.utils import io  # noqa: E402
from ibge_analytics.viz.theme import formatar_compacto, formatar_numero  # noqa: E402

st.set_page_config(
    page_title="Brasil em números — IBGE",
    page_icon="🇧🇷",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
  .bloco-metrica { border:1px solid rgba(11,11,11,.10); border-radius:10px;
                   padding:16px 18px; background:#fcfcfb; height:100%; }
  .bloco-metrica .rotulo { font-size:12px; color:#52514e; letter-spacing:.02em;
                           text-transform:uppercase; margin-bottom:6px; }
  .bloco-metrica .valor  { font-size:30px; color:#0b0b0b; line-height:1.1; font-weight:600; }
  .bloco-metrica .nota   { font-size:12px; color:#898781; margin-top:6px; }
  @media (prefers-color-scheme: dark) {
    .bloco-metrica { background:#1a1a19; border-color:rgba(255,255,255,.10); }
    .bloco-metrica .valor { color:#fff; } .bloco-metrica .rotulo { color:#c3c2b7; }
  }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def metrica(coluna, rotulo: str, valor: str, nota: str = "") -> None:
    coluna.markdown(
        f'<div class="bloco-metrica"><div class="rotulo">{rotulo}</div>'
        f'<div class="valor">{valor}</div><div class="nota">{nota}</div></div>',
        unsafe_allow_html=True,
    )


st.title("Brasil em números")
st.caption(
    "Análise territorial a partir das APIs públicas do IBGE — "
    "SIDRA v3 (agregados), Localidades v1 e Malhas v3."
)

if not io.dados_disponiveis():
    st.error(
        "Os dados processados ainda não existem. Rode o pipeline primeiro:\n\n"
        "```bash\npython -m ibge_analytics.etl.pipeline\n```"
    )
    st.stop()

painel = io.carregar("painel_municipios")
painel_uf = io.carregar("painel_ufs")
painel_reg = io.carregar("painel_regioes")

ano_pop = int(painel["ano_populacao"].iloc[0])
ano_pib = int(painel["ano_pib"].iloc[0])

st.subheader(f"Retrato do país")

c1, c2, c3, c4 = st.columns(4)
metrica(c1, "População", formatar_compacto(painel["populacao_atual"].sum()),
        f"estimativa {ano_pop}")
metrica(c2, "Municípios", formatar_numero(len(painel)), "todos os níveis territoriais")
metrica(c3, "PIB", "R$ " + formatar_compacto(painel["pib_mil_reais"].sum() * 1_000),
        f"preços correntes de {ano_pib}")
metrica(c4, "Área", formatar_compacto(painel["area_km2"].sum()) + " km²",
        "Censo 2022")

c5, c6, c7, c8 = st.columns(4)
densidade_br = painel["populacao_atual"].sum() / painel["area_km2"].sum()
pib_pc = painel["pib_mil_reais"].sum() * 1_000 / painel["populacao_ano_pib"].sum()
perdendo = (painel["variacao_absoluta"] < 0).sum()
metrica(c5, "Densidade", formatar_numero(densidade_br, 1) + " hab/km²", "média nacional")
metrica(c6, "PIB per capita", "R$ " + formatar_numero(pib_pc), f"PIB {ano_pib}")
metrica(c7, "Municípios encolhendo", formatar_numero(perdendo),
        f"{perdendo / len(painel) * 100:.0f}% do total")
metrica(c8, "Maior município", painel.nlargest(1, "populacao_atual")["municipio_nome"].iloc[0],
        formatar_compacto(painel["populacao_atual"].max()) + " habitantes")

st.divider()

col_esq, col_dir = st.columns([3, 2])

with col_esq:
    st.subheader("As cinco regiões")
    tabela_reg = painel_reg.assign(
        População=lambda d: d["populacao_atual"].map(formatar_compacto),
        **{
            "Área (km²)": lambda d: d["area_km2"].map(formatar_compacto),
            "Densidade": lambda d: d["densidade_atual"].map(lambda v: formatar_numero(v, 1)),
            "% do PIB": lambda d: d["part_pib_brasil"].map(lambda v: f"{v:.1f}%"),
            "% da população": lambda d: d["part_pop_brasil"].map(lambda v: f"{v:.1f}%"),
            "PIB per capita": lambda d: d["pib_per_capita"].map(
                lambda v: "R$ " + formatar_numero(v)
            ),
        },
    )[
        ["regiao_nome", "População", "Área (km²)", "Densidade", "% da população",
         "% do PIB", "PIB per capita"]
    ].rename(columns={"regiao_nome": "Região"})
    st.dataframe(tabela_reg, hide_index=True, use_container_width=True)

with col_dir:
    st.subheader("Como navegar")
    st.markdown(
        """
        - **População** — rankings, porte municipal e concentração
        - **Crescimento** — quem cresce, quem encolhe e em que ritmo
        - **PIB** — riqueza, produtividade e estrutura setorial
        - **Densidade** — como o território é ocupado
        - **Mapas** — coropléticos interativos por município e UF

        Cada página traz os gráficos e a tabela correspondente, para que
        nenhuma leitura dependa apenas da cor.
        """
    )

st.divider()

with st.expander("Datasets gerados pelo pipeline"):
    st.dataframe(io.resumo_datasets(), hide_index=True, use_container_width=True)
    st.caption(
        f"Fontes: agregados 6579 (população estimada), 4714 (Censo 2022) e "
        f"5938 (PIB municipal). População {ano_pop}; PIB {ano_pib}; área e "
        "densidade do Censo 2022."
    )
