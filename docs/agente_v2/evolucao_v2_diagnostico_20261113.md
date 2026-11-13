# Evolução da V2 — diagnóstico e reproduções

Data: 2026-11-13
Ambiente: checkout local da V2 com Ollama `gemma4:e2b` e PostgreSQL local; nenhum dado foi alterado.

## Escopo

Esta nota registra as reproduções funcionais que precedem as correções da evolução da V2. A validação usa o agente real e a recuperação existente; não constitui avaliação qualitativa nem utiliza os 80 casos reservados.

## Reproduções observadas

| Cenário | Entrada(s) | Observação | Classificação |
|---|---|---|---|
| Saudação | `Olá, preciso de ajuda` | Resposta natural, sem tool e sem evidências. | PASS |
| Citações, abertura | `Como fazer citações?` | O agente pediu esclarecimento, mas executou recuperação antes de publicar a pergunta. | FAIL: recuperação desnecessária |
| Citações, resposta ampla | `Todas elas` após a pergunta anterior | O contexto não foi convertido em consulta ampla confiável; terminou em insuficiência genérica. | FAIL: contexto/clarificação |
| Formatação, pergunta curta | `Como formatar?` | Terminou em insuficiência genérica, sem explicação útil nem esclarecimento específico. | FAIL: roteamento |
| Formatação, aspecto | `Referências` após `Como formatar?` | Recuperação terminou em insuficiência genérica; o aspecto respondido não foi preservado. | FAIL: contexto/clarificação |
| Normativa específica | `Como formatar uma citação direta longa segundo a ABNT?` | Publicou recuo de 4 cm com grounding parcial e limitação explícita. | PASS: parcial fundamentado |
| Mista | `O que é uma citação direta e qual recuo a norma recomenda?` | Publicou apenas o recuo; a explicação conceitual foi perdida. | FAIL: síntese mista |
| Normativa sem suporte | `Qual é a cor oficial da capa segundo a ABNT NBR 10520?` | Não publicou evidência nem afirmação normativa; informou insuficiência. | PASS: falha fechada |
| Contradição numérica | `A citação direta longa deve ter recuo de 2 cm?` | Corrigiu para 4 cm com suporte parcial; a resposta não preservou explicitamente a divergência da premissa. | OBSERVAR: contrato de contradição |
| Mudança de tópico | `Como montar referências?`; depois `Na verdade, como formatar uma citação direta longa?` | A segunda resposta reutilizou NBR 6023 e o tópico de referências, apesar da mudança explícita. | FAIL: contaminação de contexto |

## Próximo passo

Os testes determinísticos serão adicionados primeiro para os casos de roteamento, clarificação, contexto e síntese mista. As correções devem manter a recuperação, grounding, embeddings, Gold e RRF inalterados e continuar falhando de modo seguro quando uma afirmação normativa não tiver suporte.

## Verificação após as correções

- `Olá, preciso de ajuda`: resposta de saudação, sem tool, `grounding_status=conversational`.
- `Como formatar?`: esclarecimento estruturado, sem tool.
- `Como fazer citações?` → `Todas elas`: a primeira mensagem pede o aspecto; a segunda usa a consulta autossuficiente com citações diretas, indiretas e fontes, vinculada ao mesmo turno.
- `Como montar referências?` → `Na verdade, como formatar uma citação direta longa?`: a consulta publicada foi `como formatar citação direta longa abnt`; o histórico de referências não foi reutilizado.
- Pergunta mista de citação direta: o modo foi `mixed`; a explicação conceitual foi preservada. A regra normativa permaneceu limitada quando os trechos recuperados não demonstraram todas as afirmações.
- A frase `Posso ajudar. As citações diretas longas exigem recuo.` continuou rejeitada quando inserida em respostas conversacionais, ambíguas ou de ação.

Esses resultados são verificações funcionais direcionadas, não uma prova de fidelidade factual geral do LLM.
