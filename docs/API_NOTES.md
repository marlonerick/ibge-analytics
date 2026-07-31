# Notas de campo — APIs do IBGE

Comportamentos reais das APIs, medidos contra os endpoints de produção em
**2026-07-29**. Nenhum deles está documentado no manual oficial; todos custaram
uma sessão de depuração e estão travados por teste.

---

## 1. O limite de tamanho da resposta não é de períodos — é de células

`GET /agregados/{id}/periodos/{p}/variaveis/{v}?localidades=N6` devolve
**HTTP 500 com corpo `{"statusCode":500,"message":"Internal server error"}`**
quando a resposta fica grande demais. Não há mensagem indicando o motivo, e o
erro volta em ~0,5 s — é uma rejeição antecipada, não um timeout.

O custo de uma requisição é `variáveis × períodos × localidades`. Medições no
agregado 5938 (PIB), nível municipal (5.570 localidades):

| variáveis | períodos | células | resultado |
|---|---|---|---|
| 6 | 1 | 33.420 | 200 · 4,16 MB |
| 6 | 2 | 66.840 | **500** |
| 6 | 3 | 100.260 | **500** |
| 1 | 5 | 27.850 | 200 · 1,04 MB |
| 1 | 25 (`all`) | 139.250 | **500** |

O teto adotado é **33.000 células** (`config.MAX_CELULAS_POR_REQUISICAO`), logo
abaixo do maior valor que passou. `api.agregados._planejar_lotes()` fatia a
consulta por período e, quando um único período já estoura (caso do PIB
municipal, com 6 variáveis), também por variável.

> `periodos/all` é seguro apenas em níveis pequenos (N1/N2/N3), onde não dá para
> estimar o custo antes da requisição.

---

## 2. Anos que a API declara mas não publica

O agregado **6579 (população residente estimada)** anuncia periodicidade anual
de 2001 a 2025, mas publica só **21 anos**. Faltam:

| ano | motivo |
|---|---|
| 2007 | Contagem da População — o dado vem da apuração, não da estimativa |
| 2010 | Censo Demográfico |
| 2022 | Censo Demográfico |
| 2023 | estimativa suspensa durante a revisão pós-Censo 2022 |

**Pedir um ano inexistente não gera erro** — ele simplesmente não aparece na
resposta. O sintoma aparece muito depois, como uma coluna inteiramente nula
após um join.

Por isso `api.agregados.anos_disponiveis()` consulta `/periodos` e é a fonte da
verdade; `serie_de()` filtra os anos pedidos contra essa lista e registra em log
os que foram descartados. A tupla em `config.POPULACAO_ESTIMADA.periodos_ausentes`
serve só para documentação e teste.

Consequência analítica: o PIB vai até 2023, mas não existe população de 2023
para o denominador do PIB per capita. O pipeline usa o ano publicado mais
próximo (2024) e grava qual foi usado em `ano_populacao_pib`.

---

## 3. As malhas precisam ser reorientadas para o Plotly

`GET /api/v3/malhas/...?formato=application/vnd.geo+json` devolve polígonos com
o **anel externo em sentido anti-horário** — exatamente o que o RFC 7946 pede.

O Plotly renderiza com **d3-geo**, que usa *winding esférico*: ali o anel
externo precisa ser **horário**. Com a orientação do IBGE, o d3 interpreta cada
polígono como o seu complemento e o resultado é **a projeção inteira preenchida,
com o formato do estado vazado nela**.

O detalhe cruel: **não há erro nenhum**. A figura é gerada, o join funciona, os
dados estão certos, e o mapa sai errado. Só se detecta olhando.

`viz.maps.reorientar_malha()` inverte a orientação na carga
(`utils.io.carregar_malha`), e é idempotente. O Leaflet (Folium) ignora winding,
então a mesma malha serve aos dois renderizadores.

---

## 4. Contagens de municípios divergem entre fontes

| fonte | municípios |
|---|---|
| Localidades v1 `/municipios` | 5.571 |
| Agregado 6579 (população, 2025) | 5.571 |
| Agregado 5938 (PIB, 2023) | 5.570 |

A diferença é **Boa Esperança do Norte - MT (`5101837`)**, instalado em 2025 —
existe na malha administrativa e na estimativa populacional, mas não na série do
PIB, que termina em 2023.

Não é erro de join: é vigência territorial. O pipeline registra o município sem
PIB em log em vez de descartá-lo, e o painel municipal mantém a linha com
`pib_mil_reais` nulo.

---

## 5. Nomes de localidade são inconsistentes entre agregados

O mesmo município volta com formatos diferentes conforme o agregado e o recorte:

