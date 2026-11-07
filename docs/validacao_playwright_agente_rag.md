# Validação end-to-end do agente RAG com Playwright

## 1. Escopo e método

Validação funcional realizada em 07/11/2026, utilizando a interface real do Streamlit em `src/ui/app.py`, o modelo Ollama configurado e os documentos indexados no PostgreSQL. Não foram usados mocks e nenhuma alteração de implementação foi feita durante esta execução.

Foram executados os seis cenários obrigatórios, os testes complementares A e B, a verificação de expansão/recolhimento das evidências e a verificação de Nova conversa. A avaliação de pertinência documental foi feita comparando o texto exibido na resposta com os trechos apresentados pela própria aplicação.

Os snapshots YAML preservam a árvore de acessibilidade completa de cada execução. As imagens preservam a resposta e, quando aplicável, o componente de evidências expandido.

## 2. Ambiente

| Item | Valor observado |
|---|---|
| Data e horário | 07/11/2026, aproximadamente 15:06–15:12 BRT |
| Commit observado | `0257be1` |
| Interface | Streamlit `1.65.0`, `src/ui/app.py`, porta `8504` |
| Playwright | pacote Python `1.62.0`, execução pelo MCP Playwright |
| Ollama | disponível em `http://localhost:11434` |
| Modelo de geração | `gemma4:e2b` |
| Modelos auxiliares observados | `nomic-embed-text:latest`, `glm-ocr:latest` |
| PostgreSQL | TCP em `localhost:5432` acessível |
| Saúde do Streamlit | `GET /_stcore/health` retornou `ok` |
| Console do navegador | 0 erros e 0 avisos em todos os cenários coletados |

O worktree já continha alterações nos arquivos do agente, RAG, evidências, API e testes antes da validação. Nesta etapa foram adicionados somente os artefatos de validação e este relatório.

### Instrumentação disponível

Os módulos possuem logs para escopo, reformulação, recuperação, fallback e seleção de evidências, mas o processo Streamlit não expôs esses registros durante a execução: o stdout do servidor mostrou apenas a inicialização. Portanto, decisões internas como `scope_decision`, consulta reformulada, IDs rejeitados e fallback não puderam ser confirmadas diretamente pelos logs. Elas foram marcadas como não verificáveis sempre que a interface não permitiu inferi-las com segurança.

## 3. Resultados consolidados

| Cenário | Resultado | Tempo aproximado | Problemas identificados |
|---|---:|---:|---|
| 1 — Formatação ampla de TCC | **REPROVADO** | 49 s | Resposta detalhada, mas documentos e trechos não sustentam de forma confiável as afirmações. |
| 2 — Continuidade: tamanho do recuo | **REPROVADO** | 27 s | A pergunta não foi respondida; a resposta tratou de resumos, resenhas e recensões. |
| 3 — “Como faço isso no Word?” | **REPROVADO** | 20 s | Houve interpretação contextual parcial, mas a resposta desviou para margens, fonte e espaçamento, sem orientar o recuo discutido. |
| 4 — Citação direta x indireta | **REPROVADO** | 15 s | Texto coerente, porém a fonte exibida foi a norma de índice e o trecho expandido não sustentava a resposta. |
| 5 — Referências x citações | **REPROVADO** | 13 s | Comparação coerente, mas somente uma fonte de citações foi apresentada para dois assuntos normativos. |
| 6 — Margem de lucro | **APROVADO COM RESSALVAS** | 8 s | Recusa adequada e sem referência acadêmica; a ausência de consulta RAG não foi confirmada por log. |
| A — Fotossíntese | **APROVADO COM RESSALVAS** | 14 s | Não houve falso positivo lexical de “tese”, mas o agente respondeu fora do domínio acadêmico em vez de recusar. |
| B — Tamanho da margem, sem contexto | **APROVADO COM RESSALVAS** | 10 s | Assumiu interpretação acadêmica coerente e sem histórico inventado, mas não pediu esclarecimento sobre a ambiguidade. |
| C — Recuperação adaptativa | **APROVADO COM RESSALVAS** | observado no cenário 1 | Não ocorreu exceção visível e múltiplos documentos apareceram, mas a consolidação, deduplicação e pontuação não foram confirmáveis pela UI. |
| D — Sustentação documental | **REPROVADO** | — | Em pelo menos quatro respostas, a fonte/trecho exibido era inadequado ou insuficiente para as afirmações. |
| E — Interface e histórico | **APROVADO COM RESSALVAS** | — | Expansão/recolhimento, histórico e Nova conversa funcionaram; nova execução RAG via WebSocket não pôde ser comprovada apenas pelo inventário de rede. |

