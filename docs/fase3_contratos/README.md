# Fase 3 — contratos críticos do agente RAG

## Escopo e estado

Correções de F10, F11, F12 e F13 na branch `fix/fase3-contratos-agente-20261110`,
derivada do HEAD `3a279ab5bfe1215521e0fd476faaec8eab563baa`. Não foram criados
commits nem executados deploy, migração, ingestão, OCR, embeddings ou escrita
no banco de produção. A UI, os PDFs, o recuperador, o planejador de consultas,
o RRF e o prompt principal foram preservados.

A implementação passou pelos contratos determinísticos descritos abaixo.
Isso não comprova a fidelidade factual de todas as respostas de um LLM.
A avaliação limitada com modelo real foi executada: o último ensaio atingiu o
contrato esperado em 24 de 24 cenários sintéticos. Uma recusa indevida de uma
versão intermediária foi preservada e motivou uma prova lógica dirigida.
A revisão humana e a avaliação
representativa do RAG completo permanecem pendentes. Veja
[EXPERIMENTO.md](EXPERIMENTO.md).

## Preparação e sequência incremental

1. Preservação da baseline da Fase 2 e abertura da branch de correção.
   [before.json](artifacts/before.json) registra os hashes anteriores;
   [before.xml](artifacts/before.xml) registra **139 aprovados, 1 ignorado e
   15 xfail** antes da implementação. O teste de defeitos anterior foi preservado
   em [baseline_defect_agent_before.py.txt](artifacts/baseline_defect_agent_before.py.txt).
2. Leitura dos contratos de caracterização e corrigidos; inspeção de
   `ScopedAgent`, ferramentas RAG, extração de evidências, schemas, serviço HTTP
   e consumidores UI/terminal. A UI já utiliza `extract_agent_result` e não
   exigiu alteração. API e terminal precisavam publicar a mesma decisão central.
3. F13: separação entre histórico público e mensagens internas, seguida de testes
   HTTP, objetos Python já existentes e replay do histórico da resposta.
4. F12: identificação por invocação, delimitação da pergunta atual e associação
   de chamadas/resultados de tools; testes de isolamento antes da integração.
5. F10/F11: política por afirmação, testes de contradições e de falsas recusas;
   integração após recuperação/síntese e nos consumidores públicos.
6. Refatoração de responsabilidades, validação da suíte, lint, cobertura,
   complexidade, duplicação, mutações e preservação dos artefatos.

## Problemas e decisões técnicas

### F10 e F11 — existência de evidência e suporte são contratos distintos

`grounding.py` decide quais afirmações podem ser publicadas. Um identificador
válido, `matched_text` preenchido e palavras em comum não constituem prova.
Os IDs sugeridos pelo gerador não autorizam as afirmações.

Uma sentença literal completa pode ser vinculada ao texto recuperado. Para
paráfrases não demonstradas literalmente, o modelo já existente avalia as
afirmações em uma chamada interna separada, retornando JSON estrito com índice,
decisão, ID e citação literal. A aplicação verifica a identidade, a presença da
citação no texto e conflitos explícitos antes de aceitar a decisão. Uma chamada
de verificação não é feita quando todas as afirmações já têm prova literal ou
quando não há evidências.

Os controles determinísticos verificam números, unidades equivalentes (por
exemplo, 2 cm e 20 mm), negações, modalidade obrigatória/opcional, limites
mínimo/máximo, condições e exceções. O contexto de uma citação preserva
sentenças de escopo e exceção no parágrafo, sem importar automaticamente a
negação de uma regra independente. Isso evita tanto omissão de condições
quanto algumas falsas recusas. A condição da própria pergunta pode delimitar a
resposta. O contexto acadêmico também vale para perguntas implícitas de
continuação, sem transformar evidências antigas em prova atual.

