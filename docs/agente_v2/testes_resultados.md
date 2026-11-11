# Testes e resultados

## Determinísticos

`tests/test_agent_v2.py` cobre:

- conversa sem chamada RAG;
- consulta normativa com recuperação e publicação;
- ID selecionado inexistente com fechamento seguro;
- isolamento de históricos.

Execução: `4 passed`.

## Regressão

Execução com `uv run --locked pytest -q`: `446 passed, 1 skipped`.

`uv run --locked ruff check .` e `git diff --check`: aprovados.

## Verificação funcional curta

Com PostgreSQL/RAG local e `gemma4:e2b`, a pergunta “Como formatar uma citação direta longa segundo a ABNT?” retornou resposta baseada na evidência `document:1:page:16`, estado `partial` e limitação explícita. Isso demonstra o caminho funcional e não constitui prova de fidelidade factual geral do LLM.