## 4. Análise dos cenários obrigatórios

### Cenário 1 — “Quais são as principais regras de formatação de um TCC?”

Contexto: conversa nova.

Resposta produzida: o agente reconheceu o tema e apresentou uma resposta extensa, organizada em “Estrutura Geral e Formato”, “Margens”, “Fonte e Espaçamento”, “Paginação e Estrutura de Seções”, “Elementos Pré-textuais”, “Citações e Referências”, “Anexos e Apêndices” e “Formato da Folha”. Entre as afirmações, informou margens de 3 cm/2 cm, fonte 12, espaçamento 1,5, A4 e citou a `ABNT NBR 15287:2025`.

Documentos exibidos:

- `Artigo científico — Apresentação (2018)`;
- `Informação e documentação — Projeto de pesquisa — Apresentação (2025)`.

Evidências expandidas:

- Trecho 1 continha o texto “decimentos”, regras gerais e “Recomenda-se fonte em tamanho 12 e espaçamento simples, padroniz...”;
- Trecho 2 começava por “MBALAGENS PARA INSTRUMENTOS MÉDICOS” e apresentava “5 Regras gerais” de projetos de pesquisa.

Os trechos não correspondem de maneira suficiente ao conjunto de regras de formatação de TCC apresentado. O segundo trecho é especialmente incompatível com a resposta e indica ruído de recuperação. A resposta também mencionou `ABNT NBR 10520 para tabelas`, afirmação que não foi sustentada pelo recorte exibido.

Artefatos: [resposta](validacao_playwright_assets/cenario1_resposta.yml), [resposta em imagem](validacao_playwright_assets/cenario1_resposta.png), [evidências](validacao_playwright_assets/cenario1_evidencias.yml), [evidências em imagem](validacao_playwright_assets/cenario1_evidencias.png).

Critérios atendidos: reconhecimento do domínio, ausência de recusa, resposta própria e relativamente abrangente, funcionamento visual do rodapé.

Critérios não atendidos: pertinência das fontes, sustentação documental, confiabilidade da recuperação ampla e associação entre afirmações e evidências.

Resultado: **REPROVADO**.

### Cenário 2 — “Qual o tamanho do recuo necessário?”

Contexto: mesma conversa do cenário 1, após a pergunta ampla.

Resposta produzida: a resposta iniciou com “Com base nos trechos fornecidos, o documento trata das regras para a redação e apresentação de Resumos, Resenhas e Recensões” e continuou explicando definições, resumo informativo, terceira pessoa, palavras-chave e extensão de resumos.

Documento exibido:

- `Informação e documentação — Resumo, resenha e recensão — Apresentação (2021)`.

Evidências expandidas: os trechos eram sobre “4 Resumo, resenha e recensão”, “Resumo: apresentação concisa...” e “Resumo indicativo...”. Nenhum recorte apresentava recuo de parágrafo, recuo de citação direta ou configuração equivalente.

A interface preservou corretamente o histórico visual: mostrou `2 perguntas nesta conversa` e a última pergunta correta. Isso não compensou a falha de planejamento/recuperação contextual.

Artefatos: [resposta](validacao_playwright_assets/cenario2_resposta.yml), [resposta em imagem](validacao_playwright_assets/cenario2_resposta.png), [evidências](validacao_playwright_assets/cenario2_evidencias.yml), [evidências em imagem](validacao_playwright_assets/cenario2_evidencias.png).

Critérios atendidos: a pergunta não foi recusada; o histórico de quantidade e última pergunta foi mantido.

