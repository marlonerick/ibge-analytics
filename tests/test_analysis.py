"""Testes das análises que consomem os painéis.

Duas famílias de teste:

* **regras de corte** — faixas de porte e de densidade, conferidas em
  DataFrames minúsculos escritos à mão, valor a valor sobre o limite;
* **leituras derivadas** — rankings, concentração e agregações regionais,
  rodadas sobre o painel que o pipeline monta em `conftest.py`, para que a
  análise seja testada com as mesmas colunas que recebe em produção.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ibge_analytics.analysis import crescimento as an_crescimento
from ibge_analytics.analysis import densidade as an_densidade
from ibge_analytics.analysis import pib as an_pib
from ibge_analytics.analysis import populacao as an_populacao


# --------------------------------------------------------------------------- #
# populacao — porte municipal
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "habitantes, faixa",
    [
        (0, "Até 5 mil"),
        (4_999, "Até 5 mil"),
        (5_000, "5 a 10 mil"),        # intervalos fechados à esquerda
        (19_999, "10 a 20 mil"),
        (20_000, "20 a 50 mil"),
        (100_000, "100 a 500 mil"),
        (499_999, "100 a 500 mil"),
        (500_000, "Mais de 500 mil"),
        (12_000_000, "Mais de 500 mil"),
    ],
)
def test_porte_classifica_pelo_limite_inferior(habitantes, faixa):
    df = pd.DataFrame({"populacao_atual": [float(habitantes)]})
    assert an_populacao.classificar_porte(df)["porte"].iloc[0] == faixa


def test_porte_de_populacao_ausente_fica_nulo():
    df = pd.DataFrame({"populacao_atual": pd.Series([None], dtype="float64")})
    assert pd.isna(an_populacao.classificar_porte(df)["porte"].iloc[0])


def test_faixas_e_rotulos_de_porte_estao_alinhados():
    """Um rótulo a mais (ou a menos) faria `pd.cut` levantar só em produção."""
    assert len(an_populacao.FAIXAS_PORTE) == len(an_populacao.ROTULOS_PORTE) + 1
    assert an_populacao.FAIXAS_PORTE == sorted(an_populacao.FAIXAS_PORTE)


def test_distribuicao_por_porte_fecha_em_cem_por_cento(painel):
    resumo = an_populacao.distribuicao_por_porte(painel)
    assert resumo["pct_municipios"].sum() == pytest.approx(100.0)
    assert resumo["pct_populacao"].sum() == pytest.approx(100.0)
    assert resumo["n_municipios"].sum() == len(painel)


def test_distribuicao_por_porte_separa_contagem_de_populacao(painel):
    """O contraste da rede urbana: muitos municípios pequenos, pouca gente."""
    resumo = an_populacao.distribuicao_por_porte(painel).set_index("porte")
    pequeno = resumo.loc["10 a 20 mil"]
    assert pequeno["n_municipios"] == 1
    assert pequeno["pct_municipios"] > pequeno["pct_populacao"]


# --------------------------------------------------------------------------- #
# populacao — rankings e concentração
# --------------------------------------------------------------------------- #

def test_ranking_traz_os_maiores_em_ordem(painel):
    top = an_populacao.ranking_municipios(painel, n=3)
    assert top["municipio_nome"].tolist() == ["São Paulo", "Rio de Janeiro", "Fortaleza"]
    assert top["populacao_atual"].is_monotonic_decreasing


def test_ranking_ascendente_traz_os_menores(painel):
    menores = an_populacao.ranking_municipios(painel, n=2, ascendente=True)
    assert menores["municipio_nome"].iloc[0] == "Alta Floresta D'Oeste"


def test_ranking_ignora_municipios_sem_o_indicador(painel):
    """Campinas não tem PIB — não pode aparecer como o último do ranking."""
    ranking = an_populacao.ranking_municipios(painel, n=99, coluna="pib_per_capita")
    assert "Campinas" not in ranking["municipio_nome"].tolist()
    assert len(ranking) == len(painel) - 1


def test_curva_de_lorenz_vai_de_zero_a_cem(painel):
    curva = an_populacao.curva_lorenz(painel)
    assert len(curva) == len(painel)
    assert curva["pct_municipios"].iloc[-1] == pytest.approx(100.0)
    assert curva["pct_populacao"].iloc[-1] == pytest.approx(100.0)
    # Acumulados são monótonos por construção.
    assert curva["pct_populacao"].is_monotonic_increasing


def test_curva_de_lorenz_fica_abaixo_da_diagonal(painel):
    """Qualquer distribuição desigual acumula menos que a proporção de unidades."""
    curva = an_populacao.curva_lorenz(painel)
    assert (curva["pct_populacao"] <= curva["pct_municipios"] + 1e-9).all()


def test_metricas_de_concentracao_descrevem_a_populacao(painel):
    metricas = an_populacao.metricas_concentracao(painel)
    assert metricas["n"] == len(painel)
    assert 0 < metricas["gini"] < 1
    assert metricas["share_top_10pct"] == pytest.approx(
        painel["populacao_atual"].max() / painel["populacao_atual"].sum() * 100
    )


def test_serie_nacional_soma_as_ufs_ano_a_ano(paineis):
    serie = an_populacao.serie_nacional(paineis["populacao"]["ufs"])
    assert serie["ano"].tolist() == [2020, 2021, 2024, 2025]
    assert serie["populacao"].iloc[-1] == pytest.approx(
        paineis["populacao"]["ufs"].query("ano == 2025")["populacao"].sum()
    )
    # O primeiro ano não tem variação de que falar.
    assert pd.isna(serie["variacao_pct"].iloc[0])
    assert serie["variacao_pct"].iloc[1] == pytest.approx(
        (serie["populacao"].iloc[1] / serie["populacao"].iloc[0] - 1) * 100
    )


# --------------------------------------------------------------------------- #
# crescimento
# --------------------------------------------------------------------------- #

@pytest.fixture
def crescimento(paineis) -> pd.DataFrame:
    return paineis["populacao"]["crescimento_municipios"]


def test_declinio_pega_so_quem_perdeu_gente(crescimento):
    declinio = an_crescimento.municipios_em_declinio(crescimento)
    assert set(declinio["municipio_nome"]) == {"Alta Floresta D'Oeste", "Porto Alegre"}
    assert (declinio["variacao_absoluta"] < 0).all()
    # Do que mais encolhe para o que menos encolhe.
    assert declinio["cagr_pct"].is_monotonic_increasing


def test_resumo_de_declinio_conta_e_soma(crescimento):
    resumo = an_crescimento.resumo_declinio(crescimento)
    assert resumo["total_municipios"] == len(crescimento)
    assert resumo["n_perdendo"] == 2
    assert resumo["pct_perdendo"] == pytest.approx(2 / len(crescimento) * 100)
    # População perdida é reportada como número positivo.
    assert resumo["populacao_perdida"] > 0
    assert resumo["populacao_perdida"] == pytest.approx(
        -crescimento.query("variacao_absoluta < 0")["variacao_absoluta"].sum()
    )


def test_resumo_de_declinio_sem_municipios_nao_divide_por_zero():
    vazio = pd.DataFrame({"variacao_absoluta": [], "cagr_pct": []})
    resumo = an_crescimento.resumo_declinio(vazio)
    assert resumo["pct_perdendo"] == 0.0
    assert resumo["populacao_perdida"] == 0.0


def test_top_crescimento_descarta_municipios_minusculos():
    """Sair de 800 para 1.600 habitantes é +100% e não é crescimento comparável."""
    df = pd.DataFrame(
        {
            "municipio_nome": ["Vilarejo", "Cidade Média"],
            "uf_sigla": ["MT", "GO"],
            "regiao_nome": ["Centro-Oeste", "Centro-Oeste"],
            "valor_inicial": [800.0, 100_000.0],
            "valor_final": [1_600.0, 130_000.0],
            "cagr_pct": [7.2, 2.7],
        }
    )
    top = an_crescimento.top_crescimento(df, n=5)
    assert top["municipio_nome"].tolist() == ["Cidade Média"]


def test_top_crescimento_e_top_declinio_sao_as_duas_pontas(crescimento):
    topo = an_crescimento.top_crescimento(crescimento, n=2, populacao_minima=0)
    fundo = an_crescimento.top_declinio(crescimento, n=2, populacao_minima=0)
    assert topo["cagr_pct"].is_monotonic_decreasing
    assert fundo["cagr_pct"].is_monotonic_increasing
    assert topo["cagr_pct"].iloc[0] > fundo["cagr_pct"].iloc[0]


def test_crescimento_por_regiao_e_agregado_e_nao_mediano(crescimento):
    """O crescimento da região é a soma das populações, não a mediana dos CAGRs."""
    por_regiao = an_crescimento.crescimento_por_regiao(crescimento).set_index("regiao_nome")
    sudeste = por_regiao.loc["Sudeste"]
    municipios_sudeste = crescimento.query("regiao_nome == 'Sudeste'")

    assert sudeste["n_municipios"] == len(municipios_sudeste)
    assert sudeste["populacao_final"] == pytest.approx(municipios_sudeste["valor_final"].sum())
    assert sudeste["crescimento_regional_pct"] == pytest.approx(
        (municipios_sudeste["valor_final"].sum() / municipios_sudeste["valor_inicial"].sum() - 1)
        * 100
    )


def test_crescimento_por_regiao_conta_quem_encolhe(crescimento):
    por_regiao = an_crescimento.crescimento_por_regiao(crescimento).set_index("regiao_nome")
    assert por_regiao.loc["Sul", "n_perdendo"] == 1
    assert por_regiao.loc["Sul", "pct_perdendo"] == pytest.approx(100.0)
    assert por_regiao.loc["Sudeste", "n_perdendo"] == 0


def test_distribuicao_de_faixas_fecha_em_cem(crescimento):
    faixas = an_crescimento.distribuicao_faixas(crescimento)
    assert faixas["pct_municipios"].sum() == pytest.approx(100.0)
    assert faixas["n_municipios"].sum() == len(crescimento)


def test_serie_indexada_comeca_em_cem(paineis):
    serie = an_crescimento.serie_indexada(
        paineis["populacao"]["municipios"], chave="municipio_id"
    )
    primeiro_ano = serie[serie["ano"] == serie["ano"].min()]
    assert primeiro_ano["indice"].round(6).eq(100.0).all()


def test_serie_indexada_torna_comparaveis_tamanhos_diferentes(paineis):
    """O índice mede trajetória, não tamanho: quem encolhe cai abaixo de 100."""
    serie = an_crescimento.serie_indexada(
        paineis["populacao"]["municipios"], chave="municipio_id"
    )
    fim = serie[serie["ano"] == serie["ano"].max()].set_index("municipio_id")["indice"]
    assert fim.loc["1100015"] < 100  # Alta Floresta D'Oeste encolhe
    assert fim.loc["5208707"] > 100  # Goiânia cresce


def test_serie_indexada_aceita_outro_ano_base(paineis):
    serie = an_crescimento.serie_indexada(
        paineis["populacao"]["municipios"], chave="municipio_id", ano_base=2024
    )
    assert serie.query("ano == 2024")["indice"].round(6).eq(100.0).all()
    assert serie.query("ano == 2020")["indice"].max() > 100


# --------------------------------------------------------------------------- #
# pib
# --------------------------------------------------------------------------- #

def test_ranking_de_ufs_vem_do_maior_para_o_menor(paineis):
    ranking = an_pib.ranking_ufs(paineis["ufs"])
    assert ranking["pib_mil_reais"].is_monotonic_decreasing
    assert ranking["uf_sigla"].iloc[0] == "SP"


def test_ranking_de_ufs_ignora_coluna_que_a_tabela_nao_tem(paineis):
    """A mesma função serve a tabelas mais pobres (ex.: série histórica)."""
    magra = paineis["ufs"][["uf_sigla", "uf_nome", "regiao_nome", "pib_mil_reais"]]
    ranking = an_pib.ranking_ufs(magra)
    assert "part_pib_brasil" not in ranking.columns
    assert len(ranking) == len(magra)


def test_estrutura_setorial_sai_em_formato_longo(paineis):
    longo = an_pib.estrutura_setorial(paineis["ufs"])
    assert set(longo["setor"]) == {
        "Agropecuária", "Indústria", "Serviços", "Administração pública"
    }
    assert len(longo) == len(paineis["ufs"]) * 4
    # A participação de cada UF continua fechando em 100%.
    por_uf = longo.groupby("uf_sigla", observed=True)["participacao"].sum()
    assert por_uf.round(6).eq(100.0).all()


def test_descolamento_compara_fatia_de_pib_com_fatia_de_gente(paineis):
    descolamento = an_pib.descolamento_pib_populacao(paineis["ufs"])
    assert descolamento["razao_pib_pop"].is_monotonic_decreasing
    linha = descolamento.iloc[0]
    assert linha["razao_pib_pop"] == pytest.approx(
        linha["part_pib_brasil"] / linha["part_pop_brasil"]
    )


def test_evolucao_da_participacao_fecha_cem_em_cada_ano(paineis):
    evolucao = an_pib.evolucao_participacao(paineis["pib"]["ufs"])
    por_ano = evolucao.groupby("ano")["part_pib_brasil"].sum()
    assert por_ano.round(6).eq(100.0).all()


def test_evolucao_regional_fecha_cem_em_cada_ano(paineis):
    regional = an_pib.evolucao_participacao_regional(paineis["pib"]["ufs"])
    por_ano = regional.groupby("ano")["part_pib_brasil"].sum()
    assert por_ano.round(6).eq(100.0).all()
    assert regional["regiao_nome"].nunique() == 5


def test_concentracao_municipal_conta_quantos_somam_metade_do_pib(painel):
    resumo = an_pib.resumo_concentracao_municipal(painel)
    # Um único município responde por mais da metade do PIB sintético.
    assert resumo["n_municipios_metade_pib"] == 1
    assert resumo["share_top_10"] == pytest.approx(100.0)
    # Traz junto as métricas de concentração genéricas.
    assert 0 < resumo["gini"] < 1
    assert resumo["n"] == painel["pib_mil_reais"].notna().sum()


def test_top_municipios_pib_lista_os_maiores(painel):
    top = an_pib.top_municipios_pib(painel, n=3)
    assert top["municipio_nome"].tolist() == ["São Paulo", "Rio de Janeiro", "Porto Alegre"]
    assert top["pib_mil_reais"].is_monotonic_decreasing
    # Quem não tem PIB nunca entra no topo.
    assert an_pib.top_municipios_pib(painel, n=6)["pib_mil_reais"].notna().all()


# --------------------------------------------------------------------------- #
# densidade
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "hab_km2, faixa",
    [
        (0.0, "Muito baixa (<1)"),
        (0.99, "Muito baixa (<1)"),
        (1.0, "Baixa (1–5)"),
        (5.0, "Média-baixa (5–25)"),
        (24.99, "Média-baixa (5–25)"),
        (25.0, "Média (25–100)"),
        (100.0, "Alta (100–500)"),
        (500.0, "Muito alta (>500)"),
        (13_000.0, "Muito alta (>500)"),
    ],
)
def test_densidade_classifica_pelo_limite_inferior(hab_km2, faixa):
    df = pd.DataFrame({"densidade_atual": [hab_km2]})
    assert an_densidade.classificar(df)["faixa_densidade"].iloc[0] == faixa


def test_faixas_e_rotulos_de_densidade_estao_alinhados():
    assert len(an_densidade.FAIXAS_DENSIDADE) == len(an_densidade.ROTULOS_DENSIDADE) + 1
    assert an_densidade.FAIXAS_DENSIDADE == sorted(an_densidade.FAIXAS_DENSIDADE)


def test_distribuicao_de_densidade_fecha_em_cem(painel):
    dist = an_densidade.distribuicao(painel)
    assert dist["pct_area"].sum() == pytest.approx(100.0)
    assert dist["pct_populacao"].sum() == pytest.approx(100.0)
    assert dist["n_municipios"].sum() == len(painel)


def test_faixa_mais_vazia_tem_muita_area_e_pouca_gente(painel):
    """O retrato da ocupação desigual, que a análise existe para mostrar."""
    dist = an_densidade.distribuicao(painel).set_index("faixa_densidade")
    vazia = dist.loc["Baixa (1–5)"]
    assert vazia["pct_area"] > vazia["pct_populacao"]


def test_extremos_devolve_as_tres_pontas(painel):
    pontas = an_densidade.extremos(painel, n=2)
    assert set(pontas) == {"mais_densos", "mais_vazios", "maiores_areas"}
    assert pontas["mais_densos"]["densidade_atual"].is_monotonic_decreasing
    assert pontas["mais_vazios"]["densidade_atual"].is_monotonic_increasing
    assert pontas["mais_vazios"]["municipio_nome"].iloc[0] == "Alta Floresta D'Oeste"
    assert pontas["maiores_areas"]["area_km2"].iloc[0] == painel["area_km2"].max()


def test_extremos_nao_confunde_densidade_ausente_com_zero(painel):
    """Sem `dropna`, um município sem área apareceria como o mais vazio do país."""
    painel = painel.copy()
    painel.loc[painel["municipio_nome"] == "Goiânia", "densidade_atual"] = None
    vazios = an_densidade.extremos(painel, n=3)["mais_vazios"]
    assert "Goiânia" not in vazios["municipio_nome"].tolist()


def test_concentracao_territorial_mede_area_da_metade_da_populacao(painel):
    resumo = an_densidade.concentracao_territorial(painel)
    assert 1 <= resumo["n_municipios_metade_pop"] <= len(painel)
    assert resumo["area_metade_pop_km2"] <= resumo["area_total_km2"]
    assert resumo["pct_area_metade_pop"] == pytest.approx(
        resumo["area_metade_pop_km2"] / resumo["area_total_km2"] * 100
    )
    # Metade da população cabe numa fração pequena do território.
    assert resumo["pct_area_metade_pop"] < 50


def test_densidade_por_regiao_traz_as_parcelas(paineis):
    regional = an_densidade.densidade_por_regiao(paineis["regioes"])
    assert regional["part_area_brasil"].sum() == pytest.approx(100.0)
    assert regional["part_pop_brasil"].sum() == pytest.approx(100.0)
    assert len(regional) == 5