O sistema conserva somente as afirmações sustentadas, com os IDs de suas provas.
Uma resposta parcial inclui limitação explícita; nenhuma afirmação sustentada
resulta em mensagem de insuficiência documental. Uma falha, timeout, retorno
malformado ou `no_evidence` não preserva a resposta normativa candidata.
Saudações e esclarecimentos sem afirmações normativas continuam permitidos.

O ensaio real também motivou regressões específicas: aceita-se uma única cerca
Markdown ao redor de um JSON válido; entradas negativas com ID/citação nulos
não descartam uma entrada positiva comprovada. Provas positivas nulas continuam
rejeitadas. Conversões equivalentes de unidades, suas formas singulares e
limites negados equivalentes recebem normalização controlada para evitar falsas
recusas, mantendo a comparação da sentença inteira e os controles de contradição.
As falhas observadas, testes Red–Green e versões arquivadas estão em
[EXPERIMENTO.md](EXPERIMENTO.md).

Uma regra explícita de uso opcional permite comprovar a permissão do mesmo
objeto, sem depender do voto do modelo. Essa implicação é dirigida: permissão
não comprova opcionalidade. Mantêm-se as verificações de objeto, negação,
condições e exceções; não existe lista de termos favorecidos.

Pedidos explícitos de reescrita de texto fornecido pelo usuário podem seguir
sem prova documental quando não contêm afirmações normativas. Regressões
impedem usar esse caminho para publicar regras sem prova, inclusive com
“margem” ou “citação” no singular. Perguntas curtas como “Qual a fonte?”
também exigem fundamentação e podem acionar recuperação no turno atual.

`finalize_grounding` substitui a candidata pública e a saída estruturada por
essa decisão. Um objeto tipado com fingerprint vincula resposta, pergunta,
contexto normativo, turno e evidências. Os consumidores reutilizam a decisão
sem nova inferência; alteração de seus insumos invalida o reaproveitamento.
Esse mecanismo é local ao processo, não uma assinatura de autenticação externa.

Não foi criada tool, framework ou dependência. O prompt principal não mudou.
O prompt auxiliar de avaliação é necessário porque semântica e paráfrase não
podem ser comprovadas por IDs ou correspondência lexical. Essa etapa modifica
a metodologia de geração/verificação e pode adicionar latência: uma chamada ao
mesmo modelo em respostas que precisam de avaliação semântica. A latência e a
taxa representativa de recusas ainda precisam ser medidas no RAG completo;
os tempos e resultados do ensaio limitado foram registrados.

### F12 — proveniência por turno e execução

Cada invocação recebe UUID e hash da pergunta original. O identificador é
associado à mensagem atual sem reescrever sua pergunta. Somente eventos após
essa mensagem, enquanto ela ainda for a última pergunta, podem fornecer provas.
Nas execuções vinculadas, cada resultado RAG precisa de chamada anterior com
nome e `tool_call_id` correspondentes. Metadados de execução são produzidos
pelo servidor e prevalecem sobre campos recebidos no conteúdo da tool.

A recuperação direta emite um par de chamada/resultado válido para LangChain,
inclusive quando falha. Os registros de evidência carregam turno, hash da
pergunta, consulta executada e identificador da chamada. Histórico anterior
permanece como contexto conversacional, mas não impede nova recuperação.
Não se repete automaticamente uma tool já executada no turno apenas por ela
ter retornado erro ou ausência de evidências.

Adaptadores isolados sem envelope de turno continuam aceitando resultados
legados de tools após a última pergunta; essa compatibilidade não relaxa o
vínculo exigido em `ScopedAgent`. Clientes HTTP não podem fornecer esses eventos.
Nenhum dado de proveniência novo foi persistido no banco.

### F13 — papéis públicos e internos

`AgentChatRequest.history` aceita somente `user` e `assistant` por meio de
`PublicConversationMessage`. Papéis privilegiados ou aliases internos são
rejeitados com HTTP 422, inclusive instâncias construídas sem validação que
depois cruzem a fronteira pública. `ConversationMessage` mantém papéis internos
para os contratos necessários ao agente.