Critérios não atendidos: continuidade temática, interpretação de “recuo”, recuperação pertinente e sustentação da resposta.

Resultado: **REPROVADO**.

### Cenário 3 — “Como faço isso no Word?”

Contexto: mesma conversa dos cenários 1 e 2; o antecedente imediato era “Qual o tamanho do recuo necessário?”.

Resposta produzida: o agente identificou que “isso” se referia a regras de formatação no Word, mas generalizou o assunto para margens, fonte e espaçamento. Orientou menus como `Layout`, `Margens`, `Margens Personalizadas`, `Página Inicial` e `Parágrafo`, além de indicar margens de 3 cm/2 cm, fonte 12 e espaçamento 1,5.

Documento exibido:

- `Informação e documentação — Citações em documentos — Apresentação (2023)`.

O texto não apresentou um passo a passo específico para configurar o recuo de parágrafo ou o recuo de citação no Word. A resposta foi contextualizada apenas de forma ampla e não respondeu ao antecedente mais provável.

Artefatos: [resposta](validacao_playwright_assets/cenario3_resposta.yml), [resposta em imagem](validacao_playwright_assets/cenario3_resposta.png), [evidências](validacao_playwright_assets/cenario3_evidencias.yml), [evidências em imagem](validacao_playwright_assets/cenario3_evidencias.png).

Resultado: **REPROVADO**.

### Cenário 4 — “Qual a diferença entre citação direta e indireta?”

Contexto: conversa nova.

Resposta produzida: explicou citação direta como transcrição exata e citação indireta como paráfrase, diferenciou aspas, página, autor/ano e apresentou quadro comparativo.

Documento exibido:

- `Informação e documentação — Índice — Apresentação (2005)`.

Evidência expandida: o trecho iniciava por “Esta Norma estabelece os requisitos de apresentação e os critérios básicos para a elaboração de índices.” Isso não sustenta a explicação sobre citações.

A qualidade linguística da resposta não deve ser confundida com fundamentação documental. O cenário falhou justamente no vínculo entre resposta, documento e trecho original.

Artefatos: [resposta](validacao_playwright_assets/cenario4_resposta.yml), [resposta em imagem](validacao_playwright_assets/cenario4_resposta.png), [evidências](validacao_playwright_assets/cenario4_evidencias.yml), [evidências em imagem](validacao_playwright_assets/cenario4_evidencias.png).

Resultado: **REPROVADO**.

### Cenário 5 — “Quais são as diferenças entre as regras de referências e citações?”

Contexto: conversa nova.

Resposta produzida: diferenciou citação como menção no corpo do texto e referência como lista detalhada ao final, usando uma tabela comparativa.

Documento exibido:

- `Informação e documentação — Citações em documentos — Apresentação (2023)`.

Evidências expandidas:

- Trecho 1: cabeçalho e escopo da norma de citações;
- Trecho 2: “Na lista de referências” seguido de um exemplo bibliográfico.

O conteúdo é parcialmente compatível com a comparação, mas não houve documento específico de referências apresentado, nem evidência suficiente para todas as regras descritas. O requisito de recuperar e identificar fontes pertinentes aos dois assuntos não foi atendido.

Artefatos: [resposta](validacao_playwright_assets/cenario5_resposta.yml), [resposta em imagem](validacao_playwright_assets/cenario5_resposta.png), [evidências](validacao_playwright_assets/cenario5_evidencias.yml), [evidências em imagem](validacao_playwright_assets/cenario5_evidencias.png).

Resultado: **REPROVADO**.

### Cenário 6 — “Qual é a margem de lucro ideal?”

Contexto: conversa nova.

Resposta produzida: “Entendo a pergunta, mas meu foco é ajudar com normas acadêmicas, ABNT, citações, referências, formatação e estrutura de trabalhos acadêmicos. Não consigo orientar sobre esse assunto; se quiser, posso ajudar com uma dúvida acadêmica.”

Não foi exibido documento de referência nem componente de evidências. A resposta atende ao limite de domínio e não reinterpretou artificialmente “margem de lucro” como margem acadêmica.

