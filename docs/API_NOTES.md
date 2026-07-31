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

## Agregados usados

| id | nome | variáveis | níveis | período |
|---|---|---|---|---|
| 6579 | População residente estimada | 9324 | N1, N2, N3, N6 | 2001–2025 (21 anos) |
| 4714 | Censo 2022: população, área e densidade | 93, 6318, 614 | N1, N2, N3, N6 | 2022 |
| 5938 | PIB a preços correntes e VAB setorial | 37, 513, 517, 6575, 525, 543 | N1, N2, N3, N6, N8, N9 | 2002–2023 |

Níveis territoriais: `N1` Brasil · `N2` grande região · `N3` UF ·
`N6` município · `N8` mesorregião · `N9` microrregião.
