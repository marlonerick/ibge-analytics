"""Gera o relatório HTML autocontido a partir das tabelas processadas.

O relatório é uma leitura narrada dos dados — não um despejo de gráficos. Cada
seção abre com o número que importa e só depois mostra o gráfico.

Uso:
    python scripts/build_report.py
    python scripts/build_report.py --saida reports/relatorio.html
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402
import plotly.io as pio  # noqa: E402

from ibge_analytics.analysis import (  # noqa: E402
    crescimento,
    densidade as an_dens,
    pib as an_pib,
    populacao,
)
from ibge_analytics.config import REPORTS_DIR  # noqa: E402
from ibge_analytics.utils import io  # noqa: E402
from ibge_analytics.viz import charts, maps  # noqa: E402
from ibge_analytics.viz.theme import formatar_compacto, formatar_numero  # noqa: E402

CSS = """
:root {
  color-scheme: light dark;
  --superficie:#fcfcfb; --plano:#f9f9f7; --tinta:#0b0b0b; --tinta2:#52514e;
  --suave:#898781; --grade:#e1e0d9; --borda:rgba(11,11,11,.10); --azul:#2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root { --superficie:#1a1a19; --plano:#0d0d0d; --tinta:#fff; --tinta2:#c3c2b7;
          --grade:#2c2c2a; --borda:rgba(255,255,255,.10); --azul:#3987e5; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--plano); color:var(--tinta);
       font-family:system-ui,-apple-system,"Segoe UI",sans-serif; line-height:1.6; }
.envelope { max-width:1080px; margin:0 auto; padding:48px 24px 96px; }
header { border-bottom:1px solid var(--borda); padding-bottom:24px; margin-bottom:40px; }
h1 { font-size:34px; margin:0 0 8px; letter-spacing:-.02em; }
h2 { font-size:23px; margin:56px 0 6px; letter-spacing:-.01em;
     /* Compensa a navbar fixa: sem isto o âncora para com o título escondido. */
     scroll-margin-top:64px; }

/* ---------------------------------------------------------------- navbar --- */
.navbar { position:sticky; top:0; z-index:50; background:var(--superficie);
          border-bottom:1px solid var(--borda); }
@supports (backdrop-filter:blur(8px)) {
  .navbar { background:color-mix(in srgb, var(--superficie) 88%, transparent);
            backdrop-filter:blur(8px); }
}
.navbar-in { max-width:1080px; margin:0 auto; padding:0 24px;
             display:flex; align-items:center; gap:20px; }
.marca { font-weight:600; font-size:14px; letter-spacing:-.01em; white-space:nowrap;
         padding:13px 0; color:var(--tinta); text-decoration:none; }
.marca:hover { color:var(--azul); }
.navbar ul { list-style:none; display:flex; gap:2px; margin:0; padding:0;
             overflow-x:auto; scrollbar-width:none; }
.navbar ul::-webkit-scrollbar { display:none; }
.navbar a.item { display:block; padding:13px 11px; font-size:13.5px; white-space:nowrap;
                 color:var(--tinta2); text-decoration:none;
                 border-bottom:2px solid transparent; }
.navbar a.item:hover { color:var(--tinta); }
.navbar a.item[aria-current="true"] { color:var(--azul); border-bottom-color:var(--azul); }
.navbar a.item:focus-visible { outline:2px solid var(--azul); outline-offset:-4px; }
/* Em tela estreita a marca sai: o espaço vale mais para os links. */
@media (max-width:640px) { .marca { display:none; } .navbar-in { padding:0 12px; } }

.ao-topo { position:fixed; right:20px; bottom:20px; z-index:40;
           width:40px; height:40px; border-radius:50%; cursor:pointer;
           border:1px solid var(--borda); background:var(--superficie);
           color:var(--tinta2); font-size:16px; line-height:1;
           opacity:0; pointer-events:none; transition:opacity .18s ease; }
.ao-topo.ver { opacity:1; pointer-events:auto; }
.ao-topo:hover { color:var(--azul); }
.ao-topo:focus-visible { outline:2px solid var(--azul); outline-offset:2px; }

html { scroll-behavior:smooth; }
@media (prefers-reduced-motion:reduce) {
  html { scroll-behavior:auto; }
  .ao-topo { transition:none; }
}
h3 { font-size:16px; margin:32px 0 8px; color:var(--tinta2); font-weight:600; }
p  { color:var(--tinta2); margin:8px 0 16px; }
.sub { color:var(--suave); font-size:14px; }
.grade { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
         gap:12px; margin:24px 0; }