Clientes públicos existentes podem continuar enviando os mesmos campos e
reutilizando o histórico da resposta. Clientes que antes enviavam `system` ou
`tool` devem removê-los de requisições externas. A API publica apenas o histórico
público recebido, a pergunta atual e a resposta validada, sem candidatas
intermediárias ou fallback bruto da saída estruturada. O terminal usa a política
central e preserva o registro de falhas de execução/validação.

## Red–Green–Refactor

| Etapa | Evidência executada | Resultado observado |
|---|---|---|
| Contratos originais F10–F13, sem aplicar xfail | [contracts_red.xml](artifacts/contracts_red.xml) e [log](artifacts/contracts_red.log) | 6 falhas esperadas, 6 aprovados; F10: 1, F11: 2, F12: 1, F13: 2 falhas |
| Publicação API/terminal | [channels_red.xml](artifacts/channels_red.xml) → [channels_green.xml](artifacts/channels_green.xml) | 2 falhas/9 aprovados → 11 aprovados |
| Limites de condições/negação e falsa recusa opcional | [edge_red.xml](artifacts/edge_red.xml) → [policy_channels_green.xml](artifacts/policy_channels_green.xml) | 3 falhas/31 aprovados → 45 aprovados no conjunto ampliado |
| Última pergunta e resultado de tool sem chamada | [turn_edges_red.xml](artifacts/turn_edges_red.xml) → [turn_channels_green.xml](artifacts/turn_channels_green.xml) | 2 falhas/6 aprovados → 19 aprovados no conjunto ampliado |
| Continuação implícita | [implicit_red.xml](artifacts/implicit_red.xml) → [implicit_green.xml](artifacts/implicit_green.xml) | 1 falha → 48 aprovados no conjunto ampliado |
| Sentenças distintas do mesmo parágrafo | [context_red.xml](artifacts/context_red.xml) → [final_edges_green.xml](artifacts/final_edges_green.xml) | 2 falhas/2 aprovados → conjunto ampliado aprovado |
| Histórico de erro do terminal | [terminal_validation_red.xml](artifacts/terminal_validation_red.xml) → [final_edges_green.xml](artifacts/final_edges_green.xml) | 1 falha/3 aprovados → conjunto ampliado aprovado |
| Formatação Markdown sem falsa recusa | [markdown_red.xml](artifacts/markdown_red.xml) → [markdown_green.xml](artifacts/markdown_green.xml) | 2 falhas/2 aprovados → 54 aprovados na política |
| Opcionalidade implica permissão do mesmo objeto | [optional_permission_red.xml](artifacts/optional_permission_red.xml) → [optional_permission_green.xml](artifacts/optional_permission_green.xml) | 3 falhas/5 aprovados → conjunto ampliado aprovado |
| Reescrita e perguntas normativas curtas | [intent_edges_red.xml](artifacts/intent_edges_red.xml) → [intent_edges_green.xml](artifacts/intent_edges_green.xml) | 4 falhas/4 aprovados → conjunto ampliado aprovado |
| Recuperação para pergunta curta | [short_question_recovery_red.xml](artifacts/short_question_recovery_red.xml) → [short_question_recovery_green.xml](artifacts/short_question_recovery_green.xml) | 1 falha → conjunto ampliado aprovado |
| Singular de margem/citação na reescrita | [rewrite_inflection_red.xml](artifacts/rewrite_inflection_red.xml) → [rewrite_inflection_green.xml](artifacts/rewrite_inflection_green.xml) | 2 falhas/4 aprovados → 6 aprovados |

`grounding_red.xml` registra ausência inicial do novo módulo; é uma falha de
coleta, não é apresentada como demonstração comportamental de Red. A prova
comportamental inicial são os contratos corrigidos da baseline.

