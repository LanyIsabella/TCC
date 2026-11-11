# Verificação dos serviços

## Ollama

- `/api/version`: disponível, servidor `0.30.11`.
- Modelos requeridos presentes:
  - `gemma4:e2b`, digest
    `7fbdbf8f5e45a75bb122155ed546e765b4d9c53a1285f62fd9f506baa1c5a47e`;
  - `nomic-embed-text:latest`, digest
    `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`.

## PostgreSQL

A conexão foi feita com `connect_readonly()` em transação `REPEATABLE READ`
`READ ONLY`.

- PostgreSQL: 18.0.
- Documentos Bronze: 10.
- Documentos Gold ativos: 10.
- Páginas no índice Gold: 266.
- Tabelas centrais Bronze/Silver/Gold e índices de busca presentes.
- `silver.page_extraction_selections` não está presente; é uma tabela opcional
  da migração de seleção por página e não impediu o smoke de recuperação baseado
  no índice Gold ativo.
