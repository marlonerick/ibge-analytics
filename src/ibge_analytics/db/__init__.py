"""Persistência dos dados do IBGE em PostgreSQL.

Camadas:
    engine   conexão e leitura dos arquivos .sql
    schema   aplica DDL (tabelas, índices, views)
    load     Parquet -> Postgres via COPY
    queries  consultas analíticas nomeadas -> DataFrame
    cli      `ibge-db` / `python -m ibge_analytics.db.cli`

O SQL mora em `sql/`, em arquivos, e não embutido em strings Python. É o
formato em que ele é lido, revisado e executado no psql — e a única forma de
não ter duas versões da mesma definição.
"""

from .engine import DatabaseIndisponivelError, criar_engine, url_do_ambiente

__all__ = ["criar_engine", "url_do_ambiente", "DatabaseIndisponivelError"]
