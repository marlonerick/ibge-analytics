"""Linha de comando do banco.

    ibge-db check                       # conexão, inventário, índices
    ibge-db init                        # cria banco, schemas, tabelas, índices, views
    ibge-db init --recriar              # DESTRUTIVO: derruba os schemas antes
    ibge-db load                        # Parquet -> Postgres
    ibge-db refresh                     # recalcula as materialized views
    ibge-db sync                        # init + load + refresh
    ibge-db queries                     # lista as consultas analíticas
    ibge-db query concentracao
    ibge-db query top_municipios --metrica pib --limite 10
    ibge-db query serie_uf --uf SP --csv saida.csv
    ibge-db explain concentracao

Equivalente a `python -m ibge_analytics.db.cli`.
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from . import load, queries, schema
from .engine import (
    DatabaseIndisponivelError,
    criar_engine,
    garantir_banco,
    mascarar,
    testar_conexao,
    url_do_ambiente,
)

log = logging.getLogger("ibge_analytics.db")


def _saida_utf8() -> None:
    """Força UTF-8 no stdout.

    O console do Windows abre em cp1252, que não codifica nem o `─` das
    molduras nem os acentos dos nomes de município — e a saída morre com
    UnicodeEncodeError no meio de uma tabela. `errors="replace"` garante que um
    terminal antigo degrade para `?` em vez de derrubar o comando.
    """
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")


def _mostrar(df: pd.DataFrame, titulo: str = "") -> None:
    if titulo:
        print(f"\n{titulo}")
        print("─" * len(titulo))
    if df.empty:
        print("(sem resultados)")
        return
    with pd.option_context(
        "display.max_rows", 200,
        "display.max_columns", None,
        "display.width", 200,
        "display.float_format", lambda v: f"{v:,.2f}",
    ):
        print(df.to_string(index=False))
    print(f"\n{len(df)} linha(s)")


# --------------------------------------------------------------------------- #
# Comandos
# --------------------------------------------------------------------------- #

def cmd_check(args) -> int:
    print(f"conexão: {mascarar(url_do_ambiente())}")
    print(f"servidor: {testar_conexao().splitlines()[0]}")

    inventario = pd.DataFrame(schema.inventario())
    if inventario.empty:
        print("\nNenhum objeto em ibge/analytics — rode `ibge-db init`.")
        return 1
    _mostrar(inventario, "Objetos")

    if args.indices:
        _mostrar(pd.DataFrame(schema.indices()), "Índices")

    _mostrar(queries.executar("qualidade"), "Qualidade da carga")
    return 0


def cmd_init(args) -> int:
    if garantir_banco():
        print("banco criado")
    if args.recriar:
        # Destrutivo: apaga os dois schemas e tudo dentro deles.
        if not args.sim:
            resposta = input(
                "Isto apaga os schemas `ibge` e `analytics` inteiros. Digite 'sim' para seguir: "
            )
            if resposta.strip().lower() != "sim":
                print("cancelado")
                return 1
        schema.derrubar()
    schema.aplicar()
    _mostrar(pd.DataFrame(schema.inventario()), "Objetos criados")
    return 0


def cmd_load(args) -> int:
    resumo = load.carregar(truncar=not args.sem_truncate)
    _mostrar(resumo, "Carga")
    schema.atualizar_materializadas()
    print("materialized views atualizadas")
    return 0


def cmd_refresh(args) -> int:
    schema.atualizar_materializadas(concorrente=not args.bloqueante)
    print("materialized views atualizadas")
    return 0


def cmd_sync(args) -> int:
    garantir_banco()
    schema.aplicar()
    resumo = load.carregar()
    _mostrar(resumo, "Carga")
    schema.atualizar_materializadas()
    _mostrar(queries.executar("qualidade"), "Qualidade da carga")
    return 0


def cmd_queries(args) -> int:
    _mostrar(queries.listar(), "Consultas analíticas")
    return 0


def cmd_query(args) -> int:
    parametros = {}
    consulta = queries.obter(args.nome)
    for chave in consulta.parametros:
        valor = getattr(args, chave, None)
        if valor is not None:
            parametros[chave] = valor

    if args.sql:
        print(queries.sql_bruto(args.nome))
        return 0

    df = queries.executar(args.nome, **parametros)
    if args.csv:
        df.to_csv(args.csv, index=False, encoding="utf-8")
        print(f"{len(df)} linha(s) -> {args.csv}")
    else:
        _mostrar(df, f"{args.nome} — {consulta.descricao}")
    return 0


def cmd_explain(args) -> int:
    print(queries.plano(args.nome))
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ibge-db",
        description="Persistência e análise dos dados do IBGE em PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("check", help="testa a conexão e mostra o inventário")
    p.add_argument("--indices", action="store_true", help="inclui o uso dos índices")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("init", help="cria banco, schemas, tabelas, índices e views")
    p.add_argument("--recriar", action="store_true", help="DESTRUTIVO: derruba os schemas antes")
    p.add_argument("--sim", action="store_true", help="não pede confirmação para --recriar")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("load", help="carrega os Parquet de data/raw/ no banco")
    p.add_argument("--sem-truncate", action="store_true", help="não limpa as tabelas antes")
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("refresh", help="recalcula as materialized views")
    p.add_argument("--bloqueante", action="store_true", help="sem CONCURRENTLY")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("sync", help="init + load + refresh + qualidade")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("queries", help="lista as consultas analíticas")
    p.set_defaults(func=cmd_queries)

    p = sub.add_parser("query", help="executa uma consulta analítica")
    p.add_argument("nome", choices=sorted(queries.CONSULTAS))
    # Todos os parâmetros aceitos por qualquer consulta viram flags opcionais;
    # `cmd_query` repassa só os que a consulta escolhida declara.
    p.add_argument("--metrica", choices=["populacao", "pib", "pib_per_capita", "densidade", "crescimento"])
    p.add_argument("--limite", type=int)
    p.add_argument("--uf", help="sigla da UF (omitir = Brasil)")
    p.add_argument("--municipio", help="código IBGE de 7 dígitos ou nome")
    p.add_argument("--csv", metavar="ARQUIVO", help="grava o resultado em CSV")
    p.add_argument("--sql", action="store_true", help="mostra o SQL em vez de executar")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("explain", help="EXPLAIN ANALYZE de uma consulta")
    p.add_argument("nome", choices=sorted(queries.CONSULTAS))
    p.set_defaults(func=cmd_explain)

    return parser


def main(argv: list[str] | None = None) -> int:
    _saida_utf8()
    args = construir_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        return args.func(args) or 0
    except DatabaseIndisponivelError as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 2
    except load.ParquetAusenteError as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
