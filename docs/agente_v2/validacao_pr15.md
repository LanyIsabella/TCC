# Validação direcionada da PR #15

## Escopo

Validação da branch `feat/agente-v2-agentic-rag` após a implementação do
planejamento agentic RAG. O escopo ficou restrito a planner, orquestração,
síntese, grounding, testes e rastreabilidade da V2. Não houve alteração em
V1, `client.py`, ingestão, Gold, embeddings, RRF, banco ou interface.

## Red–Green

- O primeiro ciclo dos contratos adicionados produziu 8 falhas reproduzíveis:
  retorno antecipado do planner, normalização contraditória de modo, retry de
  evidência temática, falha mista, fallback de síntese geral, flag paramétrica,
  classificação semântica e preservação de Markdown.
- Após as menores correções nos componentes existentes, os contratos passaram.
- Foi acrescentado um teste parametrizado para impedir que uma afirmação
  implícita seja liberada apenas por estar em modo geral: uma explicação geral
  permanece conversacional, enquanto a mesma classificação semântica como
  normativa resulta em `unsupported`.
- A consolidação de recuperações passou a unir páginas e evidências do mesmo
  documento por identidade documental e `evidence_id`, sem sobrescrever
  metadados.
- Classificador ausente, inválido, com erro ou parcial passou a ser tratado como
  inconclusivo; guardas conservadoras continuam protegendo regras implícitas.

## Verificação local

| Comando | Resultado |
|---|---|
| `uv run --locked pytest -q tests/test_agent_v2.py tests/test_grounding_policy.py` | 221 passed |
| `uv run --locked pytest -q` | 454 passed, 1 skipped, 9 xfailed |
| `uv run --locked ruff check .` | aprovado |
| `git diff --check` | aprovado |

## Verificação operacional

Foi executado o `AgentV2` real com Ollama `gemma4:e2b` e PostgreSQL local,
sem escrita no banco. As perguntas normativas sem fundamentação foram
publicadas como `unsupported`, sem IDs; explicações gerais foram respondidas
sem chamada de recuperação e sem limitação artificial de evidência. A pergunta
ampla sobre regras de formatação retornou um trecho temático inadequado nesta
execução, portanto a qualidade da recuperação/síntese ainda não é considerada
comprovada para esse caso.

Nenhuma conclusão desta execução trata similaridade, existência de ID ou teste
determinístico como prova de fidelidade factual da LLM.

### Casos exploratórios no HEAD final

| Pergunta | Modo | Grounding | Evidências publicadas | Observação |
|---|---|---|---|---|
| Como montar as referências bibliográficas de um livro? | `normative` | `unsupported` | nenhuma | fail-closed; documentos recuperados não sustentaram a resposta |
| Como fazer uma citação direta curta segundo a ABNT? | `normative` | `unsupported` | nenhuma | fail-closed; nenhum trecho foi publicado |
| Quais são as principais regras de formatação de um TCC segundo a ABNT? | `normative` | `supported` | `document:1:page:15` | resposta observada tratou citações, não cobriu todas as regras; limitação de pertinência |
| Qual a diferença entre pesquisa qualitativa e quantitativa? | `general` | `conversational` | nenhuma | explicação paramétrica sem recuperação |
| Explique os elementos pré-textuais de um TCC. | `general` | `conversational` | nenhuma | explicação conceitual sem recuperação |
| Pode me mostrar um exemplo? | `general` | `unsupported` | nenhuma | sem contexto recuperável para um exemplo seguro |

As consultas normativas registraram as consultas planejadas e os IDs
disponíveis no turno; a interface pública não expõe cada tentativa interna de
retry como uma mensagem separada. A resposta ampla de formatação não é tratada
como sucesso científico apenas porque o trecho publicado era documentalmente
válido.

## Limitações conhecidas

- A execução real depende da disponibilidade local do Ollama e do PostgreSQL;
  ela não substitui avaliação humana ou experimento controlado.
- Crapper, Dryer e Mutator do ub-mode permanecem incompletos conforme os
  relatórios existentes (cobertura/duplicações e timeout de workers); não são
  declarados aprovados.
- Não foram utilizados casos de holdout nem feitas alterações de infraestrutura.
