# Matriz consolidada F1–F16

As definições abaixo foram conferidas contra a baseline, os relatórios das
fases e a auditoria E2E disponível. Quando a fonte histórica não usa o rótulo
`F<n>`, isso é indicado explicitamente; o rótulo não foi retroinventado.

“Corrigido contratualmente” significa implementação e testes determinísticos.
Não significa prova de fidelidade factual geral.

| Defeito | Definição confirmada e fonte | Implementação/testes observáveis | Estado atual | Limitação ou risco |
|---|---|---|---|---|
| F1 | Gate Gold aceitava `success` legado sem revisão, nota ou método confiável (`docs/baseline_fase2.md`, matriz de defeitos). | `data/gold_policy.py`, `is_gold_ready()` e testes Gold/PG; `0852c43`. | Corrigido contratualmente | `allow_unvalidated` é bypass explícito; calibração independente continua pendente. |
| F2 | Force, conteúdo ou configuração alterados podiam reutilizar avaliação/identidade (`docs/baseline_fase2.md`, Fase 4.1). | Proveniência, fingerprint, invalidação e histórico append-only; `bf4c551`. | Corrigido contratualmente | Migrações só foram exercitadas em clusters isolados; sobreviventes históricos de mutação permanecem limitação. |
| F3 | Indicadores não distinguiam falha técnica, vazio, truncamento e corrupção textual (`docs/fase4_4/diagnostico_inicial.md`). | `assess_candidate()`, indicadores por página e testes de qualidade; `682b1bb`. | Parcialmente corrigido | Integridade técnica não demonstra fidelidade semântica; referência nativa não é ground truth. |
| F4 | Gold escolhia uma execução inteira e não uma decisão conservadora por página (`docs/fase4_4/diagnostico_inicial.md`). | Seleção Silver por página, `retry_required`/`quarantined`, integração Gold; `682b1bb`. | Parcialmente corrigido | Piloto de quatro páginas; candidato único pode ser `selected` apenas como decisão técnica. |
| F5 | Identidade, edição, publicação e vigência podiam ser colapsadas entre camadas (`docs/fase4_3/relatorio.md`). | Metadados versionados, conflitos e proveniência por campo; `b203cbf`. | Parcialmente corrigido | NBR6034 (edição 2004/vigência 2005) ainda requer confirmação humana; sem backfill. |
| F6 | Compactação por prefixo podia descartar regra tardia/condição (`docs/fase4_5/parecer_tecnico.md`). | Seleção semântica, omissões e grounding parcial; `9177c7f`. | Corrigido contratualmente | Estimador lexical de 1.200 tokens; tabelas entre páginas permanecem separadas. |
| F7 | Integridade da combinação de consultas e resultados: deduplicar sem somar RRF de escalas distintas, preservar páginas e tolerar falha parcial (auditoria E2E, seção C; implementação histórica de `_merge_documents()`). | Planejamento contextual, `_merge_documents()`, prioridade por hits e melhor RRF individual; testes em `tests/test_query_planner.py`; `65a2d9b`. | Corrigido contratualmente | A auditoria E2E não confirmou o caminho internamente; não há medição real no split de desenvolvimento. |
| F8 | Identificação normativa por código e ano, separando identidade canônica de edição (baseline: divergências de edição; Fase 4.3). | `normalize_standard_identifier()`, metadados `normative-metadata-v1` e testes de edições; `b203cbf`. | Parcialmente corrigido | A divergência NBR6034 permanece; a fonte do ano/edição ainda não foi humanamente adjudicada. |
| F9 | Degradação silenciosa dos embeddings: ausência, dimensão, texto divergente ou modelo alterado não poderiam passar sem sinalização (pipeline inicial `b33191d`, validação da Fase 4.1). | Hash de conteúdo, dimensão, status, digest/modelo e `validate_pipeline()`; testes de dimensão/proveniência. | Parcialmente corrigido | A validação estrutural não prova qualidade vetorial nem garante execução periódica; o digest ativo não é gate completo de consulta. |
| F10 | Recovery sem evidência preservava resposta normativa (`docs/baseline_fase2.md`, F10). | Grounding central e limitação explícita; `27551ce`, reforço de omissões em `9177c7f`. | Corrigido contratualmente | Não prova completude factual universal do LLM. |
| F11 | IDs/matched text ou sobreposição lexical podiam legitimar número/condição contraditórios (`docs/baseline_fase2.md`, F11; auditoria E2E §6). | Suporte por afirmação, números, modalidade, negação, exceções e testes de falsa recusa; `27551ce`/`9177c7f`. | Corrigido contratualmente | Cobertura semântica é limitada às formas testadas; juiz/modelo pode errar. |
| F12 | Evidência de tool/turno anterior podia substituir recuperação da pergunta atual (`docs/baseline_fase2.md`, F12). | `EvidenceTurn`, vínculo de execução e filtragem por turno; `27551ce`. | Corrigido contratualmente | Não houve avaliação holdout nem rodada real encadeada. |
| F13 | API aceitava papéis privilegiados fornecidos pelo cliente (`docs/baseline_fase2.md`, F13). | Schema/serviço rejeitam `system`/`tool` na fronteira pública; `27551ce`. | Corrigido contratualmente | Compatibilidade coberta nos clientes existentes, não em todos os adaptadores externos. |
| F14 | Evidências nas interfaces API e terminal: o contrato público deveria preservar/representar a rastreabilidade, não apenas a resposta textual (auditoria E2E §§5–6, observações de API/CLI atuais). | UI renderiza evidências; `AgentChatResponse` e `ChatSession` hoje retornam/imprimem apenas resposta e mensagens. Não há teste de evidência nesses dois canais. | Pendente funcional | Risco de perda de proveniência fora da UI; exige decisão de contrato antes de alterar API/terminal. |
| F15 | Representatividade linguística e normativa da avaliação (baseline `rag_eval/baseline/README.md`, protocolo de 120 consultas). | Dataset balanceia categorias e dez normas, mas expectativas/referências estão `pending_human_review`; sem estratos linguísticos ou validação humana. | Pendente experimental | Não é defeito corrigido por código; não anunciar generalização da amostra. |
| F16 | Proveniência das evidências apresentadas: cada trecho deve ligar texto, página, documento, versão e execução (auditoria E2E §6; `docs/fase4_5/proveniencia.md`). | IDs estáveis por página, hashes/metadata, `turn_id`, `question_sha256`, `tool_call_id`, query e omissões; testes de evidência/turnos; `27551ce`/`9177c7f`. | Corrigido contratualmente | API/terminal ainda não expõem o registro completo (ver F14); não substitui revisão factual. |

## Evidência executada

- Recorte determinístico desta consolidação: **83 aprovados**.
- Regressão final registrada na Fase 4.5: **414 aprovados, 1 ignorado**.
- Não houve ingestão, reindexação, uso do holdout, Crapper, Dryer ou Mutator
  nesta complementação.

## Limite da confirmação histórica

F7, F8, F9, F14, F15 e F16 não aparecem como linhas numeradas na matriz
`docs/baseline_fase2.md`. As definições acima são as correspondências
verificáveis mais próximas nos relatórios e no código; onde a fonte não permite
provar o enunciado original, o estado permanece parcial ou pendente.
