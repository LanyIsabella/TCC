# Integridade dos splits

A verificação leu somente metadados de `id`, `split`, referências documentais e
hashes; não exibiu nem utilizou o texto das perguntas reservadas.

- Arquivo: `rag_eval/baseline/queries.json`.
- Total: 120 entradas.
- Desenvolvimento: 40 entradas.
- Holdout reservado: 80 entradas.
- Sobreposição de IDs: 0.
- SHA-256 de `queries.json`:
  `c8792a25989c0a7ed0a6549210f4f85597b3cff9e511b4b5f9bd162b512e9182`.
- SHA-256 de `initial_state.json`:
  `ba555e70267df221683c429d7ab6c965d03b73e64e7d1d2e52dbe0d1ace9ba99`.
- SHA-256 de `data/corpus_manifest.yaml`:
  `ff9ac11125e618c53aceb5e4fe05804c5af231461a403aa947b5fb8b0672c2c0`.
- Arquivos documentais referenciados: todos presentes; hashes divergentes: 0.

Seis entradas de desenvolvimento e quatorze reservadas não possuem referência
documental, correspondendo a casos de fronteira/conversacionais. Isso não
impede execução, mas impede pontuação factual por referência nesses casos.

Os 80 casos reservados permanecem intocados e não foram enviados a modelo,
recuperador ou ajuste.
