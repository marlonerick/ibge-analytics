"""Testes da camada de banco.

Divididos em dois blocos:

* **offline** — configuração, preparo dos DataFrames para o COPY, registro de
  consultas e coerência entre os cortes do SQL e os do pandas. Rodam sempre.
* **`@pytest.mark.postgres`** — exigem um PostgreSQL alcançável. São pulados
  automaticamente quando não há conexão, para que `pytest` continue verde numa
  máquina sem banco:

      pytest -m postgres
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from ibge_analytics.analysis.populacao import FAIXAS_PORTE, ROTULOS_PORTE
from ibge_analytics.db import engine as db_engine
from ibge_analytics.db import load, queries, schema
from ibge_analytics.etl import transform

#: Guardada antes de qualquer mock para que os testes do próprio `.env` possam
#: recuperar a implementação real.
_CARREGAR_DOTENV_REAL = db_engine.carregar_dotenv


# --------------------------------------------------------------------------- #
# engine — configuração da conexão
# --------------------------------------------------------------------------- #

@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Isola os testes das variáveis de conexão da máquina real."""
    for var in ("IBGE_DATABASE_URL", "PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"):
        monkeypatch.delenv(var, raising=False)
    # Impede que o .env do desenvolvedor vaze para dentro do teste.
    monkeypatch.setattr(db_engine, "carregar_dotenv", lambda *a, **k: {})


def test_url_usa_padroes_quando_ambiente_vazio():
    assert db_engine.url_do_ambiente() == "postgresql+psycopg://postgres@localhost:5432/ibge"


def test_url_respeita_variaveis_do_libpq(monkeypatch):
    monkeypatch.setenv("PGHOST", "db.interno")
    monkeypatch.setenv("PGUSER", "analista")
    monkeypatch.setenv("PGPASSWORD", "segredo")
    monkeypatch.setenv("PGDATABASE", "censo")
    assert db_engine.url_do_ambiente() == (
        "postgresql+psycopg://analista:segredo@db.interno:5432/censo"
    )


def test_url_escapa_caracteres_especiais_da_senha(monkeypatch):
    """Senha com @ ou / quebraria o parsing da URL se não fosse escapada."""
    monkeypatch.setenv("PGPASSWORD", "p@ss/w:rd")
    url = db_engine.url_do_ambiente()
    assert "p%40ss%2Fw%3Ard" in url
    assert url.count("@") == 1


def test_url_completa_tem_precedencia(monkeypatch):
    monkeypatch.setenv("PGHOST", "ignorado")
    monkeypatch.setenv("IBGE_DATABASE_URL", "postgresql+psycopg://u@h:5433/d")
    assert db_engine.url_do_ambiente() == "postgresql+psycopg://u@h:5433/d"


def test_dbname_explicito_ignora_a_url_completa(monkeypatch):
    """`garantir_banco` precisa conectar em `postgres`, não no banco alvo."""
    monkeypatch.setenv("IBGE_DATABASE_URL", "postgresql+psycopg://u@h:5433/ibge")
    assert db_engine.url_do_ambiente(dbname="postgres").endswith("/postgres")


def test_mascarar_esconde_a_senha():
    mascarada = db_engine.mascarar("postgresql+psycopg://user:s3cr3t@host:5432/ibge")
    assert "s3cr3t" not in mascarada
    assert mascarada == "postgresql+psycopg://user:***@host:5432/ibge"


def test_dotenv_nao_sobrescreve_o_ambiente(tmp_path, monkeypatch):
    """Uma variável já exportada no shell vence o arquivo."""
    import os

    # `carregar_dotenv` está mockada pelo fixture autouse; aqui queremos a real.
    monkeypatch.setattr(db_engine, "carregar_dotenv", _CARREGAR_DOTENV_REAL)

    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "# comentário\n\nPGHOST=do-arquivo\nexport PGUSER='aspas'\nPGPORT=\"5433\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PGHOST", "do-shell")

    db_engine.carregar_dotenv(arquivo)

    assert os.environ["PGHOST"] == "do-shell"  # o shell vence o arquivo
    assert os.environ["PGUSER"] == "aspas"     # `export ` e aspas simples removidos
    assert os.environ["PGPORT"] == "5433"      # aspas duplas removidas


