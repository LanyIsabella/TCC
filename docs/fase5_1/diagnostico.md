# Fase 5.1 — Diagnóstico da orquestração e retenção

## Escopo

Esta etapa usa o run já existente `20261111T135452Z_dev_10c062a` somente como
evidência de diagnóstico. Os 40 casos não foram reexecutados, o holdout não foi
usado e nenhum componente de ingestão, recuperação, OCR ou banco produtivo foi
alterado.

## Causas comprovadas

1. `rag_eval.baseline.runtime.execute_stage()` consumia o resultado por
   `extract_agent_result()`, mas serializava apenas `answer`, `evidences`,
   mensagens e payloads de ferramenta. O `structured_response`, o estado de
   grounding e as limitações eram descartados no relatório experimental. Assim,
   a contagem de chamadas `AgentAnswer` feita somente sobre o JSON persistido
   não distinguia ausência real de estrutura de perda no adaptador.
2. A política de evidências tratava uma seleção explícita vazia de
   `AgentAnswer` como se ela não existisse: uma correspondência literal podia
   reutilizar qualquer evidência disponível. Isso confundia evidência disponível
   com evidência selecionada pelo encerramento do agente.
3. O agente não registrava se terminou com saída estruturada, texto livre após a
   recuperação ou texto livre sem recuperação. A ausência de registro não
   permitia separar falha de encerramento de abstenção deliberada. Agora texto
   livre normativo falha fechado; somente a síntese textual interna, marcada e
   limitada, pode seguir para grounding.

## O que não foi classificado como defeito

Evidência recuperada não é automaticamente evidência publicada. Quando o
grounding rejeita uma afirmação por contradição, omissão de condição ou falta de
suporte, a lista final pode ficar vazia sem indicar perda do payload. A solução
não copia todos os documentos recuperados para a resposta.

## Casos de referência

- `specific_10520_01`: texto após tool sem estrutura visível no relatório; agora
  o encerramento é marcado como `textual_after_retrieval` e a estrutura final é
  preservada no adaptador.
- `specific_10520_02`: estrutura e tool aparecem nas mensagens, mas os campos
  estruturados eram omitidos pelo runner; a nova serialização mantém a seleção
  e o grounding separadamente.
- `boundary_01`: recusa de escopo continua sem recuperação e recebe o estado
  `scope_guard`.
