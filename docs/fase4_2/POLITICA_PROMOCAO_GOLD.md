# Política de elegibilidade da Gold

Uma promoção normal só pode resultar em `approved` quando todas as páginas da
execução atual estão completas e cada avaliação:

1. aponta para o `result_fingerprint` atual;
2. possui `evaluation_id`, `evaluation_config_fingerprint` e configuração
   persistida conhecida;
3. corresponde à identidade de avaliação atualmente configurada;
4. tem `evaluation_status=success`, método não-fallback, score presente e
   indicadores automatizados de qualidade explicitamente validados; uma
   exceção humana precisa estar explicitamente vinculada ao mesmo resultado;
5. não possui falha crítica explícita.

`requires_manual_review` é um sinal de incerteza. Ele não cria uma obrigação
operacional de revisão humana: com alternativas confiáveis, a decisão é
`retry_required`; sem alternativa confiável, é `quarantined`. A revisão humana
continua disponível como exceção auditável e pode aprovar uma versão específica.

Não há limiar numérico novo. `cer`, `wer` e `normalized_similarity` são
calculados por `deterministic_metrics(native_page_text, extracted_text)` e,
portanto, usam o texto nativo do PDF apenas como comparação diagnóstica, não
como ground truth. A promoção automatizada exige, além desses indicadores, um
bloco `deterministic_validation` com `status=passed`, referência
`human_verified` ou `independent_reference`, `reference_status=trusted` e
fingerprint da referência. A
mera presença de métricas, concordância com outra extração ou comparação com o
texto nativo conduz a retry/quarentena. O score do LLM não é usado isoladamente
como prova.

## Estados

| Estado | Uso |
| --- | --- |
| `approved` | Todas as evidências estão ligadas e aceitas. |
| `awaiting_evaluation` | Página ausente, pendente ou referência indisponível. |
| `retry_required` | Incerteza automatizada com alternativa disponível. |
| `quarantined` | Incerteza sem alternativa confiável; não altera a Gold ativa. |
| `awaiting_human_review` | Reservado para fluxo humano excepcional futuro. |
| `quality_rejected` | Falha crítica ou revisão humana rejeitada. |
| `blocked_provenance` | Resultado/configuração/identidade ausente, antiga ou divergente. |
| `technical_failure` | Execução incompleta ou falha técnica do avaliador/fallback. |

Uma revisão aprovada deve conter `review_id`, revisor, decisão, critérios,
proveniência, `result_fingerprint`, `evaluation_id` e
`evaluation_config_fingerprint`. O banco impede edição e exclusão do histórico.

A seleção adaptativa entre extratores, a execução efetiva de novas tentativas e
a escolha por página permanecem contratos para a Fase 4.4. Nesta fase a política
somente emite estados seguros para o orquestrador existente.
