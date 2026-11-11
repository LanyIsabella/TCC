# Fase 4.4 — Qualidade textual e seleção automática

Esta fase adiciona uma decisão determinística e auditável por página para os
resultados de `pdf_reader`, Docling e GLM-OCR. A decisão é persistida na Silver
e pode resultar em `selected`, `retry_required` ou `quarantined` (a implementação
atual usa `quarantined` quando não há candidato seguro).

Escopo preservado: nenhum PDF original, embedding, RRF, interface ou banco
produtivo foi alterado. A implementação não reprocessa o corpus nem promove
automaticamente resultados sem a validação F1/F2 existente.

Os 80 casos reservados do benchmark de recuperação não foram usados no piloto,
na calibração ou na seleção.

Documentos desta pasta registram diagnóstico, critérios, testes, integração,
piloto controlado, investigação final, riscos e o parecer técnico.
