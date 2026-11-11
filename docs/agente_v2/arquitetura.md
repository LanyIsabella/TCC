# Arquitetura

`AgentV2.invoke` é o único controlador do fluxo. Ele separa intenção, recuperação, síntese e publicação:

```text
mensagem externa
  -> ConversationStore (ID e contexto limitado)
  -> Planner (decisão estruturada)
  -> ToolRegistry -> rag_document_search existente
  -> Synthesizer (SynthesisResponse)
  -> grounding_adapter -> evidence.finalize_grounding
  -> resposta pública
```

Falhas de ferramenta ou de síntese entram em `failed_normative_result` e retornam estado não fundamentado. Nenhum texto candidato anterior é reutilizado como resposta normativa.
