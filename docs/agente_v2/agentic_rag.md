# Agente V2 — planejamento agentic RAG

## Escopo e baseline

Esta entrega parte da versão integrada da V2 (`962d6fd`) e altera somente o
planejamento, a síntese, a política de grounding e os testes correspondentes.
O corpus, a proveniência, PostgreSQL/pgvector, a recuperação híbrida e os
parâmetros de RRF permanecem nos componentes existentes.

Antes das mudanças, a suíte registrava 422 testes aprovados, 1 ignorado e 9
`xfail`; Ruff e `git diff --check` estavam aprovados.

## Arquitetura atual e proposta

O fluxo existente já separava planner, tool de busca, síntese estruturada e
grounding. Porém, todo turno sem recuperação recebia uma resposta fixa e o
contrato não distinguia explicação geral de resposta normativa.

O fluxo agora é:

```text
pergunta + histórico
        -> PlannerDecision (modo, objetivo, consultas limitadas)
        -> general: síntese paramétrica sem RAG
        -> normative/mixed: busca existente (até duas consultas planejadas)
        -> síntese estruturada
        -> grounding por afirmação
        -> publicação com proveniência do turno
```

Os modos são `general`, `normative`, `mixed`, `clarify` e `out_of_scope`.
`needs_retrieval` é normalizado de forma consistente: somente `normative` e
`mixed` recuperam documentos. O fallback heurístico continua apenas como
proteção quando a saída estruturada da LLM não está disponível ou é inválida.

## Decisões de implementação

- `PlannerDecision` ganhou modo explícito, objetivo, consultas documentais
  limitadas a duas e indicação de conhecimento paramétrico.
- A síntese geral pode explicar conceitos, passos e exemplos; exemplos devem
  ser marcados como `Exemplo ilustrativo:` e não podem inventar IDs ou fontes.
- Em modo misto, apenas afirmações normativas exigem suporte; prosa geral é
  preservada. Uma afirmação normativa sem suporte é removida e substituída por
  uma limitação parcial, sem publicar ID não verificado.
- O modo geral não chama a tool RAG. Respostas gerais com afirmação normativa
  ainda falham fechadas pela política central de grounding.
- Uma segunda consulta só é executada quando foi explicitamente planejada e a
  primeira não retornou evidência. Não houve alteração do ranking, do RRF ou
  da consulta interna existente.

## Testes e validação

Foram adicionados testes para normalização dos modos, resposta geral sem RAG,
resposta mista, recuperação limitada em duas tentativas e preservação de prosa
geral quando uma regra normativa não é sustentada.

Resultados locais após a implementação:

- `uv run --locked pytest -q`: 430 passed, 1 skipped, 9 xfailed.
- `uv run --locked ruff check .`: aprovado.
- `git diff --check`: pendente de confirmação no diff final da branch.

Os testes determinísticos validam contratos e decisões de publicação; eles não
comprovam fidelidade factual de uma LLM real. A avaliação com Ollama e
PostgreSQL depende dos serviços locais e deve ser registrada separadamente.

## Limitações conhecidas

- A classificação semântica dos modos ainda depende da LLM; as heurísticas são
  apenas guardas de segurança e fallback.
- Não foram alterados mecanismos de ingestão, OCR, embeddings, corpus, Gold,
  PostgreSQL, RRF ou interface V1.
- Os gates ub-mode Crapper/Dryer/Mutator permanecem sujeitos aos resultados
  incompletos já registrados (cobertura/duplicações e timeout de workers no
  OneDrive); não são declarados aprovados por esta entrega.
