"""API de Malhas v3 — geometrias GeoJSON para os mapas.

As features vêm com uma única propriedade, `codarea`, contendo o código IBGE da
área. É por ela que os mapas fazem o join com os dados.

Qualidade da malha: 'minima' (~100 KB para as 27 UFs) é suficiente para
coropléticos de tela; 'maxima' passa de 10 MB e trava o navegador.
"""

from __future__ import annotations

import json
import logging

from ..config import GEO_DIR, MALHAS_URL
from .client import IBGEClient, get_client

log = logging.getLogger(__name__)

FORMATO_GEOJSON = "application/vnd.geo+json"


def malha_ufs(qualidade: str = "minima", client: IBGEClient | None = None) -> dict:
    """Brasil dividido nas 27 UFs. `codarea` = código da UF (2 dígitos)."""
    client = client or get_client()
    return client.get_geojson(
        f"{MALHAS_URL}/paises/BR",
        params={"formato": FORMATO_GEOJSON, "qualidade": qualidade, "intrarregiao": "UF"},
    )


def malha_regioes(qualidade: str = "minima", client: IBGEClient | None = None) -> dict:
    """Brasil dividido nas 5 grandes regiões. `codarea` = código da região."""
    client = client or get_client()
    return client.get_geojson(
        f"{MALHAS_URL}/paises/BR",
        params={"formato": FORMATO_GEOJSON, "qualidade": qualidade, "intrarregiao": "regiao"},
    )


def malha_municipios_uf(
    uf_id: int | str, qualidade: str = "minima", client: IBGEClient | None = None
) -> dict:
    """Municípios de uma UF. `codarea` = código do município (7 dígitos)."""
    client = client or get_client()
    return client.get_geojson(
        f"{MALHAS_URL}/estados/{uf_id}",
        params={"formato": FORMATO_GEOJSON, "qualidade": qualidade, "intrarregiao": "municipio"},
    )


def malha_municipios_brasil(
    ufs: list[int], qualidade: str = "minima", client: IBGEClient | None = None
) -> dict:
    """Junta as malhas municipais de várias UFs numa só FeatureCollection.

    Não existe endpoint nacional de municípios — a API só entrega por UF, então
    baixamos as 27 e concatenamos.
    """
    features: list[dict] = []
    for uf in ufs:
        malha = malha_municipios_uf(uf, qualidade=qualidade, client=client)
        features.extend(malha["features"])
    log.info("malha municipal nacional: %d features de %d UFs", len(features), len(ufs))
    return {"type": "FeatureCollection", "features": features}


def salvar(malha: dict, nome: str) -> None:
    """Persiste uma malha em data/geo/ para uso offline pelo dashboard."""
    destino = GEO_DIR / f"{nome}.geojson"
    destino.write_text(json.dumps(malha), encoding="utf-8")
    log.info("malha salva: %s (%.2f MB)", destino.name, destino.stat().st_size / 1e6)


def carregar(nome: str) -> dict:
    return json.loads((GEO_DIR / f"{nome}.geojson").read_text(encoding="utf-8"))
