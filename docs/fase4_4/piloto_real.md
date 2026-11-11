# Piloto controlado

O piloto foi delimitado a páginas já presentes no snapshot de revisão humana,
em workspace e cluster PostgreSQL temporários, sem escrita no banco produtivo.
O objetivo foi validar a decisão e a persistência por página, não reprocessar o
corpus.

O serviço Ollama estava disponível no ambiente e o modelo `glm-ocr:latest` foi
consultado em modo `direct_ollama`. Em quatro cópias de páginas do snapshot
(NBR10520 p.8, NBR6023 p.5, NBR6028 p.4 e NBR14724 p.14), os três extratores terminaram com
`processing_status=success` e foram persistidos no cluster isolado. Comprimentos
observados (caracteres) e decisões foram:

O conjunto inclui uma página com exemplos/listas (NBR10520), uma página com
marcadores de tabela no texto nativo (NBR14724), uma página de texto corrido
(NBR6028) e a página conhecida por corrupção PUA (NBR6023).

| Página | PDF reader | Docling | GLM-OCR | Decisão |
|---|---:|---:|---:|---|
| NBR10520 p.8 | 1665 | 1446 | 1665* | Docling selecionado |
| NBR6023 p.5 | 2414 | 2560 | 2414* | quarentena (`no_eligible_candidate`) |
| NBR6028 p.4 | 2113 | 1856 | 2113* | Docling selecionado |
| NBR14724 p.14 | 3262 | 3036 | 3262* | quarentena (`insufficient_reference`) |

`*` Em uma verificação detalhada do mesmo piloto, o GLM-OCR retornou erro HTTP
400 e o pipeline registrou `structured_output.fallback=pdf_reader`; portanto,
esses comprimentos não representam uma saída OCR independente. A limitação foi
preservada no registro, não convertida em aprovação.

Esses números demonstram execução e variação, não qualidade factual nem
superioridade. A execução confirmou a persistência Silver e a criação da
seleção append-only; o banco temporário, os PDFs de trabalho e o cache foram
removidos ao final. A seleção deve ser aplicada somente após
avaliação/proveniência F1/F2 e revisão dos casos em quarentena.

## Métricas observadas

- páginas processadas: 4;
- páginas selecionadas: 2 (50%);
- páginas em quarentena: 2 (50%);
- `retry_required`: 0;
- distribuição das seleções: Docling 2; PDF reader 0; GLM-OCR independente 0;
- falha técnica observada: fallback GLM-OCR→PDF reader por HTTP 400;
- concordância com revisão humana, erros aceitos, tempo e custo: não disponíveis
  neste piloto e não foram inferidos.
