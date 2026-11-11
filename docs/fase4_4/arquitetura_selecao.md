# Arquitetura da seleção por página

`data/extraction_quality.py` é um módulo puro. Ele calcula indicadores de
integridade (vazio, PUA, caracteres de substituição/controle, estrutura e
referências normativas) e transforma cada candidato em uma avaliação auditável.

`select_page_candidate` recebe somente candidatos da página atual. Primeiro
elimina falhas técnicas, saída vazia não declarada como página vazia, truncamento
confirmado e densidade suspeita de PUA. Sem referência independente, acordo
entre extratores não prova correção; candidatos idênticos são colocados em
quarentena. Empates sem referência também são colocados em quarentena.

Quando existe referência independente, CER/WER/similaridade são registrados
como consistência, com `reference_is_ground_truth=false`; não há limiar
científico ou promoção baseada apenas nesses números.

`evaluate_extractions` persiste uma execução de seleção em
`silver.page_extraction_selections`. `activate_gold` exige cobertura completa,
rejeita páginas em quarentena e reconstrói o conteúdo quando a seleção é mista.
O vínculo da seleção é gravado em `gold.gold_rag_documents.selection_run_id` e
na derivação de proveniência. Cada candidato também carrega no JSON da decisão
o `page_extraction_id` e o `execution_id` imutáveis.
