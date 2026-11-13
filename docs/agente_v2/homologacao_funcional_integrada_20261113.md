# Homologação funcional integrada do Agente V2

Data: 2026-11-13
Branch: `feat/agente-v2-stabilization`
HEAD de referência: `origin/master` (as correções desta rodada serão commitadas nesta branch)

## Escopo e ambiente

Esta verificação utilizou somente cenários de desenvolvimento. Não foram executados OCR, ingestão, migrações, alterações de Gold, embeddings, RRF ou operações de escrita no PostgreSQL.

- Ollama respondeu em `http://127.0.0.1:11434/api/tags` e expôs `gemma4:e2b` e `nomic-embed-text`.
- PostgreSQL foi validado somente com a consulta de leitura `SELECT current_database(), current_user`, retornando `postgres`/`postgres`.
- O entry point Streamlit foi iniciado com `streamlit run src/app/agente_v2/streamlit_app.py --server.headless true --server.port 8502`; a porta ficou em estado `Listen` e o processo foi encerrado após a verificação.

## Matriz de cenários

| Cenário | Evidência observada | Resultado |
|---|---|---|
| Consulta geral: `O que e literatura` | Planner conversacional/general, grounding `conversational`, nenhum tool call. A resposta conceitual foi preservada após a correção de grounding. | PASS |
| Consulta normativa `specific_10520_01` | Planner `normative_query`; a consulta focada recuperou NBR 10520 página 8; a afirmação sobre `autor-data`/`numérico` e consistência foi publicada com `grounded_answer`/`supported`. | PASS |
| Consulta ampla `broad_01` | A decomposição recuperou NBR 15287 página 5 e NBR 6023 página 12. Após uma segunda tentativa controlada, a resposta publicou somente a parte sustentada por NBR 15287 (`document:4:page:5`) e informou limitação explícita para a parte restante. | PASS — resposta parcial fundamentada |
| Continuidade `dialogue_01_t2` | O histórico foi recebido, a consulta foi contextualizada e a página 8 da NBR 10520 sustentou a paráfrase sobre sobrenome de pessoa física. A condição equivalente foi aceita sem relaxar conflitos explícitos. | PASS |
| Ambiguidade `boundary_11` (`Qual é a formatação certa?`) | Após a correção, o Planner determinístico retorna `ambiguous/clarify`, não executa tools e solicita um único esclarecimento. | PASS |
| Modo misto e falhas controladas | Testes determinísticos de síntese geral, falha de recuperação, grounding e publicação passaram. | PASS (automatizado) |
| Streamlit | Bootstrap e interação real validados; `tests/test_ui_app.py`: 13 aprovados. Evidências visuais em `smoke-20261113/`. | PASS — follow-up de recuo permanece limitação P2 fail-closed |

As respostas `unsupported` não foram classificadas automaticamente como aprovação ou reprovação; foram comparadas ao comportamento esperado e à proveniência registrada.

## Defeito reproduzido e correção

Uma explicação conceitual geral com várias frases era convertida em `unsupported` quando o classificador de afirmações retornava formato inválido. O grounding determinístico reconhecia apenas um conjunto estreito de marcadores conceituais e confundia prosa explicativa legítima com conteúdo não verificável.

Foi adicionada uma regressão em `tests/test_evidence.py` e ampliado, de forma conservadora, o conjunto de pistas conceituais em `src/app/grounding.py`. A alteração não concede exceção a afirmações com marcadores normativos ou estruturais; os testes existentes de falha fechada continuam aprovados.

Também foi adicionada uma regressão em `tests/test_agent_v2.py` para a pergunta subespecificada `Qual é a formatação certa?`. O fallback do Planner (`src/app/agente_v2/planner.py`) passou a reconhecer esse formato como ambíguo, preservando a solicitação de esclarecimento antes da recuperação.

O diagnóstico da consulta ampla também reproduziu um contrato incompleto: o modelo podia declarar uma consulta normativa sem fornecer `retrieval_queries`. O Planner agora exige consultas no prompt e preenche o campo ausente usando o planejador determinístico existente. Para consultas amplas, o Orchestrator executa todas as consultas explicitamente planejadas antes de consolidar os candidatos. Foram adicionadas regressões em `tests/test_agent_v2.py` e `tests/test_query_planner.py`.

Como a recuperação passou a disponibilizar os dois trechos esperados, o prompt do Synthesizer passou a exigir que afirmações sustentadas por fontes distintas sejam separadas em frases e associadas aos respectivos `evidence_id`. Uma segunda tentativa controlada é acionada quando a primeira resposta combina fontes ou seleciona apenas uma delas. Se a segunda tentativa continuar parcial, os IDs são normalizados somente quando o alias de página é unívoco e a limitação `evidence_unavailable` é registrada. Na execução real, `broad_01` terminou com `partial_answer`, publicou apenas a afirmação sustentada e não publicou a relação não comprovada.

Também foi corrigida uma rejeição indevida no grounding: o identificador textual `NBR 10520` não é uma medida normativa e não deve gerar conflito numérico; além disso, condições semanticamente equivalentes como `quando for pessoa física` e `quando se trata de pessoa física` não são exceções novas. Os testes de contradição explícita continuam cobrindo números, polaridade, modalidade e condições ausentes.

Por fim, `tests/test_grounding_policy.py` cobre uma seção incidental de referências dentro de uma norma de citações. `src/app/grounding.py` passou a rejeitar a NBR 10520 como fonte primária quando a pergunta trata exclusivamente de referências bibliográficas, evitando publicação de uma regra documental não pertinente. `plan_queries` e o Planner também reparam consultas pouco focadas sobre sistemas de chamada, preservando a infraestrutura de recuperação e seus parâmetros.

Não foram alterados embeddings, RRF ou a implementação de busca híbrida. A decomposição adicional é limitada ao planejamento da consulta e a resposta ampla continua podendo ser parcial quando uma das fontes não sustenta uma afirmação completa.

## Validação técnica

- `uv run --locked pytest -q`: **505 passed, 1 skipped, 9 xfailed** na branch de estabilização (as alterações experimentais de `rag_eval/baseline` permanecem fora desta entrega).
- Contratos direcionados (`tests/test_agent_v2.py`, `tests/test_evidence.py`, `tests/test_grounding_policy.py`): executados após as correções; os testes de agente/grounding totalizaram **250 passed**.
- `uv run --locked pytest -q tests/test_agent_v2.py`: **113 passed**.
- `uv run --locked pytest -q tests/test_query_planner.py`: aprovado, incluindo o reparo de consulta focada.
- `uv run --locked pytest -q tests/test_ui_app.py`: **13 passed**.
- `uv run --locked ruff check .`: aprovado.
- `git diff --check`: aprovado.

## Limitações e parecer

Os gates Crapper, Dryer e Mutator permanecem incompletos conforme o relatório ub-mode vigente; não são declarados aprovados. A homologação também não substitui avaliação científica, revisão humana ou comparação V1 × V2.

**Parecer: HOMOLOGADO COM RESSALVAS.** Os fluxos geral, normativo específico, resposta ampla parcial, continuidade contextual, ambiguidade, falhas controladas e bootstrap Streamlit foram verificados. A política permanece fail-closed quando a síntese não consegue separar fontes ou quando uma afirmação não é sustentada; nesses casos, publica somente a parte comprovada ou a limitação. Permanecem as limitações metodológicas dos gates Crapper/Dryer/Mutator e a necessidade de avaliação humana dos extratos, mas não há defeito funcional bloqueante reproduzido nos cenários de desenvolvimento executados.
