# Fase 4.2 — Política de promoção confiável à Gold

Esta fase implementa exclusivamente a correção F1. A branch de trabalho é
`fix/fase4-2-politica-gold-20261110`; a Fase 4.3 não foi iniciada.

## Escopo

- A promoção normal exige identidade da avaliação ligada ao resultado atual,
  configuração conhecida, método confiável, score presente e páginas completas.
- `success` isolado, IDs de avaliação válidos, configurações históricas
  desconhecidas e `deterministic_fallback` não autorizam Gold.
- Revisões humanas são append-only e só valem quando ligadas ao mesmo resultado,
  avaliação e configuração. Elas são excepcionais, não uma etapa obrigatória;
  a decisão precisa registrar revisor, critérios e proveniência.
- `requires_manual_review` produz `retry_required` quando há alternativa
  confiável e `quarantined` quando não há alternativa; a Gold anterior é mantida.
- Estados de decisão: `approved`, `awaiting_evaluation`, `retry_required`,
  `quarantined`, `quality_rejected`, `blocked_provenance` e
  `technical_failure`.
- `--allow-unvalidated` continua sendo uma exceção administrativa explícita para
  fixtures/recuperação histórica; não é o caminho de promoção normal.

## Pacote de revisão humana

O pacote existente em
`rag_eval/baseline/human_review/lote_2026-11-10` contém 12 páginas, 36 textos e
os hashes do snapshot. O arquivo `VERIFICACAO.json` registra integridade dos
artefatos e confirma que não houve nova OCR, embedding, ingestão ou avaliação.
As 12 páginas permanecem `pending_human_review`, com zero transcrições e zero
decisões humanas. Portanto, nenhum extrator foi promovido por esse pacote.

## Evidências

- Red F1 original: [f1_baseline_red.xml](artifacts/f1_baseline_red.xml), com
  3 falhas estritas nos contratos de avaliações legadas.
- Green F1: [f1_green.xml](artifacts/f1_green.xml).
- O relatório consolidado está em [RELATORIO.md](RELATORIO.md).
- A política normativa está em [POLITICA_PROMOCAO_GOLD.md](POLITICA_PROMOCAO_GOLD.md).

Os testes PostgreSQL usam somente clusters e bancos temporários criados pela
fixture. Nenhuma migração foi aplicada ao banco produtivo.
