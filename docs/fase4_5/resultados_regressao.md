# Resultados da regressão

Com a implementação atual:

```text
uv run pytest -q
414 passed, 0 failed, 1 skipped in 53.73s, incluindo a correção final do
grounding para omissões.

uv run ruff check .
All checks passed

git diff --check
sem saída (sucesso)
```

Os dois `xfail` F6 foram removidos somente depois de seus comportamentos
passarem. O aumento da contagem em relação à baseline inclui os testes
determinísticos adicionados para F6.

Uma primeira execução completa teve uma falha transitória de permissão no
teste concorrente de `original_snapshot()`; a execução isolada passou e a
reexecução completa terminou com os números acima. Nenhuma alteração foi feita
no código F2.