```
"São Paulo (SP)"        # consulta a um município específico
"Boa Esperança do Norte - MT"   # consulta a todos os municípios (N6)
```

Por isso `etl.transform.enriquecer_municipios()` **descarta** `localidade_nome`
e usa o nome canônico da API de Localidades. Os codigos são normalizados para
string: são identificadores, não números, e `3550308` vs `"3550308"` quebra o
join silenciosamente.

---

## 6. Sentinelas de valor ausente

O SIDRA não usa `null`. Usa strings:

| valor | significado |
|---|---|
| `"..."` | não se aplica |
| `".."` | valor não disponível |
| `"-"` | zero absoluto |
| `"X"` | omitido para não identificar o informante |

Convertidos para `None` em `api.agregados._para_numero()`. Tratar `"-"` como
zero numérico seria defensável, mas misturaria "zero medido" com "sem dado" nas
médias — preferimos nulo explícito.

---

## 7. O VAB setorial para dois anos antes do PIB total

O agregado **5938** publica, no mesmo lugar, o PIB total (variável 37) e o valor
adicionado por setor (513, 517, 6575, 525). Eles **não têm a mesma cobertura**:

| variável | último ano publicado |
|---|---|
| 37 — PIB a preços correntes | **2023** |
| 513/517/6575/525 — VAB setorial | **2021** |

Em 2022 e 2023 as variáveis setoriais vêm presentes na resposta e **inteiramente
nulas**, em todos os níveis territoriais (N1 a N6). Não há erro, não há aviso.

O sintoma é traiçoeiro: quem toma `max(ano)` uma vez só e usa esse ano para
tudo — o caminho óbvio — monta um painel em que o PIB aparece e a estrutura
setorial inteira é nula. Foi exatamente o que aconteceu na primeira versão de
`analytics.mv_painel_municipio`, e é o que ainda acontece nas colunas `vab_*` de
`data/processed/painel_municipios.parquet` (elas chegam com dtype `object`
preenchido de `None` — o rastro típico de uma coluna que nunca teve valor).

As views resolvem como o pipeline já resolvia o PIB per capita: cada bloco usa o
ano mais recente em que **o seu** dado existe, e a view grava qual foi.

```sql
ano_pib AS (SELECT max(ano) FROM ibge.fato_pib_municipio),
ano_vab AS (SELECT max(ano) FROM ibge.fato_pib_municipio
             WHERE vab_industria IS NOT NULL)
```

O painel expõe `ano_pib` **e** `ano_vab` lado a lado (2023 e 2021), para que a
diferença de referência fique visível em vez de implícita.

---

## 8. PIB municipal negativo é dado válido

`ibge.fato_pib_municipio` não tem `CHECK (pib_mil_reais > 0)`, de propósito.

**Guamaré/RN, 2012**: PIB de −19.046 mil reais, com VAB industrial de −417.323.
Município de refinaria — o valor adicionado de um setor fica negativo quando o
consumo intermediário supera a produção no ano.

A constraint "PIB positivo" parece óbvia e recusaria dado oficial correto. A
verificação de plausibilidade ficou em `sql/analytics/qualidade.sql`, onde pode
distinguir o **negativo** (legítimo, esperado até 5 casos) do **zero** (que seria
falha de carga).

---

## 9. A densidade publicada tem 2 casas — e isso não é divergência

O Censo 2022 publica a densidade já calculada (variável 614). Comparar com
população ÷ área recalculada é uma boa verificação de carga, mas com tolerância
**apenas relativa** ela acusa falso positivo nos municípios mais vazios do país:

| município | população ÷ área | publicada | diferença relativa |
|---|---|---|---|
| Barcelos - AM | 0,1538 | 0,15 | 2,5% |
| Mateiros - TO | 0,2866 | 0,29 | 1,2% |

É arredondamento da publicação, não erro. `qualidade.sql` exige as duas
condições — 1% relativo **e** 0,005 absoluto (meia casa decimal) — para separar
precisão de publicação de erro de extração.

---

## Agregados usados

| id | nome | variáveis | níveis | período |
|---|---|---|---|---|
| 6579 | População residente estimada | 9324 | N1, N2, N3, N6 | 2001–2025 (21 anos) |
| 4714 | Censo 2022: população, área e densidade | 93, 6318, 614 | N1, N2, N3, N6 | 2022 |
| 5938 | PIB a preços correntes e VAB setorial | 37, 513, 517, 6575, 525, 543 | N1, N2, N3, N6, N8, N9 | 2002–2023 |

Níveis territoriais: `N1` Brasil · `N2` grande região · `N3` UF ·
`N6` município · `N8` mesorregião · `N9` microrregião.
