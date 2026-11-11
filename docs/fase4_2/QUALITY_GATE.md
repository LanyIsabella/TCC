# Qualidade e limitações dos gates

Resultados funcionais desta fase:

- Ruff nos arquivos tocados: aprovado.
- Suíte completa com o ambiente `.venv`: 370 aprovados, 1 ignorado e 2 xfail
  F6 conhecidos.
- F1 Red: 3 falhas estritas; F1 Green: 11 aprovados.
- Refatoração de escopo reduziu `assess_promotion` de CC 41 para 5 e
  `activate_gold` de CC 14 para 5; a política nova foi medida com cobertura
  válida no `.venv`.

O relatório automático ub-mode permanece não aprovado/incompleto: embora o
Crapper manual tenha usado `.venv` com cobertura válida, o Stop hook automático
expirou no orçamento compartilhado de 50 segundos. O Crapper global ainda
excede CRAP 10 por funções preexistentes de `rag_pipeline.py` e
`src/terminal/main.py`; Dryer mantém duplicações e Mutator não conclui todos os
pontos. Os 18 sobreviventes da Fase 4.1 continuam limitações conhecidas.
Timeout não é contado como mutante eliminado.
