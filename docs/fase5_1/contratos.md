# Contratos antes/depois

| Área | Antes | Depois |
| --- | --- | --- |
| Trace do agente | O runner persistia mensagens e resposta já extraída, sem `structured_response`, grounding ou limitações. | O runner preserva `structured_response` sanitizado, `grounding_status`, `limitations`, origem do encerramento e os conjuntos de IDs disponível/selecionado/publicado. |
| Encerramento | Não era possível diferenciar texto livre após tool de resposta estruturada. | `ScopedAgent` registra `completion_contract`: `structured`, `structured_invalid`, `textual_after_retrieval`, `textual_without_retrieval` ou `scope_guard`. |
| Seleção | `AgentAnswer.evidence_ids=[]` ainda permitia que o grounding buscasse qualquer evidência disponível por correspondência literal. | Uma seleção explícita restringe o conjunto usado pelo grounding; lista vazia não publica evidências. |
| Proveniência | Evidência publicada e evidência recuperada apareciam misturadas no artefato experimental. | `available_evidence_ids`, `selected_evidence_ids` e `published_evidence_ids` são campos distintos; `omitted_content` permanece no payload/evidência. |
| Escopo | Recusas legítimas eram apenas mensagens. | A recusa continua igual para consumidores e recebe metadado interno `scope_guard`, sem chamada de recuperação. |

Os campos adicionais são aditivos e não alteram o contrato HTTP/terminal; esses
canais continuam consumindo `extract_agent_result()`.

Para perguntas normativas, texto livre após uma recuperação não recebe suporte
documental automaticamente. A única exceção é a síntese textual controlada pelo
fallback interno, registrada como `textual_synthesis`; ela continua passando pelo
grounding antes da publicação. Isso evita que uma resposta livre seja aceita
silenciosamente, sem recusar o caminho de recuperação já previsto e limitado a
uma única síntese.
