# PR #14 — Correção final e caracterização pós-auditoria

Data: 2026-11-12
Branch: `fix/agente-v2-post-merge`
Base auditada: `b047df4143d1746e393d704ba7dea5fdf0b0e956`

Este relatório registra a correção do defeito P1 reproduzido na auditoria
independente e as investigações dos casos P2. Não houve alteração de V1,
`client.py`, ingestão, Bronze/Silver/Gold, embeddings, RRF ou banco produtivo.

## A. Defeito P1 — follow-up reclassificado após grounding

### Reprodução RED

Foi adicionado o teste determinístico
`test_three_turn_reference_follow_up_preserves_partial_grounding`, com o fluxo:

```text
Como fazer referências? → Elementos → E formatação das referências?
```

Antes da correção, a execução do teste falhou com:

```text
AssertionError: assert 'conversational' == 'partial'
```

O terceiro turno já tinha consulta contextualizada, síntese parcial, grounding
executado e ID selecionado, mas o resultado era substituído pelo esclarecimento
anterior.

### Causa confirmada

`_normative_turn()` aplicava `_clarification_after_unsupported_broad_query()`
depois da síntese e do grounding sempre que a pergunta original parecia ampla.
`E formatação das referências?` satisfazia a heurística de pergunta ampla,
apesar de ser um follow-up contextual com aspecto explícito.

### Correção mínima

`_is_underspecified_broad_question()` agora recebe o histórico e não classifica
como pergunta inicial subespecificada um follow-up contextual que explicita um
aspecto acadêmico (`autoria`, `elementos`, `formatação`, `recuo`, `margem`,
`fonte` ou `citação`). A conversão para esclarecimento continua válida para
perguntas amplas iniciais sem suporte.

Não foi removido o guardrail e `partial` não foi transformado em aprovação:
afirmações sustentadas, IDs selecionados e a limitação permanecem publicados;
afirmações não sustentadas continuam sendo filtradas.

### GREEN

O teste reproduzido e o teste negativo passaram:

```text
2 passed, 84 deselected
```

O teste cobre pergunta original, assunto ativo, consulta contextualizada,
recuperação, síntese, grounding, IDs disponíveis/selecionados/publicados,
limitação parcial, histórico atualizado e ausência de esclarecimento repetitivo.
`test_genuinely_ambiguous_question_still_requests_clarification` confirma que
`Como formatar?` continua gerando esclarecimento sem chamar o RAG.

## B. Investigações P2

As consultas abaixo foram executadas com Ollama `gemma4:e2b`, temperatura efetiva
`0` e PostgreSQL em leitura. Os resultados são observações de execuções reais,
não métricas de qualidade geral.

### P2 — continuidade de citação direta longa

Consulta inicial:

```text
Como formatar uma citação direta longa?
```

Na repetição mais recente, o Synthesizer produziu uma paráfrase fiel sobre
recuo, letra menor, espaço simples, ausência de aspas e 4 cm. O grounding
publicou `document:1:page:16` com `supported`.

Trecho recuperado na página 16:

```text
7.1.1 A citação direta, com mais de três linhas, deve ser destacada com recuo
padronizado em relação à margem esquerda, com letra menor que a utilizada no
texto, em espaço simples e sem aspas. Recomenda-se o recuo de 4 cm.
```

Follow-up:

```text
E o recuo?
```

Consulta enviada ao RAG:

```text
E o recuo? Contexto da pergunta anterior: Como formatar uma citação direta longa?
```

Resultado observado: `document:1:page:17` foi selecionada, as páginas 17–19
foram recuperadas e nenhuma delas continha a regra de recuo da página 16. O
grounding retornou `unsupported`, publicou zero IDs e registrou
`grounding_rejected`. Portanto, a rejeição é coerente com as evidências do
turno; a causa isolada é recuperação/seleção de uma página posterior, não um
defeito comprovado no filtro de grounding.

Uma execução anterior também terminou `unsupported` no primeiro turno por falha
de parsing do verificador semântico, enquanto a repetição passou. Essa variação
reforça que a síntese LLM não pode ser tratada como determinística.