Os seis `xfail(strict=True)` corrigidos foram removidos. As caracterizações do
comportamento inseguro foram substituídas por regressões do contrato corrigido,
mantendo a cópia histórica. O contrato F12 passou a esperar a consulta
contextualizada já produzida pelo planejador existente, em vez de exigir a
consulta sem contexto. O planejador não foi alterado.

Fixtures antigas que tratavam texto relacionado ou metadados sem trechos como
suporte foram ajustadas para fornecer provas literais e pares de tool válidos.
Os testes de serialização da API usam uma interação sem afirmações normativas;
os casos normativos têm testes negativos próprios. Não se manteve um contrato
inseguro apenas para conservar expectativas antigas.

## Testes, controles e limitações

Resultado final: **291 aprovados, 1 ignorado e 9 xfail conhecidos**, conforme
[full_green.xml](artifacts/full_green.xml) e [log](artifacts/full_green.log).
Os seis contratos corrigidos passaram separadamente em
[contracts_final.xml](artifacts/contracts_final.xml). Os xfail restantes são
de F1, F2 e F6, fora desta entrega; não representam falhas ocultadas nesta fase.
O lint passou nos arquivos envolvidos: [ruff.log](artifacts/ruff.log).
A cobertura é medida com
`coverage` já instalado no ambiente isolado de ferramentas, sem instalação de
dependências ou mudança do projeto: schemas 100%, serviço HTTP 96%, agente 92%,
evidências 95%, política 99% e módulo do terminal 34%. Este último percentual
inclui o fluxo interativo antigo, não exercitado nesta fase. O agregado medido
desses seis módulos é 81%; não é cobertura do repositório inteiro.
[coverage.log](artifacts/coverage.log) contém o resultado executado.

O Crapper mediu **67 funções novas/alteradas**, identificadas por comparação
de AST com o HEAD preservado, todas com CRAP inferior a 10 (máximo 9):
[quality_scope.json](artifacts/quality_scope.json). A execução sobre arquivos
inteiros continua reprovada por cinco funções antigas que não foram alteradas;
isso está registrado, sem declarar aprovação global. O Dryer indicou dois
wrappers de validação de campos, revisados: a regra compartilhada já está em
`_nonempty_text`; os validadores de `message` e `content` mantêm contratos
distintos. Não foi introduzida uma hierarquia apenas para eliminar esse alerta.

Na política central, **70 mutantes foram executados e eliminados, sem
sobreviventes nem pontos não executados nesse conjunto de operadores**:
[mutator_policy_delivery_all_sites.log](artifacts/mutator_policy_delivery_all_sites.log). O resultado não
equivale a prova formal de correção. A primeira execução de mutações da API
falhou na limpeza de diretório por `WinError 32`; foi preservada em
[mutator_api.log](artifacts/mutator_api.log). Para evitar o bloqueio do OneDrive,
a verificação prosseguiu em cópia temporária de código/testes, com os mesmos
bytes e interpretador, sem corpus, `.env` ou banco. O workspace e os resultados
estão registrados nos artefatos; não se alterou a configuração global das ferramentas.

Duas tentativas finais na cópia temporária não encontraram cobertura da política
nos relatórios daquela cópia e não executaram seus 70 pontos. Os logs
`mutator_policy_delivery.log` e `mutator_policy_delivery_verified.log` preservam
essa incompletude e os erros de cópia associados. A execução conclusiva sincronizou
os bytes corretos e usou `--no-coverage --mutate-all` para executar todos os
70 operadores da política com a baseline de testes aprovada. A cobertura medida
separadamente na árvore principal continua registrada; não se inferiu cobertura
a partir dessas tentativas sem execução.

Resultados finais de mutação por escopo:

| Escopo | Eliminados | Sobreviventes | Não executados no escopo selecionado |
|---|---:|---:|---:|
| Política central | 70 | 0 | 0 |
| Schemas e serviço da API | 5 | 0 | 0 |
| Agente e evidências | 110 | 2 | 0 |
| `ChatSession.ask`, linhas 168–220 | 4 | 0 | 0 |

