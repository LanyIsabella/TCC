# Resultados de verificação

## Testes executados

- Direcionados de orquestração, fallback, evidências, canais, API, terminal e
  runner: **78 passed**.
- Ruff nos arquivos alterados: **sem violações** após a formatação.
- Regressão completa final (`uv run pytest -q -p no:cacheprovider`): **426
  passed, 0 failed, 1 skipped** em 63,87 s. Duas execuções intermediárias
  tiveram uma falha transitória de `PermissionError` no teste de concorrência de
  snapshot; a reprodução isolada e a regressão subsequente passaram.

Não foram executados manualmente nesta fase os 40 casos experimentais, o holdout,
ingestão, migração, Crapper, Dryer ou Mutator.

O relatório ub-mode já existente (`6d55bcec9bbdadbe6d16/report.json`) permanece
reprovado: Crapper terminou com exit 2 por CRAP acima do limite e cobertura
incompleta, Dryer encontrou duplicações, e Mutator terminou por expiração do
orçamento (71 mutações eliminadas, 569 não cobertas de 640). Ele cobre diversos
arquivos de fases anteriores; não foi rerodado nem tratado como evidência de
aprovação desta fase.

## Arquivos alterados

- `src/app/agente.py`: metadados internos do encerramento.
- `src/app/evidence.py`: respeito à seleção explícita de evidências.
- `rag_eval/baseline/runtime.py`: retenção sanitizada do contrato no trace.
- Testes em `tests/test_agent_orchestration.py`, `tests/test_evidence.py` e
  `tests/baseline/test_runner.py`.
- Documentação em `docs/fase5_1/`.
