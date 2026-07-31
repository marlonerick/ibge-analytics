"""Testes do gerador de relatório.

O que vale travar aqui é a invariante da navegação: **a navbar é derivada das
seções**, não escrita à parte. Se alguém acrescentar um `r.titulo(...)` e a
barra não acompanhar, é porque a derivação quebrou — e é isso que estes testes
detectam, sem precisar dos dados processados nem gerar os 12 MB do relatório.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def build_report():
    """Importa scripts/build_report.py, que não é um módulo do pacote."""
    caminho = RAIZ / "scripts" / "build_report.py"
    spec = importlib.util.spec_from_file_location("build_report", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# --------------------------------------------------------------------------- #
# _slug
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "titulo, esperado",
    [
        ("Panorama", "panorama"),
        ("População", "populacao"),
        ("Crescimento populacional", "crescimento-populacional"),
        ("Densidade demográfica", "densidade-demografica"),
        ("As cinco regiões", "as-cinco-regioes"),
        ("PIB", "pib"),
    ],
)
def test_slug_remove_acento_e_espaco(build_report, titulo, esperado):
    """A âncora precisa ser legível na barra de endereços, não percent-encoded."""
    assert build_report._slug(titulo) == esperado


def test_slug_nao_deixa_hifen_nas_pontas(build_report):
    assert build_report._slug("  As cinco regiões!  ") == "as-cinco-regioes"


def test_slug_e_valido_como_id_html(build_report):
    for titulo in ["Panorama", "População", "Crescimento populacional", "PIB"]:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", build_report._slug(titulo))


# --------------------------------------------------------------------------- #
# navbar derivada das seções
# --------------------------------------------------------------------------- #

def test_titulo_registra_a_secao(build_report):
    r = build_report.Relatorio()
    r.titulo("Panorama")
    r.titulo("Crescimento populacional")
    assert [s for s, _ in r.secoes] == ["panorama", "crescimento-populacional"]


def test_titulo_emite_h2_com_id(build_report):
    r = build_report.Relatorio()
    r.titulo("Densidade demográfica")
    assert '<h2 id="densidade-demografica">Densidade demográfica</h2>' in "".join(r.partes)


def test_navbar_cobre_todas_as_secoes(build_report):
    r = build_report.Relatorio()
    for t in ["Panorama", "População", "PIB"]:
        r.titulo(t)
    nav = r.navbar("Marca")
    for slug in ["panorama", "populacao", "pib"]:
        assert f'href="#{slug}"' in nav


def test_secao_nova_entra_no_menu_sozinha(build_report):
    """A razão de ser da derivação: nenhuma lista paralela para esquecer."""
    r = build_report.Relatorio()
    r.titulo("Panorama")
    antes = r.navbar("M").count('class="item"')
    r.titulo("Seção inventada agora")
    depois = r.navbar("M")
    assert depois.count('class="item"') == antes + 1
    assert 'href="#secao-inventada-agora"' in depois


def test_navbar_usa_rotulo_curto_quando_ha(build_report):
    r = build_report.Relatorio()
    r.titulo("Crescimento populacional")
    nav = r.navbar("M")
    assert ">Crescimento<" in nav
    # O título completo continua no corpo; só o menu encurta.
    assert "<h2 id=\"crescimento-populacional\">Crescimento populacional</h2>" in "".join(r.partes)


def test_documento_final_tem_navbar_antes_do_conteudo(build_report):
    r = build_report.Relatorio()
    r.titulo("Panorama")
    doc = r.renderizar("Título")
    assert doc.index('<nav class="navbar"') < doc.index("<div class='envelope'>")


def test_todo_link_da_navbar_aponta_para_um_id_existente(build_report):
    r = build_report.Relatorio()
    for t in ["Panorama", "População", "Crescimento populacional", "As cinco regiões"]:
        r.titulo(t)
    doc = r.renderizar("Título")

    destinos = {m for m in re.findall(r'class="item" href="#([^"]+)"', doc)}
    ancoras = set(re.findall(r'<h2 id="([^"]+)">', doc))
    assert destinos == ancoras, f"navbar e seções divergem: {destinos ^ ancoras}"


def test_marca_aponta_para_o_topo(build_report):
    r = build_report.Relatorio()
    r.titulo("Panorama")
    doc = r.renderizar("Título")
    assert 'href="#topo"' in doc
    assert "id='topo'" in doc or 'id="topo"' in doc


# --------------------------------------------------------------------------- #
# Comportamento de leitura
# --------------------------------------------------------------------------- #

def test_h2_compensa_a_barra_fixa(build_report):
    """Sem scroll-margin-top o âncora para com o título escondido sob a navbar."""
    assert "scroll-margin-top" in build_report.CSS


def test_movimento_reduzido_e_respeitado(build_report):
    assert "prefers-reduced-motion" in build_report.CSS
    assert "prefers-reduced-motion" in build_report.JS


def test_realce_usa_posicao_e_nao_observer(build_report):
    """As seções têm alturas muito desiguais; observar entrada faria pular."""
    assert "offsetTop" in build_report.JS
    assert "IntersectionObserver" not in build_report.JS


def test_script_nao_depende_de_biblioteca_externa(build_report):
    assert "http" not in build_report.JS