Os dois sobreviventes são as opções `ensure_ascii=False` dos JSONs enviados à
verificação/síntese. A troca por `True` não altera os dados após decodificar o
JSON, mas seu possível efeito nos tokens e no comportamento do modelo real
não foi avaliado. **O Mutator do agente não recebeu aprovação geral**; os
sobreviventes permanecem explícitos em
[mutator_agent_final_stage.log](artifacts/mutator_agent_final_stage.log),
reexecutado integralmente após as correções derivadas do modelo real.
A execução do terminal foi limitada à função alterada, não aos demais 21 pontos
do módulo. Os logs anteriores com sobreviventes e a falha de limpeza foram
mantidos, assim como os resultados finais da
[API](artifacts/mutator_api_post_experiment.log) e do
[terminal](artifacts/mutator_terminal_post_experiment.log), também reexecutados
após a atualização do componente de fundamentação.

A execução automática do Stop hook, anterior ao experimento real, **não passou**:
[hook_stop_report.json](artifacts/hook_stop_report.json). Seu Crapper registrou
falta de `coverage` no ambiente automaticamente escolhido e continua reprovando
as cinco funções antigas. Isso não invalida a medição manual com o ambiente
isolado já instalado, mas não autoriza declarar o hook aprovado. O Dryer também
reportou dois pares entre getters `_message_value` preexistentes em módulos
independentes, além dos wrappers de campos já revisados. Esses getters não foram
refatorados nesta fase. O Mutator automático esgotou o orçamento compartilhado:
52 mutantes eliminados, 160 pontos registrados como não cobertos/não concluídos,
exit code 124; não se interpretam timeouts como mutantes eliminados. Os três
logs foram preservados com o prefixo `hook_stop_`. Os hashes dos seis arquivos
de produção foram reconferidos após aquele hook. A atualização posterior de
`grounding.py`, motivada pelo experimento, recebeu nova execução da suíte e dos
controles manuais. Não foi iniciada limpeza ou refatoração fora do escopo para
silenciar os alertas antigos.

A verificação de preservação está em [preservation.json](artifacts/preservation.json):
24 arquivos congelados da baseline, 63 arquivos do pacote humano, 10 PDFs e 40
hashes de fontes fora do escopo conferidos. Snapshot:
`ba555e70267df221683c429d7ab6c965d03b73e64e7d1d2e52dbe0d1ace9ba99`.
Alterações anteriores de `.gitignore`, `pyproject.toml` e artefatos da Fase 2
foram preservadas.

Limitações e pendências de validação:

- O avaliador semântico é um LLM e pode errar. Uma citação real tampouco garante
  que a fonte esteja correta, atualizada ou completa. Erros de OCR, extração e
  compactação documental permanecem fora desta fase.
- As verificações linguísticas e numéricas detectam formas explícitas cobertas
  pelos testes. Não demonstram implicação lógica geral, correferência, relações
  entre múltiplos valores/entidades, tabelas complexas, unidades arbitrárias ou
  todas as construções de condição/exceção. Paráfrases podem ser recusadas quando
  não há prova suficiente para a aplicação confirmar a avaliação.
- O corpus recuperado e compactado limita a prova. A política não reconstrói
  trechos ausentes, não muda recuperação/RRF e não corrige F1–F9/F14–F16.
- O bloqueio inicial do Ollama foi resolvido pelo usuário, que iniciou o serviço
  já instalado. Não houve contorno da rejeição automática de `ollama serve` nem
  download. [experiment_status.json](artifacts/experiment_status.json) preserva
  essa sequência. O ensaio com `gemma4:e2b`, temperatura 0,7, mostrou 24 de 24
  resultados esperados na última execução real. O resultado adverso intermediário
  (20/21) permanece arquivado; a alteração posterior introduziu uma prova dirigida
  e genérica para uso opcional, coberta por TDD. A correção final de flexão no
  detector de reescrita recebeu testes e replay determinístico dos 24 registros
  reais, com argumentos e decisões idênticos; esse replay não é nova inferência.
  Não se alegam
  fidelidade geral, taxa populacional de recusas, desempenho de ponta a ponta ou
  avaliação humana comprovados. A baseline reservada não foi usada no ajuste.
