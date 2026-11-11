# Matriz de testes

| Grupo | Evidência | Resultado |
|---|---|---:|
| F6 direcionado | página longa, página tardia, condição posterior, tabela, lista, orçamento, edição, payload e documento vazio | 15 passed |
| Omissão no grounding | política unitária e fluxo RAG→evidência→grounding | 2 passed |
| Evidência/grounding/agente | `test_evidence`, `test_grounding_policy`, turnos, orquestração, fallback e canais | 174 passed |
| Integração de proveniência | `tests/integration/test_postgres_provenance.py` | 43 passed |
| Regressão completa | `uv run pytest -q` | 414 passed, 1 skipped |
| Lint | `uv run ruff check .` | sem problemas |
| Integridade do diff | `git diff --check` | sem problemas |

Os testes F6 foram executados em Red antes da alteração e em Green após a
alteração. Crapper, Dryer e Mutator não foram reexecutados, conforme a
restrição da fase.