.cartao { border:1px solid var(--borda); border-radius:10px; padding:16px 18px;
          background:var(--superficie); }
.cartao .rot { font-size:11px; text-transform:uppercase; letter-spacing:.04em;
               color:var(--tinta2); margin-bottom:6px; }
.cartao .val { font-size:27px; font-weight:600; color:var(--tinta); line-height:1.15; }
.cartao .nota { font-size:12px; color:var(--suave); margin-top:4px; }
figure { margin:20px 0 8px; border:1px solid var(--borda); border-radius:10px;
         background:var(--superficie); padding:8px; overflow-x:auto; }
figcaption { font-size:13px; color:var(--suave); margin:8px 4px 0; }
table { border-collapse:collapse; width:100%; font-size:13px; margin:16px 0;
        font-variant-numeric:tabular-nums; display:block; overflow-x:auto; }
th,td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--grade);
        white-space:nowrap; }
th { color:var(--tinta2); font-weight:600; font-size:12px; text-transform:uppercase;
     letter-spacing:.03em; }
td { color:var(--tinta2); }
.destaque { border-left:3px solid var(--azul); padding:10px 0 10px 16px;
            margin:20px 0; color:var(--tinta2); background:transparent; }
footer { margin-top:72px; padding-top:20px; border-top:1px solid var(--borda);
         font-size:13px; color:var(--suave); }
code { background:var(--grade); padding:2px 6px; border-radius:4px; font-size:12px; }
"""


def _slug(texto: str) -> str:
    """Identificador de âncora a partir do título da seção.

    Sem acento e sem espaço, para que o link fique legível na barra de
    endereços — `#crescimento-populacional` e não `#se%C3%A7%C3%A3o-3`.
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


#: Realce da seção atual e botão de voltar ao topo.
#:
#: O realce vem da posição de rolagem, e não de IntersectionObserver: as seções
#: aqui têm alturas muito desiguais — um mapa Plotly ocupa 680px, um destaque
#: ocupa três linhas — e observar a entrada de cada uma faria a marcação pular
#: para a frente e para trás. Comparar `offsetTop` com a rolagem atual sempre
#: aponta a seção em que o leitor de fato está.
JS = """
(function () {
  var titulos = Array.prototype.slice.call(document.querySelectorAll('h2[id]'));
  var links = {};
  Array.prototype.forEach.call(document.querySelectorAll('.navbar a.item'), function (a) {
    links[a.getAttribute('href').slice(1)] = a;
  });
  var aoTopo = document.querySelector('.ao-topo');
  var agendado = false;

  function atualizar() {
    agendado = false;
    var y = window.scrollY + 80;
    var atual = titulos.length ? titulos[0].id : null;
    for (var i = 0; i < titulos.length; i++) {
      if (titulos[i].offsetTop <= y) atual = titulos[i].id;
    }
    // Perto do fim da página a última seção é a que o leitor está vendo, mesmo
    // que seu título já tenha passado bem para cima.
    if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 80 && titulos.length) {
      atual = titulos[titulos.length - 1].id;
    }
    for (var id in links) {
      if (id === atual) links[id].setAttribute('aria-current', 'true');
      else links[id].removeAttribute('aria-current');
    }
    aoTopo.classList.toggle('ver', window.scrollY > 400);
  }

  window.addEventListener('scroll', function () {
    if (!agendado) { agendado = true; requestAnimationFrame(atualizar); }
  }, { passive: true });
  window.addEventListener('resize', atualizar, { passive: true });

  aoTopo.addEventListener('click', function () {
    window.scrollTo({ top: 0, behavior:
      matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  });

  atualizar();
})();
"""


