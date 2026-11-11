# Parecer técnico — Fase 4.2

## Implementado

- F1 corrigido em `data/gold_policy.py` e integrado ao gate
  `data/rag_pipeline.py`.
- Avaliações legadas sem identidade confiável não passam pelo gate normal.
- Fallback determinístico é classificado como falha técnica, não como qualidade
  aprovada.
- `requires_manual_review` agora conduz a `retry_required` quando há alternativa
  e a `quarantined` quando não há; revisão humana não é requisito operacional.
- A promoção automática exige pelo menos um indicador determinístico (`cer`,
  `wer` ou similaridade normalizada), além da identidade e do status válidos.
  A presença deixou de ser suficiente: a política também exige
  `deterministic_validation.status=passed`, fingerprint de referência e uma
  referência independente/humanamente verificada. Métricas calculadas contra
  `native_page_text` continuam diagnósticas e não são tratadas como ground
  truth.
- O contrato de `technical_failure` permanece compatível com o mecanismo
  existente de reprocessamento por `retry_errors`; a escolha efetiva de método
  alternativo por página continua reservada à Fase 4.4.
- Revisões humanas foram modeladas em `silver.gold_promotion_reviews`, com
  vínculo ao resultado/avaliação/configuração e proteção append-only.
- Migrações reversíveis foram adicionadas apenas para uso em clusters isolados:
  `0002_gold_promotion_policy.up.sql` e `.down.sql`.
- Testes unitários e PostgreSQL cobrem identidade, revisão, rejeição de legado,
  fallback, resultado obsoleto e preservação append-only.

## Red–Green–Refactor

- Red pré-correção preservado em `artifacts/f1_baseline_red.xml`: 3 falhas
  estritas, correspondentes às avaliações legadas `review`, `no-score` e
  `legacy-fallback`.
- Green após a menor alteração: contrato F1 passou sem xfail; o relatório está
  em `artifacts/f1_green.xml`.
- Refactor: a decisão foi isolada em função pura, sem introduzir limiares
  científicos ou alterar recuperação, embeddings, OCR, RRF, agente, UI ou dados
  ativos.

## Testes executados

- `tests/test_gold_policy.py`: política determinística, estados e identidades.
- `tests/integration/test_gold_policy_pg.py`: 4 testes em PostgreSQL isolado.
- `tests/integration/test_postgres_provenance.py`: 43 testes F2/regressão.
- `tests/baseline/test_defect_pipeline.py`: 11 testes, incluindo os contratos F1
  sem xfail.
- A baseline anterior da suíte completa foi **366 passed, 1 skipped, 2 xfailed**;
  nesta verificação foram adicionados quatro contratos determinísticos para os
  indicadores. Com o ambiente `.venv` corrigido, a regressão completa executou
  **370 passed, 1 skipped, 2 xfailed**; o subconjunto F1/F2 executou **65
  passed**.
- O pacote humano foi somente lido e verificado por hashes; não houve nova
  avaliação automática.

## Limitações e pendências

- O pacote humano continua sem anotações: 0 decisões e 0 transcrições. Nenhuma
  conclusão semântica foi inferida a partir dele.
- A política não demonstra fidelidade factual universal de LLM; ela controla
  identidade, completude, qualidade automatizada, retry/quarentena e revisão
  auditável.
- Os 18 sobreviventes de mutação da Fase 4.1 e o Stop hook reprovado continuam
  limitações conhecidas; não foram ocultados nem reclassificados nesta fase.
- A migração 0002 ainda não foi aplicada ao PostgreSQL produtivo.
- A política emite estados seguros, mas não implementa ainda a orquestração
  adaptativa por página entre PDF Reader, Docling e GLM-OCR.
- O pipeline atual calcula CER/WER/similaridade contra o texto nativo do PDF,
  sem atestado independente; essas avaliações permanecem em retry/quarentena
  até que a referência seja validada. A calibração de critérios e limiares
  continua fora desta fase, reservada à Fase 4.4.
- O último relatório automático do ub-mode permanece reprovado/incompleto:
  embora o Crapper manual tenha usado `.venv` com cobertura válida, o Stop hook
  automático expirou no orçamento compartilhado de 50 segundos. O Crapper
  global ainda excede CRAP 10 por funções preexistentes, Dryer encontra
  duplicações e Mutator não completa a execução. Esses gates não são declarados
  como aprovação nesta fase; os pontos são mantidos como limitações conhecidas.

## Decisão

F1 está implementado e testado no escopo desta fase. O encerramento técnico
deve manter as ressalvas acima; a promoção automatizada não depende de
preenchimento humano, e versões incertas são encaminhadas para retry ou
quarentena.
