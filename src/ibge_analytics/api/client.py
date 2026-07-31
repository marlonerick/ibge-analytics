"""Cliente HTTP para as APIs do IBGE.

Responsabilidades: sessão com retry/backoff, cache em disco das respostas e
logging. Nenhuma regra de negócio — os módulos de endpoint constroem as URLs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import (
    BACKOFF_FACTOR,
    CACHE_DIR,
    CACHE_TTL_DIAS,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
)

log = logging.getLogger(__name__)

_SEGUNDOS_POR_DIA = 86_400


class IBGEAPIError(RuntimeError):
    """Falha ao obter dados da API do IBGE após todas as tentativas."""


class IBGEClient:
    """Cliente com cache de disco para as APIs públicas do IBGE.

    O cache é indexado por hash da URL final (incluindo query string). Como os
    agregados do IBGE são anuais, um TTL longo é seguro e evita repetir
    requisições que custam 5-15s cada.
    """

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        use_cache: bool = True,
        ttl_dias: int = CACHE_TTL_DIAS,
        timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.use_cache = use_cache
        self.ttl_segundos = ttl_dias * _SEGUNDOS_POR_DIA
        self.timeout = timeout
        self.session = self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        # A API do IBGE devolve 500 intermitente sob carga; 502/503/504 também
        # aparecem. Retry cobre esses casos sem mascarar 4xx (erro nosso).
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.headers.update({"Accept": "application/json", "User-Agent": "ibge-analytics/0.1"})
        return session

    # ----------------------------------------------------------------- cache #

    def _cache_path(self, url: str, params: dict[str, Any] | None) -> Path:
        chave = url + "?" + json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(chave.encode("utf-8")).hexdigest()[:20]
        return self.cache_dir / f"{digest}.json"

    def _ler_cache(self, caminho: Path) -> Any | None:
        if not (self.use_cache and caminho.exists()):
            return None
        if time.time() - caminho.stat().st_mtime > self.ttl_segundos:
            log.debug("cache expirado: %s", caminho.name)
            return None
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Cache corrompido (ex.: escrita interrompida) — trata como miss.
            log.warning("cache ilegível, descartando: %s", caminho.name)
            return None

    def _escrever_cache(self, caminho: Path, payload: Any) -> None:
        if not self.use_cache:
            return
        # Escrita atômica: evita cache truncado se o processo morrer no meio.
        tmp = caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(caminho)

    # ------------------------------------------------------------------ http #

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET com cache. Levanta IBGEAPIError se a resposta não for utilizável."""
        caminho = self._cache_path(url, params)
        if (cached := self._ler_cache(caminho)) is not None:
            log.debug("cache hit: %s", url)
            return cached

        inicio = time.perf_counter()
        try:
            resposta = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise IBGEAPIError(f"falha de rede em {url}: {exc}") from exc

        decorrido = time.perf_counter() - inicio
        log.info("GET %s -> %s (%.1fs, %.2f MB)", resposta.url, resposta.status_code,
                 decorrido, len(resposta.content) / 1e6)

        if resposta.status_code != 200:
            raise IBGEAPIError(
                f"HTTP {resposta.status_code} em {resposta.url}: {resposta.text[:300]}"
            )

        try:
            payload = resposta.json()
        except ValueError as exc:
            raise IBGEAPIError(f"resposta não-JSON em {resposta.url}") from exc

        self._escrever_cache(caminho, payload)
        return payload

    def get_geojson(self, url: str, params: dict[str, Any] | None = None) -> dict:
        """GET de malha territorial. Mesma semântica de cache do get_json."""
        payload = self.get_json(url, params)
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise IBGEAPIError(f"esperado FeatureCollection em {url}, veio {type(payload)}")
        return payload


#: Cliente padrão compartilhado pelos módulos de endpoint.
_default_client: IBGEClient | None = None


def get_client() -> IBGEClient:
    global _default_client
    if _default_client is None:
        _default_client = IBGEClient()
    return _default_client