**Decisão:** não alterar recuperação, RRF ou grounding nesta tarefa. A limitação
permanece documentada para uma etapa específica de recuperação, caso seja
autorizada futuramente.

### P2 — autoria da NBR 6023

Consulta:

```text
Segundo a ABNT NBR 6023, como indicar autores nas referências?
```

O RAG recuperou `document:32:page:7`, `document:32:page:11` e
`document:32:page:40`. A página 40 continha o conteúdo de indicação de autoria,
mas o Synthesizer selecionou a página 11 e produziu:

```text
Autores devem ser indicados em lista de referências.
```

Essa frase não responde como indicar o autor e não é sustentada pela página 11.
O grounding rejeitou a resposta (`unsupported`, zero IDs publicados). O
comportamento fail-closed evitou publicar a afirmação irrelevante.

**Causa:** seleção probabilística de uma evidência incidental entre candidatos
`direct_match`; não foi demonstrada perda de conteúdo no armazenamento.

**Decisão:** não criar regra hardcoded para escolher a página 40 e não alterar
RRF. O caso permanece como falso negativo de seleção/síntese a ser calibrado
com protocolo de avaliação próprio.

### P2 — item 6.7 da NBR 6023

Consulta:

```text
Qual é o item 6.7 da ABNT NBR 6023?
```

O RAG retornou `document:32:page:9`, `document:32:page:50` e
`document:32:page:70`. A página 70 é um índice com caracteres corrompidos; o
Synthesizer escolheu essa página e respondeu sobre “indicação de informações
do conteúdo”, sem suporte ao item solicitado. O grounding rejeitou a resposta
e publicou zero IDs.

Em outra consulta ampla, a página 11 continha o texto completo do item 6.7,
mas ela não foi candidata para esta busca específica. A página correta existe no
corpus, porém não foi selecionada neste turno.

**Causa:** recuperação/seleção por página e evidência de índice corrompida; não
há fundamento para relaxar o grounding ou publicar a resposta produzida.

**Decisão:** não alterar Gold, OCR, embeddings, RRF ou o pipeline documental.
Registrar como limitação de recuperação e seleção.

## C. Integridade e validação

Arquivos funcionais alterados nesta correção:

- `src/app/agente_v2/orchestrator.py`
- `tests/test_agent_v2.py`

Documento acrescentado:

- `docs/agente_v2/correcao_final_pr14.md`

As alterações anteriores em `synthesis.py`, `grounding_adapter.py`,
`grounding.py`, `planner.py` e testes existentes foram preservadas. Artefatos
experimentais não rastreados do worktree foram preservados.

Validações executadas antes do commit:

- teste direcionado RED/GREEN do fluxo P1: `2 passed, 84 deselected`;
- suíte V2 (`uv run --locked pytest -q tests/test_agent_v2.py`): `86 passed`;
- suíte completa (`uv run --locked pytest -q`): `413 passed, 1 skipped, 9 xfailed`;
- `uv run --locked ruff check .`: `All checks passed!`;
- `git diff --check`: passou sem apontamentos;
- Ollama `gemma4:e2b`, temperatura efetiva `0` e PostgreSQL somente leitura:
  o fluxo real de três turnos preservou respostas `partial`, limitações e os
  IDs publicados (`document:32:page:12`, `document:32:page:11`); o caso de
  citação longa passou em uma repetição com `document:1:page:16`, enquanto os
  follow-ups de recuo, autoria e item 6.7 foram rejeitados sem publicar IDs,
  conforme descrito na seção P2;
- bootstrap do Streamlit em `127.0.0.1:8503`: HTTP `200`, título `Streamlit`.
  A inspeção Playwright/CUA não foi concluída por bloqueio do navegador já em
  uso no Windows.

Os gates globais do ub-mode continuam incompletos por ausência de `coverage`,
duplicações e bloqueio/timeout do Mutator no OneDrive. Não são classificados
como aprovados.

## D. Recomendação

O P1 reproduzido está corrigido sem liberar afirmações sem suporte; os P2
permanecem caracterizados e documentados, sem alterações especulativas na
infraestrutura. A PR deve ser submetida a uma última revisão independente após
o novo commit.
