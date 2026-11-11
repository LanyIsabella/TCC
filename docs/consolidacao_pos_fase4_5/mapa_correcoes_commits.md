# Mapa de correções e commits

| Commit | Fase | Escopo | Contratos principais |
|---|---|---|---|
| `27551ce` | Fase 3 | Turnos, grounding, papéis públicos e evidências do agente | F10, F11, F12, F13 |
| `bf4c551` | Fase 4.1 | Snapshot, identidade de execução, avaliação e histórico | F2 |
| `0852c43` | Fase 4.2 | Gate conservador de promoção Gold | F1 |
| `b203cbf` | Fase 4.3 | Metadados normativos versionados e conflitos | F5 |
| `682b1bb` | Fase 4.4 | Indicadores determinísticos e seleção por página | F3, F4 |
| `9177c7f` | Fase 4.5 | Compactação semântica, omissões e grounding parcial | F6; reforço F10/F11 |
| `65a2d9b` | Histórico anterior | Planejamento contextual, recuperação adaptativa e combinação de resultados | F7 |
| `b33191d` | Histórico anterior | Pipeline híbrido, hashes/digest de embedding e validação estrutural | F9 |

O commit atual contém somente o pacote da Fase 4.5. A auditoria presente não
cria commit nem modifica a árvore funcional.

F8 compartilha a implementação versionada de metadados de `b203cbf`. F14 não
possui correção identificada: API e terminal ainda expõem somente o contrato
textual/mensagens. F15 é uma pendência metodológica, não um commit funcional.
F16 usa os contratos de evidência de `27551ce` e o reforço de `9177c7f`.
