# Fase 4.4 — Diagnóstico inicial (F3/F4)

Este diagnóstico foi produzido antes das alterações funcionais, usando o código atual, o snapshot da Fase 2 e o pacote de revisão humana. Nenhum PDF foi reprocessado.

## Caminho atual

1. `data/rag_pipeline.py::extract_page` produz páginas independentes para `pdf_reader`, `docling` e `glm_ocr`.
2. `_process_extraction_page` persiste texto, Markdown, hash, contagens e `structured_output` na Silver.
3. `evaluate_page` envia imagem e textos ao avaliador LLM. Em `_evaluate_page_result`, `deterministic_metrics(native, extracted)` compara a extração com o texto nativo do PDF.
4. CER, WER e similaridade são, portanto, indicadores de consistência com uma referência auxiliar nativa; não constituem ground truth. A política F2 já exige identidade e proveniência, mas não seleciona candidatos por página.
5. `refresh_silver_document` agrega qualidade por execução. `activate_gold` escolhe uma execução inteira pela média ponderada/agregada e copia suas páginas; não existe seleção mista por página.

## Lacunas observadas

- O único tratamento determinístico de corrupção PUA está em `select_primary_content`, aplicado ao conteúdo Bronze agregado, não como avaliação por página.
- Texto vazio, truncado, falhas técnicas e `completion_unconfirmed` não formam um contrato único de elegibilidade.
- A avaliação LLM pode produzir nota alta quando a saída é vazia ou apenas repete o texto auxiliar; a nota não substitui indicadores independentes.
- O schema guarda avaliação por página, mas não guarda uma decisão de seleção por página nem as alternativas rejeitadas.
- A seleção Gold é por execução, o que impede combinar extratores diferentes no mesmo documento.

## Evidência NBR 6023

- Página física 5: o leitor nativo contém muitos caracteres privados/corrompidos; Docling também preserva ruído; GLM-OCR tem texto parcial. Avaliações históricas foram `deterministic_fallback` com nota 50.
- Página física 6: leitor e Docling retornam apenas aviso de impressão; GLM-OCR está vazio, mas registros históricos chegaram a nota 100 com avaliação baseada no texto auxiliar.
- Páginas 21, 28 e 54 também estão no pacote de revisão humana e permanecem sem confirmação humana.

## Direção de F4.4

Adicionar indicadores determinísticos independentes, uma decisão por página com estados `selected`, `retry_required` ou `quarantined`, e persistir critérios/proveniência. A ausência de referência independente será registrada como `consistency_only`; não haverá limiar científico inventado nem promoção automática por score LLM.
