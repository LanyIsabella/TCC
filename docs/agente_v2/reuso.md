# Reuso e fronteiras

- Recuperação: `src.app.tools.rag_search.rag_document_search`.
- Proveniência e grounding: `src.app.evidence` e `src.app.grounding`.
- Contexto: `ConversationStore` e `contextualize_query` existentes.
- Modelo: `Client` existente, sem alteração.

A V2 não copia SQL, RRF, embeddings, schemas de persistência ou regras de ingestão. O único nome de tool registrado é `rag_document_search`; interfaces futuras não são expostas nesta etapa.