def test_dotenv_ausente_nao_falha(tmp_path, monkeypatch):
    monkeypatch.setattr(db_engine, "carregar_dotenv", _CARREGAR_DOTENV_REAL)
    assert db_engine.carregar_dotenv(tmp_path / "nao-existe.env") == {}


# --------------------------------------------------------------------------- #
# load — preparo dos dados para o COPY
# --------------------------------------------------------------------------- #

def test_codigo_de_municipio_mantem_sete_digitos():
    """O Parquet guarda o código como int64 e perde o zero à esquerda."""
    fonte = load.Fonte("t", "p", ("municipio_id", "ano", "populacao"), nivel="municipio")
    bruto = pd.DataFrame({"localidade_id": [1100015, 3550308], "ano": [2025, 2025], "populacao": [22.0, 11.0]})
    preparado = load.preparar(bruto, fonte)
    assert preparado["municipio_id"].tolist() == ["1100015", "3550308"]
    assert preparado["municipio_id"].str.len().eq(7).all()


def test_chave_de_uf_vira_inteiro():
    fonte = load.Fonte("t", "p", ("uf_id", "ano", "populacao"), nivel="uf")
    bruto = pd.DataFrame({"localidade_id": ["35", "11"], "ano": [2025, 2025], "populacao": [1.0, 2.0]})
    preparado = load.preparar(bruto, fonte)
    assert preparado["uf_id"].tolist() == [35, 11]


def test_colunas_inteiras_perdem_o_ponto_flutuante():
    """"12345.0" não é um bigint válido para o COPY."""
    fonte = load.Fonte("t", "p", ("uf_id", "ano", "populacao"), nivel="uf")
    bruto = pd.DataFrame({"localidade_id": ["35"], "ano": [2025], "populacao": [46_000_000.0]})
    csv = load._para_csv(load.preparar(bruto, fonte))
    assert csv.strip() == "35,2025,46000000"


def test_nulo_vira_campo_vazio_no_csv():
    fonte = load.Fonte("t", "p", ("uf_id", "ano", "populacao"), nivel="uf")
    bruto = pd.DataFrame({"localidade_id": ["35"], "ano": [2025], "populacao": [None]})
    assert load._para_csv(load.preparar(bruto, fonte)).strip() == "35,2025,"


def test_coluna_faltante_falha_com_o_nome_do_arquivo():
    fonte = load.Fonte("t", "pop_ufs", ("uf_id", "ano", "populacao"), nivel="uf")
    with pytest.raises(KeyError, match="pop_ufs"):
        load.preparar(pd.DataFrame({"localidade_id": ["35"], "ano": [2025]}), fonte)


def test_dimensoes_sao_carregadas_antes_dos_fatos():
    """As FKs são checadas durante o COPY — a ordem do registro importa."""
    ordem = [f.tabela for f in load.FONTES]
    ultima_dimensao = max(i for i, t in enumerate(ordem) if ".dim_" in t)
    primeiro_fato = min(i for i, t in enumerate(ordem) if ".fato_" in t)
    assert ultima_dimensao < primeiro_fato


def test_regiao_carrega_antes_de_uf_que_carrega_antes_de_municipio():
    ordem = [f.tabela for f in load.FONTES]
    assert ordem.index("ibge.dim_regiao") < ordem.index("ibge.dim_uf") < ordem.index("ibge.dim_municipio")


