# Resultados e parecer técnico

Implementado nesta branch:
`fix/fase4-6-evidencias-api-terminal-20261111`.

Testes F14 e contratos relacionados: 165 testes aprovados na execução
direcionada após a implementação. A regressão completa registrou 419 testes
aprovados, 1 ignorado e 0 falhas.

Uma primeira execução completa teve uma falha transitória de permissão no
teste concorrente de snapshot; a reprodução isolada e a execução completa
subsequente passaram, sem alteração no código de F14.

Ruff (`uv run ruff check .`) e `git diff --check` passaram.

Não foram executados holdout, ingestão, backfill, reindexação, Crapper, Dryer
ou Mutator. O relatório ub-mode global existente permanece incompleto e
reprovado por limite compartilhado, com CRAP elevado em funções fora do escopo;
isso não é declarado como passe.

Parecer: a perda de evidências nos canais API/terminal foi corrigida com uma
projeção pública mínima e compatível. A conclusão final depende da regressão
completa registrada no handoff.