A ausência de RAG foi inferida pela resposta imediata e pela ausência de fontes na UI; não há log técnico disponível para confirmá-la.

Artefato: [resposta](validacao_playwright_assets/cenario6_resposta.yml), [resposta em imagem](validacao_playwright_assets/cenario6_resposta.png).

Resultado: **APROVADO COM RESSALVAS**.

## 5. Testes complementares

### A — Falso positivo lexical: “O que é fotossíntese?”

O sistema não recusou a pergunta por encontrar a sequência de caracteres semelhante a “tese”. Isso indica que a correção de correspondência lexical por limites de palavra evitou esse falso positivo específico.

Por outro lado, o agente produziu uma explicação extensa de biologia, incluindo equação, cloroplastos, glicose, oxigênio e fases fotoquímica e química. Não apresentou fonte acadêmica nem recusa de domínio. Portanto, o teste lexical foi positivo, mas a política de especialização ficou permissiva demais para mensagens classificadas como incertas.

Resultado: **APROVADO COM RESSALVAS**.

Artefatos: [resposta](validacao_playwright_assets/complementar_A_resposta.yml), [resposta em imagem](validacao_playwright_assets/complementar_A_resposta.png).

### B — Ambiguidade sem contexto: “Qual o tamanho da margem?”

Em conversa nova, o sistema assumiu que “margem” significava margem de trabalho acadêmico e respondeu com 3 cm na parte superior/esquerda e 2 cm na inferior/direita, mencionando a necessidade de consultar o manual institucional.

Documento exibido: `Informação e documentação — Trabalhos acadêmicos — Apresentação (2024)`.

O comportamento não inventou histórico anterior e foi coerente com o domínio do produto. Entretanto, a resposta não explicitou a ambiguidade nem solicitou confirmação. O trecho expandido exibiu principalmente o cabeçalho da `ABNT NBR 14724`, sem mostrar no recorte a regra concreta das margens que aparecia na resposta.

Resultado: **APROVADO COM RESSALVAS**.

Artefatos: [resposta](validacao_playwright_assets/complementar_B_resposta.yml), [resposta em imagem](validacao_playwright_assets/complementar_B_resposta.png), [evidências](validacao_playwright_assets/complementar_B_evidencias.yml), [evidências em imagem](validacao_playwright_assets/complementar_B_evidencias.png).

### C — Recuperação adaptativa e `_merge_documents()`

O cenário 1, que é amplo, terminou sem exceção visível e exibiu dois documentos de referência e dois trechos. Isso indica que o fluxo adaptativo e a consolidação chegaram ao fim em execução real.

Não foi possível confirmar pela interface:

- a consulta original e as consultas expandidas;
- a execução efetiva de `_merge_documents()`;
- a política de deduplicação;
- a preservação de páginas;
- a combinação das pontuações sem soma indevida;
- o comportamento em falha parcial de uma consulta complementar.

Resultado: **APROVADO COM RESSALVAS** para ausência de exceção no caminho observado; a correção algorítmica completa permanece não verificável por este teste visual.

### D — Evidências documentais

Foram comparadas evidências de pelo menos cinco respostas com RAG. Os resultados foram:

- Cenário 1: trechos de artigo/projeto de pesquisa e até um trecho iniciado por “MBALAGENS PARA INSTRUMENTOS MÉDICOS” para responder sobre TCC;
- Cenário 2: trechos sobre resumos para responder sobre recuo;
- Cenário 3: fonte de citações para uma orientação genérica de Word, sem trecho específico de recuo;
- Cenário 4: trecho da norma de índices para explicar citações diretas e indiretas;
- Cenário 5: fonte de citações com um exemplo de lista de referências, insuficiente para cobrir os dois conjuntos normativos;
- Cenário B: documento de trabalhos acadêmicos, mas o recorte exibido não mostrava a regra concreta de margens.

Resultado: **REPROVADO**. A existência de documento e trecho não garantiu suporte semântico às afirmações.

### E — Interface, histórico e expansão

Resultados observados:

