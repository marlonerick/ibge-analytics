"""Camada de acesso às APIs do IBGE."""

from .client import IBGEAPIError, IBGEClient, get_client

__all__ = ["IBGEClient", "IBGEAPIError", "get_client"]