def test_toda_fonte_aponta_para_um_parquet_do_pipeline():
    from ibge_analytics.etl import extract  # noqa: F401  (garante que RAW_DIR existe)

    nomes = {f.parquet for f in load.FONTES}
    assert "pop_municipios" in nomes and "pib_municipios" in nomes and "dim_municipios" in nomes


# --------------------------------------------------------------------------- #
# queries — registro
# --------------------------------------------------------------------------- #

def test_toda_consulta_registrada_tem_arquivo():
    for consulta in queries.CONSULTAS.values():
        assert consulta.caminho.exists(), f"{consulta.caminho} não existe"


def test_todo_arquivo_sql_esta_registrado():
    """Um .sql órfão em sql/analytics/ é código morto — o teste o denuncia."""
    em_disco = {p.stem for p in db_engine.SQL_ANALYTICS_DIR.glob("*.sql")}
    assert em_disco == set(queries.CONSULTAS)


def test_parametros_declarados_aparecem_no_sql():
    for consulta in queries.CONSULTAS.values():
        sql = consulta.sql()
        for parametro in consulta.parametros:
            assert f":{parametro}" in sql, f"{consulta.nome} declara :{parametro} mas não o usa"


def test_sql_nao_usa_parametro_nao_declarado():
    """Um :bind não declarado só apareceria como erro em tempo de execução.

    A extração vem do próprio SQLAlchemy, e não de um regex: é ele quem
    interpreta o SQL na hora de executar, então é a única fonte que não
    confunde `::text` nem um `"ano:valor"` dentro de um comentário.
    """
    from sqlalchemy import text as sa_text

    for consulta in queries.CONSULTAS.values():
        usados = set(sa_text(consulta.sql())._bindparams)
        assert usados == set(consulta.parametros), (
            f"{consulta.nome}: SQL usa {sorted(usados)}, "
            f"registro declara {sorted(consulta.parametros)}"
        )


def test_consulta_desconhecida_lista_as_disponiveis():
    with pytest.raises(queries.ConsultaDesconhecidaError, match="concentracao"):
        queries.obter("nao_existe")


def test_parametro_indevido_e_rejeitado():
    with pytest.raises(TypeError, match="uf"):
        queries.executar("concentracao", uf="SP")


def test_arquivos_ddl_existem_na_ordem_declarada():
    for arquivo in schema.ARQUIVOS_DDL:
        assert (db_engine.SQL_DIR / arquivo).exists()


# --------------------------------------------------------------------------- #
# Coerência entre o SQL e o pandas
#
# As mesmas faixas estão escritas duas vezes — em CASE no SQL e em pd.cut no
# Python. Estes testes travam a duplicação: se alguém mexer num lado, o outro
# tem de acompanhar.
# --------------------------------------------------------------------------- #

def test_faixas_de_crescimento_do_sql_batem_com_as_do_pandas():
    sql = (db_engine.SQL_DIR / "03_views.sql").read_text(encoding="utf-8")
    for rotulo in transform.classificar_crescimento(
        pd.DataFrame({"cagr_pct": [-1.0, -0.2, 0.2, 0.7, 2.0]})
    )["faixa_crescimento"]:
        assert f"'{rotulo}'" in sql


def test_cortes_de_crescimento_do_sql_batem_com_os_do_pandas():
    """Valores exatamente nos limites: pd.cut usa intervalos fechados à direita."""
    cortes = [-0.5, 0.0, 0.5, 1.0]
    esperado = transform.classificar_crescimento(pd.DataFrame({"cagr_pct": cortes}))
    assert esperado["faixa_crescimento"].tolist() == [
        "Perda acentuada",
        "Perda leve",
        "Crescimento lento",
        "Crescimento moderado",
    ]
    sql = (db_engine.SQL_DIR / "03_views.sql").read_text(encoding="utf-8")
    for corte in cortes:
        assert f"<= {corte:>4.1f}" in sql or f"<=  {corte:.1f}" in sql or f"<= {corte:.1f}" in sql


