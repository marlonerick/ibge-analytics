"""Gera os notebooks de análise a partir de uma definição única.

Manter os notebooks como código gerado — em vez de .ipynb editados à mão — evita
o problema clássico de notebook em repositório: diffs ilegíveis, saídas
commitadas e células fora de ordem. O conteúdo analítico vive aqui; o .ipynb é
artefato.

Uso:
    python scripts/build_notebooks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat as nbf

RAIZ = Path(__file__).resolve().parents[1]
NOTEBOOKS = RAIZ / "notebooks"

PREAMBULO = """\
import sys, warnings
from pathlib import Path

sys.path.insert(0, str(Path.cwd().parent / "src"))
warnings.filterwarnings("ignore")

import pandas as pd
from ibge_analytics.utils import io
from ibge_analytics.viz import charts, maps
from ibge_analytics.viz.theme import formatar_compacto, formatar_numero

pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
"""


def md(texto: str) -> nbf.NotebookNode:
    return nbf.v4.new_markdown_cell(texto)


def code(fonte: str) -> nbf.NotebookNode:
    return nbf.v4.new_code_cell(fonte.strip())


# --------------------------------------------------------------------------- #
# Definição dos notebooks
# --------------------------------------------------------------------------- #

def nb_populacao() -> list:
    return [
        md(
            "# 01 · População\n\n"
            "Quantas pessoas vivem onde, e o quão desigual é essa distribuição.\n\n"
            "**Fonte:** agregado 6579 (população residente estimada) e 4714 "
            "(Censo 2022), via API de Agregados v3 do IBGE."
        ),
        code(PREAMBULO),
        code(
            'painel = io.carregar("painel_municipios")\n'
            'pop_ufs = io.carregar("populacao_ufs")\n'
            'ano = int(painel["ano_populacao"].iloc[0])\n'
            'print(f"{len(painel):,} municípios · estimativa {ano}")\n'
            'print(f"População do Brasil: {painel[\'populacao_atual\'].sum():,.0f}")'
        ),
        md("## Os maiores municípios"),
        code(
            "from ibge_analytics.analysis import populacao\n\n"
            "ranking = populacao.ranking_municipios(painel, n=15)\n"
            'ranking["rotulo"] = ranking["municipio_nome"] + " (" + ranking["uf_sigla"] + ")"\n'
            'charts.barras_ranking(ranking, x="populacao_atual", y="rotulo",\n'
            '                      rotulo_valor="População",\n'
            '                      titulo=f"Municípios mais populosos ({ano})")'
        ),
        md(
            "## Porte municipal\n\n"
            "O contraste central da rede urbana brasileira: a maior parte dos "
            "municípios é pequena, e a maior parte da população não vive neles."
        ),
        code(
            "porte = populacao.distribuicao_por_porte(painel)\n"
            "display(porte)\n"
            'charts.barras_agrupadas_comparacao(\n'
            '    porte, categoria="porte",\n'
            '    series={"pct_municipios": "% dos municípios", "pct_populacao": "% da população"},\n'
            '    titulo="Muitos municípios pequenos, pouca gente neles")'
        ),
        md("## Concentração"),
        code(
            "metricas = populacao.metricas_concentracao(painel)\n"
            'print(f"Gini da população municipal: {metricas[\'gini\']:.3f}")\n'
            'print(f"Os 10% maiores concentram {metricas[\'share_top_10pct\']:.1f}% da população")\n'
            'print(f"Os 100 maiores concentram {metricas[\'share_top_100\']:.1f}% da população")\n\n'
            'charts.lorenz(populacao.curva_lorenz(painel),\n'
            '              titulo="Curva de Lorenz da população municipal")'
        ),
        md(
            "## Trajetória das regiões\n\n"
            "Séries indexadas a 100 no primeiro ano: é o que permite comparar "
            "regiões de tamanhos muito diferentes num eixo só, sem recorrer a "
            "um segundo eixo y."
        ),
        code(
            'por_regiao = pop_ufs.groupby(["ano", "regiao_nome"], observed=True,\n'
            '                             as_index=False)["populacao"].sum()\n'
            'base = por_regiao[por_regiao["ano"] == por_regiao["ano"].min()]\\\n'
            '    .set_index("regiao_nome")["populacao"]\n'
            'por_regiao["indice"] = por_regiao["populacao"] / por_regiao["regiao_nome"].map(base) * 100\n\n'
            'charts.linha_temporal(por_regiao, x="ano", y="indice", cor="regiao_nome",\n'
            '                      titulo="População por região (base 100)")'
        ),
        md(
            "> A série de estimativas não cobre 2007, 2010, 2022 e 2023 — anos "
            "de Censo/Contagem ou de estimativa suspensa para revisão. As "
            "linhas ligam os anos publicados."
        ),
    ]


def nb_crescimento() -> list:
    return [
        md(
            "# 02 · Crescimento populacional\n\n"
            "Quem cresce, quem encolhe e em que ritmo. A métrica é o **CAGR** "
            "(taxa média de crescimento anual composta), que compara ritmos "
            "entre entidades com séries de comprimentos diferentes."
        ),
        code(PREAMBULO),
        code(
            "from ibge_analytics.analysis import crescimento\n\n"
            'cresc = io.carregar("crescimento_municipios")\n'
            'ano_ini, ano_fim = int(cresc["ano_inicial"].min()), int(cresc["ano_final"].max())\n'
            "resumo = crescimento.resumo_declinio(cresc)\n"
            'print(f"Período: {ano_ini}–{ano_fim}")\n'
            'print(f"Municípios perdendo população: {resumo[\'n_perdendo\']:,} '
            '({resumo[\'pct_perdendo\']:.1f}%)")\n'
            'print(f"População perdida somada: {resumo[\'populacao_perdida\']:,.0f}")\n'
            'print(f"CAGR mediano: {resumo[\'cagr_mediano\']:.2f}% a.a.")'
        ),
        md(
            "Vale reparar no número acima: o país como um todo ainda cresce, mas "
            "uma fatia grande dos municípios encolhe. O crescimento nacional se "
            "concentra em poucos polos."
        ),
        md("## Extremos"),
        code(
            "top = crescimento.top_crescimento(cresc, n=15, populacao_minima=20_000)\n"
            'top["rotulo"] = top["municipio_nome"] + " (" + top["uf_sigla"] + ")"\n'
            'charts.barras_ranking(top, x="cagr_pct", y="rotulo", rotulo_valor="CAGR",\n'
            '                      sufixo="% a.a.", casas=2,\n'
            '                      titulo="Maior crescimento (≥ 20 mil habitantes)")'
        ),
        code(
            "baixo = crescimento.top_declinio(cresc, n=15, populacao_minima=20_000)\n"
            'baixo["rotulo"] = baixo["municipio_nome"] + " (" + baixo["uf_sigla"] + ")"\n'
            'charts.barras_ranking(baixo, x="cagr_pct", y="rotulo", rotulo_valor="CAGR",\n'
            '                      sufixo="% a.a.", casas=2,\n'
            '                      titulo="Maior retração (≥ 20 mil habitantes)")'
        ),
        md(
            "> O corte de 20 mil habitantes evita que municípios minúsculos "
            "dominem o ranking: sair de 800 para 1.600 habitantes é +100%, mas "
            "não é o mesmo fenômeno que o crescimento de uma cidade média."
        ),
        md("## Panorama regional"),
        code(
            "por_regiao = crescimento.crescimento_por_regiao(cresc)\n"
            "display(por_regiao)\n"
            "display(crescimento.distribuicao_faixas(cresc))"
        ),
        md("## Onde o país cresce e onde encolhe"),
        code(
            'malha = io.carregar_malha("municipios")\n'
            'painel = io.carregar("painel_municipios")\n'
            'maps.coropletico_plotly(\n'
            '    painel, malha, id_col="municipio_id", valor_col="cagr_pct",\n'
            '    nome_col="municipio_nome", divergente=True,\n'
            '    titulo=f"Crescimento populacional {ano_ini}–{ano_fim}", rotulo="% a.a.")'
        ),
        md(
            "> Escala divergente com cinza no zero, porque aqui o zero é um "
            "limiar real: de um lado municípios que crescem, do outro os que "
            "encolhem."
        ),
    ]


def nb_pib() -> list:
    return [
        md(
            "# 03 · PIB\n\n"
            "Riqueza, produtividade e estrutura setorial.\n\n"
            "**Fonte:** agregado 5938 (PIB municipal a preços correntes)."
        ),
        code(PREAMBULO),
        code(
            "from ibge_analytics.analysis import pib as an_pib\n\n"
            'painel = io.carregar("painel_municipios")\n'
            'painel_uf = io.carregar("painel_ufs")\n'
            'pib_ufs = io.carregar("pib_ufs")\n'
            'ano_pib = int(painel["ano_pib"].iloc[0])\n'
            'ano_pop = int(painel["ano_populacao_pib"].iloc[0])\n'
            'print(f"PIB {ano_pib} · população de referência {ano_pop}")\n'
            'print(f"PIB nacional: R$ {painel[\'pib_mil_reais\'].sum() * 1_000:,.0f}")'
        ),
        md(
            "> O PIB per capita usa a população do ano publicado mais próximo "
            "ao do PIB — a série de estimativas não cobre 2022 nem 2023."
        ),
        md("## Concentração do PIB"),
        code(
            "conc = an_pib.resumo_concentracao_municipal(painel)\n"
            'print(f"Metade do PIB nacional está em {conc[\'n_municipios_metade_pib\']} '
            'municípios ({conc[\'pct_municipios_metade_pib\']:.1f}% do total)")\n'
            'print(f"Os 10 maiores somam {conc[\'share_top_10\']:.1f}% do PIB")\n'
            'print(f"Gini do PIB municipal: {conc[\'gini\']:.3f}")'
        ),
        md("## Riqueza x população por UF"),
        code(
            "desc = an_pib.descolamento_pib_populacao(painel_uf)\n"
            "display(desc)\n"
            'charts.barras_agrupadas_comparacao(\n'
            '    desc, categoria="uf_sigla",\n'
            '    series={"part_pib_brasil": "% do PIB", "part_pop_brasil": "% da população"},\n'
            '    titulo="Onde a barra do PIB supera a da população, a UF concentra riqueza")'
        ),
        md(
            "As duas séries são percentuais do mesmo total nacional, então "
            "compartilham um eixo legitimamente. Grandezas de escalas diferentes "
            "nunca deveriam dividir um eixo."
        ),
        md("## Estrutura setorial"),
        code(
            'estrutura = an_pib.estrutura_setorial(painel_uf, chave="uf_sigla")\n'
            'charts.barras_empilhadas(estrutura, x="uf_sigla", y="participacao", cor="setor",\n'
            '                         titulo="Participação setorial no valor adicionado (%)")'
        ),
        md("## A economia está desconcentrando?"),
        code(
            "evolucao = an_pib.evolucao_participacao_regional(pib_ufs)\n"
            'charts.linha_temporal(evolucao, x="ano", y="part_pib_brasil", cor="regiao_nome",\n'
            '                      titulo="Participação de cada região no PIB nacional (%)")'
        ),
        md("## Riqueza x tamanho dos municípios"),
        code(
            'charts.dispersao_facetada(\n'
            '    painel.dropna(subset=["pib_per_capita", "populacao_atual"]),\n'
            '    x="populacao_atual", y="pib_per_capita",\n'
            '    titulo="População (log) × PIB per capita (log), por região")'
        ),
        md(
            "> Facetado em vez de colorido: numa dispersão todos os pares de "
            "cor competem entre si, e cinco séries sobrepostas deixariam de ser "
            "distinguíveis com segurança. A nuvem cinza é o país inteiro."
        ),
    ]


def nb_densidade() -> list:
    return [
        md(
            "# 04 · Densidade demográfica\n\n"
            "Como o território é ocupado.\n\n"
            "**Fonte:** agregado 4714 (Censo 2022 — população, área e densidade)."
        ),
        code(PREAMBULO),
        code(
            "from ibge_analytics.analysis import densidade as an_dens\n\n"
            'painel = io.carregar("painel_municipios")\n'
            'painel_reg = io.carregar("painel_regioes")\n'
            "terr = an_dens.concentracao_territorial(painel)\n"
            'print(f"Densidade nacional: '
            '{painel[\'populacao_atual\'].sum() / painel[\'area_km2\'].sum():.1f} hab/km²")\n'
            'print(f"Metade da população vive em {terr[\'n_municipios_metade_pop\']} municípios,")\n'
            'print(f"que ocupam {terr[\'pct_area_metade_pop\']:.1f}% do território nacional.")'
        ),
        md("## Território x população"),
        code(
            "distrib = an_dens.distribuicao(painel)\n"
            "display(distrib)\n"
            'charts.barras_agrupadas_comparacao(\n'
            '    distrib, categoria="faixa_densidade",\n'
            '    series={"pct_area": "% do território", "pct_populacao": "% da população"},\n'
            '    titulo="As faixas mais vazias ocupam quase todo o país")'
        ),
        md("## Extremos"),
        code(
            "extremos = an_dens.extremos(painel, n=10)\n"
            'print("Mais densos:"); display(extremos["mais_densos"])\n'
            'print("Mais vazios:"); display(extremos["mais_vazios"])\n'
            'print("Maiores áreas:"); display(extremos["maiores_areas"])'
        ),
        md("## Distribuição"),
        code(
            'charts.histograma(painel, coluna="densidade_atual", log_x=True, nbins=60,\n'
            '                  titulo="Municípios por densidade (escala log)")'
        ),
        md(
            "> Eixo logarítmico porque a densidade municipal varia de menos de "
            "0,1 a mais de 10 mil hab/km²; numa escala linear tudo se "
            "acumularia numa barra só."
        ),
        md("## Mapa"),
        code(
            'malha = io.carregar_malha("municipios")\n'
            'maps.coropletico_plotly(\n'
            '    painel, malha, id_col="municipio_id", valor_col="densidade_atual",\n'
            '    nome_col="municipio_nome", escala_log=True,\n'
            '    titulo="Densidade demográfica municipal", rotulo="hab/km²")'
        ),
    ]


def nb_regioes() -> list:
    return [
        md(
            "# 05 · Comparação entre regiões\n\n"
            "As cinco grandes regiões lado a lado: população, território, "
            "riqueza e ocupação."
        ),
        code(PREAMBULO),
        code(
            'painel_reg = io.carregar("painel_regioes")\n'
            'painel_uf = io.carregar("painel_ufs")\n'
            "display(painel_reg[[\n"
            '    "regiao_nome", "n_ufs", "populacao_atual", "area_km2", "densidade_atual",\n'
            '    "part_pop_brasil", "part_area_brasil", "part_pib_brasil", "pib_per_capita",\n'
            "]])"
        ),
        md(
            "## Território, gente e riqueza\n\n"
            "Três percentuais do mesmo total nacional — a defasagem entre eles "
            "é o retrato da desigualdade regional brasileira."
        ),
        code(
            'charts.barras_agrupadas_comparacao(\n'
            '    painel_reg, categoria="regiao_nome",\n'
            '    series={"part_area_brasil": "% do território",\n'
            '            "part_pop_brasil": "% da população",\n'
            '            "part_pib_brasil": "% do PIB"},\n'
            '    titulo="Participação de cada região no total nacional")'
        ),
        md("## PIB per capita e densidade"),
        code(
            'charts.barras_ranking(painel_reg, x="pib_per_capita", y="regiao_nome",\n'
            '                      rotulo_valor="PIB per capita", sufixo="", casas=0,\n'
            '                      titulo="PIB per capita por região (R$)")'
        ),
        code(
            'charts.barras_ranking(painel_reg, x="densidade_atual", y="regiao_nome",\n'
            '                      rotulo_valor="Densidade", sufixo=" hab/km²", casas=1,\n'
            '                      titulo="Densidade demográfica por região")'
        ),
        md("## Mapa das regiões"),
        code(
            'malha_reg = io.carregar_malha("regioes")\n'
            'from ibge_analytics.config import REGIOES\n'
            'inverso = {v: str(k) for k, v in REGIOES.items()}\n'
            'reg = painel_reg.assign(regiao_id=painel_reg["regiao_nome"].map(inverso))\n'
            'maps.coropletico_plotly(\n'
            '    reg, malha_reg, id_col="regiao_id", valor_col="pib_per_capita",\n'
            '    nome_col="regiao_nome", titulo="PIB per capita por região", rotulo="R$")'
        ),
        md("## Mapa navegável (Folium)"),
        code(
            'malha_uf = io.carregar_malha("ufs")\n'
            'uf = painel_uf.assign(uf_id_str=painel_uf["uf_id"].astype(str))\n'
            'maps.coropletico_folium(\n'
            '    uf, malha_uf, id_col="uf_id_str", valor_col="pib_per_capita",\n'
            '    nome_col="uf_nome", rotulo="PIB per capita (R$)")'
        ),
    ]


CADERNOS = {
    "01_populacao.ipynb": nb_populacao,
    "02_crescimento.ipynb": nb_crescimento,
    "03_pib.ipynb": nb_pib,
    "04_densidade.ipynb": nb_densidade,
    "05_regioes.ipynb": nb_regioes,
}


def main() -> int:
    NOTEBOOKS.mkdir(parents=True, exist_ok=True)
    for nome, construir in CADERNOS.items():
        nb = nbf.v4.new_notebook(cells=construir())
        nb.metadata = {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        }
        destino = NOTEBOOKS / nome
        nbf.write(nb, destino)
        print(f"gerado: notebooks/{nome} ({len(nb.cells)} células)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