- “Conversa atual” mostrou `1`, `2` e `3 perguntas nesta conversa` conforme as mensagens eram adicionadas;
- a última pergunta exibida foi atualizada corretamente, não permanecendo na penúltima;
- as evidências permaneceram vinculadas à resposta correspondente durante o histórico;
- “Nova conversa” limpou a conversa visível e retornou a tela inicial;
- o status “Consulta concluída” apareceu após a geração;
- “Trechos que sustentam a resposta” iniciou recolhido, abriu ao clique e voltou a recolher por clique direto no elemento `summary`;
- não apareceram mensagens duplicadas nem erros de renderização;
- a expansão não exibiu uma nova resposta ou novo status de geração.

O inventário de rede mostrou apenas requisições de saúde/telemetria e chamadas internas do Streamlit; como a comunicação de execução ocorre por WebSocket, não foi possível usar esse inventário sozinho para provar ausência de uma nova chamada RAG.

Resultado: **APROVADO COM RESSALVAS**.

Artefatos de rede: [após recolhimento](validacao_playwright_assets/complementar_B_network_after_collapse.txt).

## 6. Problemas encontrados

### Alto — Evidências aceitas sem suporte semântico suficiente

**Comportamento observado:** respostas plausíveis foram associadas a documentos e recortes que tratavam de índices, resumos, embalagens ou projetos de pesquisa.

**Comportamento esperado:** somente trechos que sustentem as afirmações da resposta devem aparecer como referências.

**Evidência:** cenários 1, 2, 3, 4 e 5, com snapshots e imagens acima.

**Componente provável:** `src/app/evidence.py`, `src/app/agente.py` e `src/ui/app.py`.

**Causa técnica provável, confirmada por inspeção:** `_supports_answer()` aceita imediatamente qualquer evidência que possua `matched_text` não vazio. Além disso, quando não há saída estruturada, `_fallback_evidence_ids()` usa sobreposição lexical. Esses mecanismos validam pertencimento ao conjunto recuperado, mas não demonstram que o trecho sustenta a afirmação gerada.

**Recomendação:** manter a validação de IDs, mas exigir uma relação claim/evidence mais forte antes de exibir o trecho; quando essa relação não puder ser comprovada, omitir a referência.

### Alto — Falha de recuperação contextual para pergunta complementar

**Comportamento observado:** “Qual o tamanho do recuo necessário?” foi respondida com conteúdo de resumos e recensões.

**Comportamento esperado:** reformular a consulta preservando o contexto de formatação e recuperar recuos de parágrafo/citação.

**Componente provável:** `src/app/query_planner.py`, `src/app/tools/rag_search.py` e o caminho de síntese em `src/app/agente.py`.

**Causa:** a interface confirma o histórico visual, mas o resultado documental observado não acompanha o tema anterior. Os logs de consulta reformulada não estavam disponíveis para diferenciar erro de reformulação de erro de ranqueamento.

**Recomendação:** registrar a consulta contextual final e auditar os candidatos recuperados antes da síntese; adicionar um teste end-to-end que exija termos de recuo na evidência.

### Alto — Vazamento de domínio para pergunta incerta

**Comportamento observado:** “O que é fotossíntese?” recebeu uma aula de biologia.

**Comportamento esperado:** não tratar a pergunta como acadêmica apenas por semelhança lexical e, para um assistente especializado, recusar ou pedir esclarecimento quando não houver relação com normas acadêmicas.

**Componente provável:** `src/app/scope_guard.py` e o fluxo de `UNCERTAIN` em `src/app/agente.py`.

**Causa técnica provável:** o filtro evita corretamente o falso positivo de “tese”, mas mensagens incertas seguem para interpretação/geração sem uma confirmação semântica de domínio suficientemente conservadora.

**Recomendação:** separar “não é falso positivo lexical” de “é permitido responder fora do domínio”; usar uma decisão de escopo mais conservadora para perguntas incertas sem contexto acadêmico.

### Médio — Fallback gera respostas completas a partir de contexto inadequado

**Comportamento observado:** cenários 1–5 apresentaram respostas longas e bem formatadas mesmo quando o documento recuperado era inadequado.

