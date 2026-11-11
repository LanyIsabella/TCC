# Diagnóstico inicial F6

O defeito estava em `src/app/tools/rag_search.py`, em `_compact_document()`.
Antes da correção, cada página era reduzida por `page_text[:1800]` e o texto
integral era descartado quando ultrapassava 6.000 caracteres. Assim, uma regra
recuperada no final de uma página longa ou em uma página posterior podia não
chegar ao LLM.

O fluxo observado foi:

1. `rag_document_search()` chama `search_documents()`;
2. os resultados são mesclados sem alterar RRF;
3. `_compact_document()` monta evidências e o aviso de contexto;
4. `_model_document()` envia somente o contrato reduzido ao agente;
5. `src/app/evidence.py` e `src/app/grounding.py` validam a proveniência.

Baseline Red reproduzível, antes da correção:

```text
uv run pytest -q --runxfail tests/baseline/test_defect_agent.py -k f6
2 passed, 2 failed
```

As duas falhas eram os contratos F6 de regra no fim da página e de regra em
página posterior. Os limites anteriores eram 1.800 caracteres por página,
5.000 por contexto e 6.000 para texto integral.