class Relatorio:
    #: Rótulos mais curtos para a navbar, onde o espaço é disputado. A chave é o
    #: slug; um título sem entrada aqui aparece como está.
    ROTULOS_CURTOS = {
        "crescimento-populacional": "Crescimento",
        "densidade-demografica": "Densidade",
        "as-cinco-regioes": "Regiões",
    }

    def __init__(self) -> None:
        self.partes: list[str] = []
        self.primeiro_grafico = True
        #: (slug, rótulo) de cada seção, na ordem em que aparecem. A navbar é
        #: montada daqui, e não de uma lista à parte — assim uma seção nova
        #: entra no menu sem que ninguém precise lembrar de atualizá-lo.
        self.secoes: list[tuple[str, str]] = []

    def html(self, fragmento: str) -> None:
        self.partes.append(fragmento)

    def titulo(self, texto: str) -> None:
        slug = _slug(texto)
        self.secoes.append((slug, self.ROTULOS_CURTOS.get(slug, texto)))
        self.html(f'<h2 id="{slug}">{texto}</h2>')

    def subtitulo(self, texto: str) -> None:
        self.html(f"<h3>{texto}</h3>")

    def paragrafo(self, texto: str) -> None:
        self.html(f"<p>{texto}</p>")

    def destaque(self, texto: str) -> None:
        self.html(f'<div class="destaque">{texto}</div>')

    def cartoes(self, itens: list[tuple[str, str, str]]) -> None:
        blocos = "".join(
            f'<div class="cartao"><div class="rot">{r}</div>'
            f'<div class="val">{v}</div><div class="nota">{n}</div></div>'
            for r, v, n in itens
        )
        self.html(f'<div class="grade">{blocos}</div>')

    def figura(self, fig, legenda: str = "") -> None:
        # O plotly.js entra uma vez só, no primeiro gráfico; os demais
        # referenciam o mesmo bundle. Sem isso o arquivo passa de 30 MB.
        corpo = pio.to_html(
            fig,
            include_plotlyjs="inline" if self.primeiro_grafico else False,
            full_html=False,
            config={"displayModeBar": False, "responsive": True},
        )
        self.primeiro_grafico = False
        rodape = f"<figcaption>{legenda}</figcaption>" if legenda else ""
        self.html(f"<figure>{corpo}{rodape}</figure>")

    def tabela(self, df: pd.DataFrame, legenda: str = "") -> None:
        self.html(df.to_html(index=False, border=0, escape=False))
        if legenda:
            self.html(f'<p class="sub">{legenda}</p>')

    def navbar(self, marca: str) -> str:
        itens = "".join(
            f'<li><a class="item" href="#{slug}">{rotulo}</a></li>'
            for slug, rotulo in self.secoes
        )
        return (
            '<nav class="navbar" aria-label="Seções do relatório"><div class="navbar-in">'
            f'<a class="marca" href="#topo">{marca}</a>'
            f"<ul>{itens}</ul>"
            "</div></nav>"
        )

    def renderizar(self, titulo: str, marca: str = "Brasil em números") -> str:
        return (
            "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{titulo}</title><style>{CSS}</style></head><body id='topo'>"
            f"{self.navbar(marca)}"
            f"<div class='envelope'>{''.join(self.partes)}</div>"
            '<button class="ao-topo" type="button" aria-label="Voltar ao topo">&uarr;</button>'
            f"<script>{JS}</script></body></html>"
        )