**Componente provável:** `_synthesize_from_retrieval()` em `src/app/agente.py`.

**Causa técnica provável:** a síntese recebe o payload RAG e produz uma resposta final, mas não há uma verificação claim-level posterior que impeça o modelo de preencher lacunas com uma narrativa plausível.

**Recomendação:** tratar baixa pertinência documental como insuficiência de evidência, não como convite para uma síntese abrangente; limitar a resposta às afirmações suportadas e explicitar lacunas.

### Médio — Recortes exibidos são curtos ou não contêm a afirmação sustentada

**Comportamento observado:** no cenário B, a evidência mostrada continha principalmente cabeçalho da NBR 14724; no cenário 1, os recortes eram fragmentos com ruído.

**Componente provável:** seleção de `matched_text` em `src/app/tools/rag_search.py` e renderização em `src/ui/app.py`.

**Recomendação:** selecionar o recorte por afirmação/termo normativo, preservar contexto suficiente e rejeitar recortes que contenham somente metadados ou cabeçalhos.

### Médio — Falta de observabilidade durante o E2E

**Comportamento observado:** não foi possível confirmar escopo, consulta contextual, IDs estruturados, IDs rejeitados, fallback e documentos candidatos pelos logs do servidor.

**Componente provável:** configuração de logging dos módulos `src/app/*` quando executados pelo Streamlit.

**Recomendação:** disponibilizar logs técnicos em arquivo ou saída configurável para ambiente de teste, sem expor esses dados na UI e sem registrar credenciais ou conteúdo sensível desnecessário.

## 7. Verificações automatizadas complementares

Comandos executados após a validação:

```text
python -m pytest -q -rs
83 passed, 1 skipped in 7.63s
SKIPPED: tests/test_gedweb_playwright.py — RUN_GEDWEB_PLAYWRIGHT=1 não definido
```

```text
python -m ruff check src tests
All checks passed!
```

O teste Playwright do GEDWeb foi mantido como não executado porque depende de configuração externa e não faz parte da validação do chatbot local. Os cenários deste relatório, por sua vez, foram executados diretamente pelo MCP Playwright contra o Streamlit real.

## 8. Conclusão

1. **O agente deixou de ser excessivamente restritivo?** Parcialmente. A pergunta de margem de lucro foi recusada corretamente e o falso positivo lexical de “fotossíntese” não ocorreu, mas perguntas incertas podem receber respostas fora do domínio.
2. **O histórico conversacional funciona?** A interface preserva contagem, última pergunta e mensagens. A continuidade semântica não funciona de modo confiável: “recuo” foi desviado para resumos.
3. **Perguntas amplas geram respostas completas?** Geram respostas longas e organizadas, mas a completude não é confiável porque as evidências recuperadas não sustentam o conteúdo.
4. **A recuperação adaptativa está funcional?** O caminho amplo concluiu sem exceção visível e retornou múltiplos documentos. Deduplicação, ordenação e pontuações não foram verificáveis pelo E2E visual.
5. **As fontes são pertinentes?** Não de forma consistente. Foram observadas fontes de índices, resumos, projetos de pesquisa e embalagens em respostas sobre formatação e citações.
6. **As evidências sustentam as respostas?** Não. Esse foi o principal problema encontrado.
7. **O comportamento se aproxima de um assistente generativo com RAG?** A camada conversacional e visual se aproxima, mas a rastreabilidade documental ainda não é confiável o suficiente para considerar o comportamento pronto.
8. **O que ainda precisa ser corrigido?** A prioridade é impedir que recortes apenas lexicalmente relacionados sejam apresentados como sustentação, auditar a recuperação contextual de perguntas curtas, tornar o fallback consciente de insuficiência de evidência, reforçar o limite de domínio para mensagens incertas e habilitar observabilidade técnica no E2E.

## 9. Artefatos de execução

Os artefatos estão em [`docs/validacao_playwright_assets`](validacao_playwright_assets/), incluindo snapshots YAML, screenshots de resposta, screenshots de evidências expandidas, arquivos de console e a inspeção de rede após recolher o componente.

