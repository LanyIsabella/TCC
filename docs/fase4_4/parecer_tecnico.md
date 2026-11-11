# Parecer técnico — Fase 4.4

## Resultado

A seleção determinística por página foi implementada com rastreabilidade na
Silver e integração conservadora na Gold. Os contratos unitários, a persistência
append-only e a regressão F2/proveniência passaram nos testes executados. A
investigação final também bloqueia fallback técnico como seleção GLM-OCR e
corrige a publicação concorrente do snapshot no Windows.

## Evidências

- `tests/test_extraction_quality.py`: 12 aprovados.
- `tests/integration/test_extraction_quality_pg.py`: 3 aprovados.
- `tests/integration/test_postgres_provenance.py`: 43 aprovados no recorte
  executado junto com a seleção.
- Regressão antes da investigação: 393 aprovados, 1 ignorado e 2 xfail.
- Regressão final após os ajustes: 397 aprovados, 1 ignorado e 2 xfail.

## Limitações

O piloto real foi executado em quatro páginas com os três extratores, sem escrita
produtiva; ele demonstra execução e variação, não fidelidade factual. Os gates
Crapper/Dryer/Mutator permanecem limitados por timeout e alta
quantidade de pontos não cobertos; isso não é declarado como aprovação.

O relatório ub-mode mais recente também expirou o orçamento de 50 segundos do
Crapper durante a coleta de cobertura (exit 124), e o Mutator não obteve uma
baseline executável para vários módulos. O Dryer registrou duplicações já
existentes, inclusive entre consultas de status em `data/rag_pipeline.py`.
Esses resultados são limitações de validação, não defeitos funcionais
confirmados nesta fase.

## Recomendação

Prosseguir somente com revisão dos casos em quarentena e um piloto ampliado,
caso necessário, com os três extratores. Não promover automaticamente
resultados deste piloto nem iniciar a fase seguinte nesta execução.
