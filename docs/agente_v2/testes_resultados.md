# Testes e resultados

## Determinísticos

`tests/test_agent_v2.py` cobre:

- conversa sem chamada RAG;
- consulta normativa com recuperação e publicação;
- ID selecionado inexistente com fechamento seguro;
- isolamento de históricos.

Execução: `4 passed`.

## Regressão

Execução nesta branch, baseada no `master` atualizado (`6dd05ba`):
`299 passed, 1 skipped, 9 xfailed`.

Uma validação anterior no histórico funcional `c22962a` registrou `446 passed,
1 skipped`. A diferença é esperada: `master` ainda não contém os commits
Fase 4.1–Fase 5.1 e os respectivos testes; esses commits divergem do baseline
atual. Não foi feito merge indiscriminado. A V2 traz apenas as adaptações de
conversa, evidência e grounding necessárias ao seu contrato.

Os testes de proveniência, Gold, metadados normativos e integrações PostgreSQL
das fases anteriores permanecem associados ao histórico `c22962a` e devem ser
validados quando essa infraestrutura for integrada separadamente.

`uv run --locked ruff check .` e `git diff --check`: aprovados.

## Verificação funcional curta

Com PostgreSQL/RAG local e `gemma4:e2b`, a pergunta “Como formatar uma citação direta longa segundo a ABNT?” retornou resposta baseada na evidência `document:1:page:16`, estado `partial` e limitação explícita. Isso demonstra o caminho funcional e não constitui prova de fidelidade factual geral do LLM.
