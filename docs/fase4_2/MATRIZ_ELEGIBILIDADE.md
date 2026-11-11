# Matriz de elegibilidade

| Evidência | Ausente/divergente | Presente e ligada | Resultado |
| --- | --- | --- | --- |
| Execução completa | `awaiting_evaluation` | continua | não promove |
| Avaliação atual | `blocked_provenance` | fingerprint de resultado e configuração coincidem | continua |
| Método | fallback/desconhecido → `technical_failure` | `page_image` ou `pdf_reader_text` | continua |
| Score | ausente → `blocked_provenance` | presente, sem limiar novo | continua |
| Indicadores automatizados | ausentes, inválidos ou sem validação independente → `retry_required`/`quarantined` | CER/WER/similaridade registrados e `deterministic_validation.status=passed` com referência confiável (`reference_status=trusted`) | continua |
| Falha crítica | `quality_rejected` | não sinalizada | continua |
| Página explicitamente vazia | classificação ausente ou conflitante | `blank_page` explícito e identidade confiável | pode aprovar |
| Incerteza (`requires_manual_review`) | alternativa → `retry_required`; sem alternativa → `quarantined`; rejeição humana → `quality_rejected` | aprovação humana excepcional ligada ao resultado | pode aprovar |
| Configuração | histórica/desconhecida → `blocked_provenance` | configuração atual conhecida | pode aprovar |

A decisão final só é `approved` quando todas as páginas chegam à última coluna
sem qualquer estado bloqueante.

O texto nativo do PDF e a concordância entre extratores são referências
diagnósticas; não autorizam promoção sem uma validação independente explícita.
