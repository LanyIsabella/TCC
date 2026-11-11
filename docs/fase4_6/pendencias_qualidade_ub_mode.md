# Pendências futuras de qualidade técnica

Estas pendências foram separadas da implementação F14 e não são corrigidas
nesta fase:

- corrigir o orçamento de execução e a coleta de cobertura do ub-mode;
- adicionar testes para funções críticas de promoção Gold;
- avaliar a cobertura de `direct_ollama_pdf_text` e `search_documents`;
- investigar a duplicação apontada em `data/rag_pipeline.py`.

Não refatorar a duplicação nem modificar ingestão, Gold ou extração textual sem
um defeito funcional reproduzível. O relatório ub-mode permanece reprovado e
incompleto; seus resultados não são usados como aprovação da Fase 4.6.
