"""Mapas coropléticos interativos sobre as malhas do IBGE."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ibge_analytics.utils import io  # noqa: E402
from ibge_analytics.viz import maps  # noqa: E402
from ibge_analytics.viz.theme import formatar_numero  # noqa: E402

st.set_page_config(page_title="Mapas — IBGE", page_icon="🌎", layout="wide")
st.title("Mapas")

painel = io.carregar("painel_municipios")
painel_uf = io.carregar("painel_ufs")

#: (rótulo) -> (coluna, unidade, escala divergente?, escala log?)
INDICADORES = {
    "População": ("populacao_atual", "habitantes", False, True),
    "Densidade demográfica": ("densidade_atual", "hab/km²", False, True),
    "PIB": ("pib_mil_reais", "mil R$", False, True),
    "PIB per capita": ("pib_per_capita", "R$", False, True),
    "Crescimento populacional (CAGR)": ("cagr_pct", "% a.a.", True, False),
    "Área territorial": ("area_km2", "km²", False, True),
}

f1, f2, f3 = st.columns([2, 2, 2])
indicador = f1.selectbox("Indicador", list(INDICADORES))
nivel = f2.radio("Nível", ["Município", "UF"], horizontal=True)
coluna, unidade, divergente, log_padrao = INDICADORES[indicador]

if nivel == "Município":
    ufs_disponiveis = sorted(painel["uf_sigla"].dropna().unique())
    recorte = f3.selectbox("Recorte", ["Brasil inteiro"] + ufs_disponiveis)
else:
    recorte = "Brasil inteiro"
    f3.empty()

escala_log = st.checkbox(
    "Escala logarítmica", value=log_padrao and not divergente, disabled=divergente,
    help="Indicadores territoriais são muito assimétricos; o log espalha a cor "
         "pela faixa onde os dados realmente estão.",
)

if divergente:
    st.caption(
        "Escala divergente azul↔vermelho com cinza no zero: aqui o zero é um "
        "limiar real — municípios que crescem de um lado, que encolhem do outro."
    )
else:
    st.caption(
        "Escala sequencial de um matiz só, do claro ao escuro, proporcional à "
        "magnitude."
    )

if nivel == "Município":
    malha = io.carregar_malha("municipios")
    dados = painel
    if recorte != "Brasil inteiro":
        dados = dados[dados["uf_sigla"] == recorte]
        # Recortar a malha também: mandar 5.570 polígonos ao navegador quando
        # só um estado está em tela trava a renderização.
        malha = maps.filtrar_malha(malha, set(dados["municipio_id"].astype(str)))
    id_col, nome_col = "municipio_id", "municipio_nome"
else:
    malha = io.carregar_malha("ufs")
    dados = painel_uf.assign(uf_id_str=lambda d: d["uf_id"].astype(str))
    id_col, nome_col = "uf_id_str", "uf_nome"

validos = dados[coluna].notna().sum()
st.caption(
    f"{formatar_numero(validos)} áreas com dado · "
    f"mín. {formatar_numero(dados[coluna].min(), 2)} · "
    f"mediana {formatar_numero(dados[coluna].median(), 2)} · "
    f"máx. {formatar_numero(dados[coluna].max(), 2)} {unidade}"
)

st.plotly_chart(
    maps.coropletico_plotly(
        dados, malha, id_col=id_col, valor_col=coluna, nome_col=nome_col,
        titulo=f"{indicador} — {recorte}", rotulo=f"{indicador} ({unidade})",
        divergente=divergente, escala_log=escala_log,
        altura=700 if recorte == "Brasil inteiro" else 620,
    ),
    use_container_width=True,
)

with st.expander("Ver os dados do mapa"):
    exibir = [c for c in [nome_col, "uf_sigla", "regiao_nome", coluna] if c in dados.columns]
    st.dataframe(
        dados[exibir].sort_values(coluna, ascending=False),
        hide_index=True, use_container_width=True, height=380,
    )

st.divider()
st.caption(
    "Malhas da API de Malhas v3 do IBGE, qualidade mínima — o join com os "
    "dados é feito pela propriedade `codarea` de cada feature."
)
