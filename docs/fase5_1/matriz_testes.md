# Matriz TDD

| Cenário | Teste | Resultado |
| --- | --- | --- |
| Saída estruturada válida | `test_agent_stage_uses_real_structured_response_adapter` | passa |
| Retenção do contrato no runner | `test_agent_stage_preserves_grounding_contract_metadata` | passa |
| Texto livre após recuperação | `test_orchestration_records_textual_completion_after_retrieval` | passa |
| Texto livre normativo sem estrutura | `test_free_text_after_retrieval_cannot_be_published_as_normative_support` | passa |
| Falta de recuperação por escopo | `test_orchestration_records_scope_guard_without_retrieval` | passa |
| Estrutura inválida | `test_orchestration_records_invalid_structured_completion` | passa |
| `AgentAnswer` sem seleção | `test_structured_answer_without_selected_evidence_cannot_publish_available_text` | passa |
| IDs inválidos/contraditórios | `test_extract_agent_result_accepts_only_retrieved_evidence_ids` e contratos F10/F11 | passam |
| Suporte parcial e omissão | `test_compaction_omission_reaches_grounding_as_a_partial_answer` | passa |
| Isolamento de turnos | contratos F12 em `tests/baseline/test_defect_agent.py` | passam |
| API/terminal/UI | `tests/api/test_agent_*`, `tests/test_terminal_evidence.py` e `tests/test_ui_app.py` | passam na suíte direcionada |

## Red–Green–Refactor

- Red: o teste do runner falhou com `KeyError: grounding_status`; o teste de
  seleção explícita publicou uma evidência que não havia sido selecionada.
- Green: o adaptador passou a serializar os metadados e `_decision()` passou a
  restringir o suporte à seleção explícita.
- Refactor: a serialização foi mantida em helpers pequenos e os campos foram
  separados por finalidade, sem alterar a busca ou o ranking.