def construir() -> str:
    painel = io.carregar("painel_municipios")
    painel_uf = io.carregar("painel_ufs")
    painel_reg = io.carregar("painel_regioes")
    cresc = io.carregar("crescimento_municipios")
    pib_ufs = io.carregar("pib_ufs")
    pop_ufs = io.carregar("populacao_ufs")

    ano_pop = int(painel["ano_populacao"].iloc[0])
    ano_pib = int(painel["ano_pib"].iloc[0])
    ano_pop_pib = int(painel["ano_populacao_pib"].iloc[0])
    ano_ini = int(cresc["ano_inicial"].min())

    r = Relatorio()
    r.html(
        f"<header><h1>Brasil em números</h1>"
        f"<p class='sub'>Análise territorial a partir das APIs públicas do IBGE — "
        f"população {ano_pop}, PIB {ano_pib}, área e densidade do Censo 2022.<br>"
        f"Gerado em {date.today():%d/%m/%Y}.</p></header>"
    )

    # ---------------------------------------------------------------- panorama
    pib_total = painel["pib_mil_reais"].sum() * 1_000
    pib_pc = pib_total / painel["populacao_ano_pib"].sum()
    dens_br = painel["populacao_atual"].sum() / painel["area_km2"].sum()
    r.titulo("Panorama")
    r.cartoes(
        [
            ("População", formatar_compacto(painel["populacao_atual"].sum()), f"estimativa {ano_pop}"),
            ("Municípios", formatar_numero(len(painel)), "unidades territoriais"),
            ("PIB", "R$ " + formatar_compacto(pib_total), f"preços correntes {ano_pib}"),
            ("PIB per capita", "R$ " + formatar_numero(pib_pc), f"população {ano_pop_pib}"),
            ("Área", formatar_compacto(painel["area_km2"].sum()) + " km²", "Censo 2022"),
            ("Densidade", formatar_numero(dens_br, 1) + " hab/km²", "média nacional"),
        ]
    )

    # ---------------------------------------------------------------- população
    conc = populacao.metricas_concentracao(painel)
    porte = populacao.distribuicao_por_porte(painel)
    pequenos = porte[porte["porte"].isin(["Até 5 mil", "5 a 10 mil"])]

    r.titulo("População")
    r.destaque(
        f"<strong>{pequenos['pct_municipios'].sum():.0f}% dos municípios brasileiros "
        f"têm menos de 10 mil habitantes — e somados abrigam apenas "
        f"{pequenos['pct_populacao'].sum():.0f}% da população.</strong> "
        f"No outro extremo, os 100 maiores concentram {conc['share_top_100']:.0f}%."
    )
    r.figura(
        charts.barras_agrupadas_comparacao(
            porte, categoria="porte",
            series={"pct_municipios": "% dos municípios", "pct_populacao": "% da população"},
            titulo="Porte municipal: muitos municípios pequenos, pouca gente neles",
        ),
        "Duas séries percentuais do mesmo total, por isso compartilham um eixo.",
    )
    r.figura(
        charts.lorenz(populacao.curva_lorenz(painel),
                      titulo=f"Curva de Lorenz da população (Gini {conc['gini']:.3f})"),
        "Quanto mais a curva se afasta da diagonal, mais concentrada a distribuição.",
    )

    ranking = populacao.ranking_municipios(painel, n=12)
    ranking["rotulo"] = ranking["municipio_nome"] + " (" + ranking["uf_sigla"] + ")"
    r.figura(
        charts.barras_ranking(ranking, x="populacao_atual", y="rotulo",
                              rotulo_valor="População",
                              titulo=f"Municípios mais populosos ({ano_pop})"),
    )

    # -------------------------------------------------------------- crescimento
    resumo = crescimento.resumo_declinio(cresc)
    ano_fim = int(cresc["ano_final"].max())
    r.titulo("Crescimento populacional")
    r.destaque(
        f"<strong>{resumo['pct_perdendo']:.0f}% dos municípios perderam população "
        f"entre {ano_ini} e {ano_fim}</strong>, somando "
        f"{formatar_compacto(resumo['populacao_perdida'])} habitantes a menos — "
        f"mesmo com o país crescendo no agregado. O crescimento nacional se "
        f"concentra em poucos polos."
    )
    r.figura(
        maps.coropletico_plotly(
            painel, io.carregar_malha("municipios"), id_col="municipio_id",
            valor_col="cagr_pct", nome_col="municipio_nome", divergente=True,
            titulo=f"Crescimento populacional {ano_ini}–{ano_fim} (CAGR)",
            rotulo="% a.a.", altura=680,
        ),
        "Escala divergente com cinza no zero — aqui o zero separa crescer de encolher. "
        "O azul da fronteira agrícola contrasta com o vermelho do interior do Sul e do Sudeste.",
    )
    r.subtitulo("Por região")
    por_regiao = crescimento.crescimento_por_regiao(cresc)
    r.tabela(
        por_regiao.assign(
            **{
                "Região": por_regiao["regiao_nome"],
                "Municípios": por_regiao["n_municipios"],
                "% encolhendo": por_regiao["pct_perdendo"].map(lambda v: f"{v:.1f}%"),
                "CAGR mediano": por_regiao["cagr_mediano"].map(lambda v: f"{v:.2f}%"),
                "Crescimento total": por_regiao["crescimento_regional_pct"].map(lambda v: f"{v:+.1f}%"),
            }
        )[["Região", "Municípios", "% encolhendo", "CAGR mediano", "Crescimento total"]],
        "«Crescimento total» é a variação da população somada da região — diferente "
        "da mediana municipal, que dá peso igual a cada município.",
    )

    # ---------------------------------------------------------------------- PIB
    conc_pib = an_pib.resumo_concentracao_municipal(painel)
    r.titulo("PIB")
    r.destaque(
        f"<strong>Metade do PIB brasileiro é produzida em "
        f"{conc_pib['n_municipios_metade_pib']} municípios</strong> — "
        f"{conc_pib['pct_municipios_metade_pib']:.1f}% do total. "
        f"O Gini do PIB municipal ({conc_pib['gini']:.2f}) é ainda mais alto que "
        f"o da população ({conc['gini']:.2f})."
    )
    desc = an_pib.descolamento_pib_populacao(painel_uf)
    r.figura(
        charts.barras_agrupadas_comparacao(
            desc, categoria="uf_sigla",
            series={"part_pib_brasil": "% do PIB", "part_pop_brasil": "% da população"},
            titulo="Riqueza x população por UF",
        ),
        "Onde a barra do PIB supera a da população, a UF concentra mais riqueza do que gente.",
    )
    r.figura(
        charts.barras_empilhadas(
            an_pib.estrutura_setorial(painel_uf, chave="uf_sigla"),
            x="uf_sigla", y="participacao", cor="setor",
            titulo="Estrutura setorial do valor adicionado bruto (%)",
        ),
        "«Serviços» exclui administração, defesa, educação e saúde públicas, que "
        "formam categoria própria na publicação do IBGE.",
    )
    r.figura(
        charts.linha_temporal(
            an_pib.evolucao_participacao_regional(pib_ufs),
            x="ano", y="part_pib_brasil", cor="regiao_nome",
            titulo="Participação de cada região no PIB nacional (%)",
        ),
        "Séries com rótulo direto: a identidade não depende apenas da cor.",
    )

    # ---------------------------------------------------------------- densidade
    terr = an_dens.concentracao_territorial(painel)
    r.titulo("Densidade demográfica")
    r.destaque(
        f"<strong>Metade da população brasileira vive em "
        f"{terr['n_municipios_metade_pop']} municípios que ocupam "
        f"{terr['pct_area_metade_pop']:.1f}% do território.</strong> "
        f"A outra metade se espalha pelos {100 - terr['pct_area_metade_pop']:.1f}% restantes."
    )
    r.figura(
        charts.barras_agrupadas_comparacao(
            an_dens.distribuicao(painel), categoria="faixa_densidade",
            series={"pct_area": "% do território", "pct_populacao": "% da população"},
            titulo="As faixas mais vazias ocupam quase todo o país",
        ),
    )
    r.figura(
        maps.coropletico_plotly(
            painel, io.carregar_malha("municipios"), id_col="municipio_id",
            valor_col="densidade_atual", nome_col="municipio_nome", escala_log=True,
            titulo="Densidade demográfica municipal", rotulo="hab/km²", altura=680,
        ),
        "Escala logarítmica: a densidade municipal varia de menos de 0,1 a mais de "
        "10 mil hab/km², e numa escala linear o mapa inteiro sairia de uma cor só.",
    )

    # ------------------------------------------------------------------ regiões
    r.titulo("As cinco regiões")
    r.figura(
        charts.barras_agrupadas_comparacao(
            painel_reg, categoria="regiao_nome",
            series={"part_area_brasil": "% do território",
                    "part_pop_brasil": "% da população",
                    "part_pib_brasil": "% do PIB"},
            titulo="Participação de cada região no total nacional",
        ),
        "A defasagem entre as três barras é o retrato da desigualdade regional.",
    )
    r.tabela(
        painel_reg.assign(
            **{
                "Região": painel_reg["regiao_nome"],
                "UFs": painel_reg["n_ufs"],
                "População": painel_reg["populacao_atual"].map(formatar_compacto),
                "Área (km²)": painel_reg["area_km2"].map(formatar_compacto),
                "Densidade": painel_reg["densidade_atual"].map(lambda v: f"{v:.1f}"),
                "% do PIB": painel_reg["part_pib_brasil"].map(lambda v: f"{v:.1f}%"),
                "PIB per capita": painel_reg["pib_per_capita"].map(
                    lambda v: "R$ " + formatar_numero(v)),
            }
        )[["Região", "UFs", "População", "Área (km²)", "Densidade", "% do PIB", "PIB per capita"]]
    )

    r.html(
        "<footer>Fontes: IBGE — API de Agregados v3 (agregados "
        "<code>6579</code> população estimada, <code>4714</code> Censo 2022, "
        "<code>5938</code> PIB municipal), API de Localidades v1 e API de "
        "Malhas v3.<br>Gerado por <code>scripts/build_report.py</code> a partir "
        "das tabelas em <code>data/processed/</code>.</footer>"
    )
    return r.renderizar("Brasil em números — IBGE")


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera o relatório HTML")
    parser.add_argument("--saida", type=Path, default=REPORTS_DIR / "relatorio.html")
    args = parser.parse_args()

    if not io.dados_disponiveis():
        print("Dados processados ausentes. Rode: python -m ibge_analytics.etl.pipeline")
        return 1

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(construir(), encoding="utf-8")
    print(f"relatório gerado: {args.saida} ({args.saida.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
