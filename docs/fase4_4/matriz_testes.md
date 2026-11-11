# Matriz de testes

| Cenário | Cobertura | Resultado |
|---|---|---|
| Texto limpo | `tests/test_extraction_quality.py` | aprovado |
| PUA/substituição | teste determinístico | aprovado |
| Vazio e truncamento | teste determinístico | aprovado |
| Referência não é ground truth | teste determinístico | aprovado |
| Concordância idêntica sem referência | quarentena | aprovado |
| Escolha por página | teste determinístico | aprovado |
| Página explicitamente vazia | teste determinístico | aprovado |
| Estrutura de listas/tabelas | teste determinístico | aprovado |
| Números/referências e divergência pareada | testes determinísticos | aprovado |
| Persistência append-only | `tests/integration/test_extraction_quality_pg.py` | aprovado |
| Regressão F2/proveniência | `tests/integration/test_postgres_provenance.py` | aprovado |

Casos de erro de infraestrutura e de extratores indisponíveis são registrados
como limitações do piloto; não são convertidos em aprovações.