- Os controles de qualidade devem ser lidos por escopo: funções novas/alteradas
  e resultados de mutação medidos não autorizam declarar aprovação geral de
  funções antigas não modificadas. Falhas de ferramentas permanecem registradas.

Esta entrega não inicia reconstrução de ingestão ou outras refatorações.

## Arquivos modificados nesta fase

| Arquivo | Responsabilidade da alteração |
|---|---|
| `src/app/grounding.py` (novo) | Política por afirmação, prova literal/semântica, conflitos e limitações |
| `src/app/evidence.py` | Turno atual, pares de execução, coleta válida, decisão central e fingerprint |
| `src/app/agente.py` | Vínculo da invocação, recuperação/síntese, avaliação e publicação segura |
| `src/api/schemas/agent.py` | Histórico público sem papéis privilegiados, compatibilidade e validação comum |
| `src/api/services/agent_service.py` | Pergunta confiável da requisição e histórico público com resposta validada; remoção dos adaptadores/fallbacks que ficaram sem uso |
| `src/terminal/main.py` | Consumo da resposta validada e preservação de registro de erros |
| `tests/test_grounding_policy.py` (novo) | Contradições, prova, parcialidade, avaliador e falsas recusas |
| `tests/test_agent_turns.py` (novo) | Isolamento de turno, pergunta, chamada, evidência e metadados |
| `tests/test_agent_contract_channels.py` (novo) | API/terminal, falhas, cache, continuação implícita e modelo simulado |
| `tests/test_agent_orchestration.py` (novo) | Evitar chamadas/recusas indevidas, preservar contexto recente e prefill interno LangChain |
| `tests/api/test_agent_router.py` | Rejeição HTTP de papéis internos, revalidação e replay público |
| `tests/api/test_agent_service.py` | Compatibilidade de representação e validação de mensagem vazia |
| `tests/test_agent_fallback.py` | Fixtures com provas e pares reais do contrato de tools |
| `tests/test_evidence.py` | Provas efetivas nas expectativas de seleção de evidências |
| `tests/test_scope_guard.py` | Fixture de recuperação com evidência efetiva |
| `tests/baseline/test_defect_agent.py` | Contratos corrigidos ativos e regressões; xfail de F6 preservados |
| `docs/fase3_contratos/` | Este relatório e evidências desta fase |

## Reprodução determinística

Na raiz do projeto, com o ambiente já existente:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests/baseline/test_defect_agent.py -k 'contract and (f10 or f11 or f12 or f13)' -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests/test_grounding_policy.py tests/test_agent_turns.py tests/test_agent_contract_channels.py -q -p no:cacheprovider
```

Os testes simulam modelos e recuperações. Não requerem Ollama, embeddings ou
escrita no banco. O teste optativo de integração já ignorado na baseline
continua dependendo de sua configuração externa.

## Conferência do último hook Stop

O relatório atualizado foi lido após a entrega e arquivado em
[hook_stop_final_report.json](artifacts/hook_stop_final_report.json), com os
três logs `hook_stop_final_*.log`. **O hook continua reprovado/incompleto**:
Crapper sem `coverage` no ambiente selecionado automaticamente e cinco violações
antigas; Dryer com os wrappers e getters já revisados; Mutator com exit code 124
por esgotamento do orçamento. O resumo automático registra 75 mutantes eliminados
e 160 pontos não cobertos/não concluídos, sem comprovar execução integral.
Esse resumo não substitui os ensaios manuais delimitados descritos acima.
Os seis hashes de produção permanecem idênticos aos da entrega. Nenhum código,
teste, dependência ou configuração foi alterado para silenciar o hook.
