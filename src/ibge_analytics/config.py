"""Configuração central: caminhos, registro de agregados e constantes territoriais.

Todos os IDs de agregado/variável aqui foram verificados contra a API v3 em
2026-07-29 (endpoint /agregados/{id}/metadados). Ver docs/API_NOTES.md para as
peculiaridades encontradas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Caminhos
# --------------------------------------------------------------------------- #

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
GEO_DIR = DATA_DIR / "geo"

REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
CACHE_DIR = PROJECT_ROOT / ".cache"

for _d in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, GEO_DIR, REPORTS_DIR, FIGURES_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

BASE_V3 = "https://servicodados.ibge.gov.br/api/v3"
BASE_V1 = "https://servicodados.ibge.gov.br/api/v1"

AGREGADOS_URL = f"{BASE_V3}/agregados"
MALHAS_URL = f"{BASE_V3}/malhas"
LOCALIDADES_URL = f"{BASE_V1}/localidades"


# --------------------------------------------------------------------------- #
# Níveis territoriais (nomenclatura da API de agregados)
# --------------------------------------------------------------------------- #

class Nivel:
    BRASIL = "N1"
    REGIAO = "N2"
    UF = "N3"
    MESORREGIAO = "N8"
    MICRORREGIAO = "N9"
    MUNICIPIO = "N6"


NIVEL_LABEL = {
    "N1": "Brasil",
    "N2": "Grande Região",
    "N3": "Unidade da Federação",
    "N6": "Município",
    "N8": "Mesorregião",
    "N9": "Microrregião",
}


# --------------------------------------------------------------------------- #
# Registro de agregados (SIDRA v3)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Agregado:
    """Descreve um agregado do SIDRA e as variáveis que consumimos dele."""

    id: int
    nome: str
    variaveis: dict[int, str]
    niveis: tuple[str, ...]
    periodo_inicio: int
    periodo_fim: int
    #: Buracos conhecidos na série, apenas para documentação e testes — o
    #: pipeline resolve os anos consultando /periodos, que é a fonte da verdade
    #: (ver `api.agregados.anos_disponiveis`).
    periodos_ausentes: tuple[int, ...] = field(default=())

    @property
    def anos(self) -> list[int]:
        """Anos esperados. Use `anos_disponiveis()` para os anos reais da API."""
        return [
            a
            for a in range(self.periodo_inicio, self.periodo_fim + 1)
            if a not in self.periodos_ausentes
        ]


#: População residente estimada, anual. Base para série histórica e crescimento.
#: Quatro anos não são publicados: 2007 e 2010 (Contagem e Censo, em que o dado
#: vem da apuração e não da estimativa) e 2022-2023 (estimativa suspensa durante
#: a revisão pós-Censo 2022). São 21 anos de série, não 25.
POPULACAO_ESTIMADA = Agregado(
    id=6579,
    nome="População residente estimada",
    variaveis={9324: "populacao"},
    niveis=("N1", "N2", "N3", "N6"),
    periodo_inicio=2001,
    periodo_fim=2025,
    periodos_ausentes=(2007, 2010, 2022, 2023),
)

#: Censo 2022: população, área territorial e densidade demográfica.
#: Única fonte oficial que entrega área e densidade já calculada por município.
CENSO_2022 = Agregado(
    id=4714,
    nome="Censo 2022: população, área territorial e densidade demográfica",
    variaveis={
        93: "populacao_censo",
        6318: "area_km2",
        614: "densidade_hab_km2",
    },
    niveis=("N1", "N2", "N3", "N6"),
    periodo_inicio=2022,
    periodo_fim=2022,
)

#: PIB municipal e estadual a preços correntes + valor adicionado por setor.
PIB = Agregado(
    id=5938,
    nome="Produto Interno Bruto a preços correntes",
    variaveis={
        37: "pib_mil_reais",
        513: "vab_agropecuaria",
        517: "vab_industria",
        6575: "vab_servicos",
        525: "vab_administracao_publica",
        543: "impostos_liquidos",
    },
    niveis=("N1", "N2", "N3", "N6", "N8", "N9"),
    periodo_inicio=2002,
    periodo_fim=2023,
)

AGREGADOS: dict[str, Agregado] = {
    "populacao_estimada": POPULACAO_ESTIMADA,
    "censo_2022": CENSO_2022,
    "pib": PIB,
}


# --------------------------------------------------------------------------- #
# Limites operacionais da API
# --------------------------------------------------------------------------- #

#: A API rejeita respostas grandes com HTTP 500 (sem mensagem útil). O limite
#: não é de períodos, e sim do produto variáveis × períodos × localidades.
#: Medido em 2026-07-29 contra o agregado 5938 em nível municipal:
#:     33.420 células -> 200 (4,16 MB)      66.840 células -> 500
#: Adotamos 33.000 como teto seguro logo abaixo do último valor que passou.
MAX_CELULAS_POR_REQUISICAO = 33_000

#: Quantidade de localidades por nível — usada para dimensionar os lotes antes
#: de fazer a requisição, em vez de descobrir o estouro por tentativa e erro.
LOCALIDADES_POR_NIVEL = {
    "N1": 1,
    "N2": 5,
    "N3": 27,
    "N6": 5_570,
    "N8": 137,
    "N9": 558,
}

REQUEST_TIMEOUT = 180
MAX_RETRIES = 4
BACKOFF_FACTOR = 1.5

#: Cache em disco das respostas cruas. A API do IBGE é lenta (~5-15s por
#: requisição municipal) e os dados são anuais — cache agressivo é seguro.
CACHE_TTL_DIAS = 30


# --------------------------------------------------------------------------- #
# Regiões
# --------------------------------------------------------------------------- #

REGIOES = {
    1: "Norte",
    2: "Nordeste",
    3: "Sudeste",
    4: "Sul",
    5: "Centro-Oeste",
}

#: Ordem canônica para eixos e legendas (norte→sul, como o IBGE publica).
ORDEM_REGIOES = ["Norte", "Nordeste", "Sudeste", "Sul", "Centro-Oeste"]
