# Riscos e decisões

- **Risco:** extratores concordarem em um mesmo erro. **Decisão:** sem referência
  independente, concordância idêntica gera quarentena.
- **Risco:** referência nativa ser confundida com ground truth. **Decisão:** o
  indicador registra explicitamente `reference_is_ground_truth=false`.
- **Risco:** perda de histórico. **Decisão:** seleções são append-only e a
  derivação registra as páginas efetivamente selecionadas.
- **Risco:** promoção parcial. **Decisão:** Gold exige uma linha `selected` para
  cada página e rejeita estados incompletos.
- **Risco:** limiar operacional virar afirmação científica. **Decisão:** a
  densidade de PUA é documentada como guarda de corrupção e sua calibração fica
  pendente.

Não foram alterados OCR, embeddings, RRF, agente, UI ou banco produtivo.