def test_faixas_de_porte_do_sql_batem_com_as_do_pandas():
    sql = (db_engine.SQL_DIR / "03_views.sql").read_text(encoding="utf-8")
    for rotulo in ROTULOS_PORTE:
        assert f"'{rotulo}'" in sql
    for limite in FAIXAS_PORTE[1:-1]:
        assert str(int(limite)) in sql


# --------------------------------------------------------------------------- #
# Integração — exigem PostgreSQL
# --------------------------------------------------------------------------- #

@pytest.fixture
def conexao(monkeypatch):
    """Engine real, ou skip se não houver banco.

    O fixture autouse zera as variáveis de conexão e mocka o leitor de `.env`;
    aqui os dois são desfeitos, porque estes testes precisam justamente da
    configuração real da máquina.
    """
    monkeypatch.setattr(db_engine, "carregar_dotenv", _CARREGAR_DOTENV_REAL)
    db_engine.carregar_dotenv()
    try:
        motor = db_engine.criar_engine(db_engine.url_do_ambiente())
        db_engine.testar_conexao(motor)
    except Exception as erro:  # noqa: BLE001 — qualquer falha de conexão pula
        pytest.skip(f"PostgreSQL indisponível: {erro}")
    return motor


@pytest.mark.postgres
def test_schemas_existem(conexao):
    objetos = {linha["objeto"] for linha in schema.inventario(conexao)}
    assert "ibge.dim_municipio" in objetos
    assert "analytics.mv_painel_municipio" in objetos


@pytest.mark.postgres
def test_painel_tem_uma_linha_por_municipio(conexao):
    from sqlalchemy import text

    with conexao.connect() as conn:
        painel = conn.execute(text("SELECT count(*) FROM analytics.mv_painel_municipio")).scalar_one()
        dim = conn.execute(text("SELECT count(*) FROM ibge.dim_municipio")).scalar_one()
    assert painel == dim


@pytest.mark.postgres
def test_qualidade_sem_falhas(conexao):
    resultado = queries.executar("qualidade", engine=conexao)
    falhas = resultado[resultado["status"] == "FALHA"]
    assert falhas.empty, falhas.to_string(index=False)


@pytest.mark.postgres
def test_toda_consulta_registrada_executa(conexao):
    for nome in queries.CONSULTAS:
        df = queries.executar(nome, engine=conexao)
        assert not df.empty, f"{nome} devolveu vazio"


@pytest.mark.postgres
def test_cagr_do_sql_bate_com_o_do_pandas(conexao):
    """A mesma métrica calculada nos dois lugares tem de dar o mesmo número."""
    from sqlalchemy import text

    from ibge_analytics.utils import io as uio

    with conexao.connect() as conn:
        do_banco = pd.read_sql_query(
            text(
                "SELECT municipio_id, cagr_pct FROM analytics.vw_crescimento_municipio"
                " WHERE cagr_pct IS NOT NULL ORDER BY municipio_id"
            ),
            conn,
        )
    do_pandas = uio.carregar("crescimento_municipios")[["municipio_id", "cagr_pct"]].dropna()

    juntos = do_banco.merge(do_pandas, on="municipio_id", suffixes=("_sql", "_pd"))
    assert len(juntos) > 5_000
    # Tolerância de 1e-3 p.p.: o SQL arredonda em 4 casas na view.
    assert (juntos["cagr_pct_sql"].astype(float) - juntos["cagr_pct_pd"]).abs().max() < 1e-3


@pytest.mark.postgres
def test_concentracao_do_pib_e_extrema(conexao):
    """Trava o achado central: metade do PIB sai de pouquíssimos municípios."""
    resultado = queries.executar("concentracao", engine=conexao)
    meio = resultado.query("metrica == 'pib' and pct_alvo == 50").iloc[0]
    assert meio["n_municipios"] < 200
    assert meio["pct_dos_municipios"] < 5
