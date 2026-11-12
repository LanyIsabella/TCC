# Comparação das interfaces Streamlit V1 e V2

## Escopo

A interface V2 foi alinhada visualmente à V1 sem importar `build_agent()` nem
alterar `src/ui/app.py`, o agente V1 ou a infraestrutura de recuperação.
Ambas usam a identidade **Normas Acadêmicas**, os mesmos textos de apoio,
ícones Material, sugestões iniciais e organização de sidebar.

## Paridade de apresentação

| Área | V1 | V2 após o ajuste |
| --- | --- | --- |
| Página | `Normas Acadêmicas`, ícone `menu_book`, layout `wide`, sidebar expandida | Igual |
| Cabeçalho | Título e descrição acadêmica | Igual |
| Sidebar | Identidade, `Nova conversa`, resumo, ajuda e escopo | Igual, com estado V2 isolado |
| Tela inicial | Container `Comece por uma pergunta` e `st.pills` | Igual; sugestões chamam `AgentV2` |
| Mensagens | Avatares Material e Markdown | Igual |
| Consulta | `st.status` compacto com estados de consulta | Igual |
| Evidências | Documento, trechos e página em bloco expansível | Igual, filtrando IDs publicados pelo grounding |

## Contratos preservados

- O payload enviado ao agente contém somente mensagens `user`/`assistant` e a
  pergunta atual; metadados visuais não entram no histórico do modelo.
- A V2 continua usando `conversation_id_v2`, `AgentV2` e o
  `ConversationStore` interno.
- Cada mensagem de assistente mantém `turn_id` e seu registro de apresentação,
  evitando associação por índice entre reruns e respostas sem evidência.
- `Nova conversa` cria outro ID, limpa mensagens, sugestões e apresentações,
  sem reutilizar documentos ou esclarecimentos da conversa anterior.

## Política de evidências

`published_evidence_ids` é a única fonte de autorização visual. Evidências
disponíveis ou selecionadas que não estejam publicadas não aparecem na tela.
O recorte usa `matched_text` quando presente e `text` como fallback, mantendo
título, versão e página. Trechos equivalentes são deduplicados e nenhuma nova
consulta é feita para preencher a interface.

Resultados `partial` preservam resposta e limitações; `unsupported` exibe
somente a limitação; conversas e esclarecimentos não exigem evidências.

## Testes

Os testes headless cobrem bootstrap do entry point, configuração visual, tela
inicial, envio por sugestão, reruns sem duplicação, isolamento de `Nova
conversa`, associação por `turn_id` e rejeição de evidências não publicadas.

Validação visual interativa depende de navegador disponível. Quando o navegador
estiver bloqueado, o resultado deve ser registrado como limitação e não como
homologação visual completa.

## Validação executada

- Testes direcionados de UI: `9 passed`.
- Suíte completa: `418 passed, 1 skipped, 9 xfailed`.
- `uv run --locked ruff check .`: aprovado.
- `git diff --check`: aprovado.
- Bootstrap real com `uv run --locked streamlit run
  src/app/agente_v2/streamlit_app.py --server.port 8504`: HTTP 200, título
  `Streamlit`.
- Fluxo real somente leitura com Ollama `gemma4:e2b` e PostgreSQL:
  `Como fazer referências?` solicitou esclarecimento; `Elementos` e `E
  formatação das referências?` produziram respostas `partial`, sem retorno ao
  esclarecimento, com IDs publicados pertencentes às evidências do turno.

A validação visual interativa com Playwright/CUA permaneceu indisponível por
bloqueio do navegador no Windows. Os gates ub-mode globais continuam
incompletos (CRAP/duplicações/Mutator timeout) e não são tratados como
aprovação.
