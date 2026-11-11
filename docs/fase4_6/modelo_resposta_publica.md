# Modelo público e compatibilidade

`AgentChatResponse` mantém `answer` e `messages` e acrescenta, quando
disponíveis, `evidences`, `grounding_status` e `limitations`. Os campos são
aditivos e a rota usa `response_model_exclude_none=True`; clientes antigos que
não conhecem os campos continuam compatíveis.

Cada evidência pública pode conter `evidence_id`, `document_id`, título,
identificador/edição da norma, página, seção, texto, trecho correspondente,
`turn_id`, `tool_call_id`, `execution_id`, consulta e um resumo seguro de
`omitted_content` (`characters`/`pages`). IDs de ranking, `rag_document_id`,
fonte interna, scores, caminhos e prompts não são publicados.

Estados: `supported`, `partial`, `unsupported` e `conversational`. A ausência
de suporte não é convertida em uma resposta normativa afirmativa.
