"""Conexão com o PostgreSQL e acesso aos arquivos .sql.

A URL vem do ambiente, nunca do código. Ordem de precedência:

    1. IBGE_DATABASE_URL
    2. as variáveis padrão do libpq (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE)
    3. os defaults de `PADROES` abaixo

Um arquivo `.env` na raiz do projeto é lido antes de tudo isso, para que a
senha fique fora do shell e fora do repositório (está no .gitignore).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

from ..config import PROJECT_ROOT

log = logging.getLogger(__name__)

SQL_DIR = PROJECT_ROOT / "sql"
SQL_ANALYTICS_DIR = SQL_DIR / "analytics"

#: Driver explícito: o dialeto `postgresql://` sozinho resolveria para
#: psycopg2, que não é dependência do projeto.
DRIVER = "postgresql+psycopg"

PADROES = {
    "host": "localhost",
    "port": "5432",
    "user": "postgres",
    "password": "",
    "dbname": "ibge",
}

#: Banco usado apenas para executar CREATE DATABASE — sempre existe numa
#: instalação padrão do PostgreSQL.
BANCO_MANUTENCAO = "postgres"


class DatabaseIndisponivelError(RuntimeError):
    """Não foi possível conectar ao PostgreSQL configurado."""


def carregar_dotenv(caminho: Path | None = None) -> dict[str, str]:
    """Lê um `.env` simples (KEY=VALUE) para o ambiente, sem sobrescrever.

    Não sobrescrever é deliberado: uma variável já exportada no shell vence o
    arquivo, que é o comportamento esperado ao apontar para outro banco numa
    execução pontual.

    Implementado à mão para não puxar python-dotenv só por isto. Suporta
    comentários, linhas em branco, `export ` como prefixo e aspas ao redor do
    valor — nada além disso.
    """
    caminho = caminho or PROJECT_ROOT / ".env"
    if not caminho.exists():
        return {}

    lidas: dict[str, str] = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.removeprefix("export ").partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        lidas[chave] = valor
        os.environ.setdefault(chave, valor)
    return lidas


def url_do_ambiente(dbname: str | None = None) -> str:
    """Monta a URL de conexão. `dbname` sobrepõe o banco, mantendo o resto."""
    carregar_dotenv()

    if (url := os.environ.get("IBGE_DATABASE_URL")) and dbname is None:
        return url

    host = os.environ.get("PGHOST", PADROES["host"])
    port = os.environ.get("PGPORT", PADROES["port"])
    user = os.environ.get("PGUSER", PADROES["user"])
    senha = os.environ.get("PGPASSWORD", PADROES["password"])
    banco = dbname or os.environ.get("PGDATABASE", PADROES["dbname"])

    # quote(): senhas com `@`, `/` ou `:` quebrariam o parsing da URL.
    credencial = quote(user, safe="")
    if senha:
        credencial += ":" + quote(senha, safe="")

    return f"{DRIVER}://{credencial}@{host}:{port}/{banco}"


def mascarar(url: str) -> str:
    """A URL sem a senha, para log e mensagem de erro."""
    if "@" not in url:
        return url
    credenciais, _, resto = url.rpartition("@")
    esquema, _, usuario = credenciais.partition("://")
    usuario = usuario.split(":", 1)[0]
    return f"{esquema}://{usuario}:***@{resto}"


@lru_cache(maxsize=4)
def criar_engine(url: str | None = None, *, autocommit: bool = False) -> Engine:
    """Engine SQLAlchemy, memoizada por URL.

    `autocommit` é necessário para CREATE DATABASE, que o PostgreSQL recusa
    dentro de um bloco de transação.
    """
    url = url or url_do_ambiente()
    engine = create_engine(
        url,
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT" if autocommit else "READ COMMITTED",
        future=True,
    )
    log.debug("engine: %s", mascarar(url))
    return engine


def testar_conexao(engine: Engine | None = None) -> str:
    """Devolve a versão do servidor ou levanta com uma mensagem acionável."""
    engine = engine or criar_engine()
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version()")).scalar_one()
    except OperationalError as erro:
        raise DatabaseIndisponivelError(
            f"não foi possível conectar em {mascarar(str(engine.url))}\n"
            f"  {erro.orig}\n\n"
            "Configure a conexão com um arquivo .env na raiz do projeto:\n"
            "    PGHOST=localhost\n"
            "    PGUSER=postgres\n"
            "    PGPASSWORD=sua-senha\n"
            "    PGDATABASE=ibge\n"
            "ou exporte IBGE_DATABASE_URL."
        ) from erro


def garantir_banco(dbname: str | None = None) -> bool:
    """Cria o banco se ele não existir. Devolve True se criou agora.

    Conecta no banco de manutenção porque não dá para criar um banco estando
    conectado a ele.
    """
    alvo = dbname or os.environ.get("PGDATABASE") or PADROES["dbname"]
    if url := os.environ.get("IBGE_DATABASE_URL"):
        alvo = url.rsplit("/", 1)[-1].split("?")[0]

    engine = criar_engine(url_do_ambiente(dbname=BANCO_MANUTENCAO), autocommit=True)
    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": alvo}
        ).scalar()
        if existe:
            return False
        # O nome do banco não pode ser parâmetro — só identificador. Vem da
        # configuração local, mas o regex barra qualquer coisa que não seja um
        # identificador simples antes de interpolar.
        if not alvo.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"nome de banco inválido: {alvo!r}")
        conn.execute(text(f'CREATE DATABASE "{alvo}" ENCODING \'UTF8\''))
        log.info("banco %s criado", alvo)
        return True


def ler_sql(nome: str) -> str:
    """Conteúdo de um arquivo de `sql/` (com ou sem a extensão)."""
    caminho = SQL_DIR / nome
    if caminho.suffix != ".sql":
        caminho = caminho.with_suffix(".sql")
    if not caminho.exists():
        raise FileNotFoundError(f"{caminho} não encontrado")
    return caminho.read_text(encoding="utf-8")
