# PR #14 — Auditoria de prompts, guardrails e continuidade

Data da consolidação: 2026-11-12
Branch: `fix/agente-v2-post-merge`
Commit de referência da PR: `9923e8b806307dcfbc6b388578767ec43f056640`

Este relatório documenta apenas o Agente V2. Não houve reingestão, OCR,
embeddings, alteração de RRF, alteração da Gold ou modificação do agente V1.

## Configuração efetiva

| Item | Valor verificado |
|---|---|
| Modelo | `gemma4:e2b` |
| ID local Ollama | `7fbdbf8f5e45` |
| Blob base do Modelfile | `sha256-4e30e2665218745ef463f722c0bf86be0cab6ee676320f1cfadf91e989107448` |
| Temperatura no `.env` | `0` |
| Temperatura no `.env.example` | `0` |
| Host | `http://localhost:11434` |
| Parâmetros do Modelfile | `temperature 1`, `top_k 64`, `top_p 0.95` |
| Parâmetros enviados por `Client` | `temperature=0.0`, sem `seed`, `top_k` ou `top_p` explícitos |

`src/app/client.py` carrega o `.env` e passa a temperatura para o único
`ChatOllama` compartilhado pelo Planner e pelo Synthesizer V2. O teste
`tests/test_client_configuration.py` confirma que o valor zero chega ao
cliente. O campo `seed` existe em `ChatOllama`, mas não foi aplicado: a
reprodutibilidade adicional não foi demonstrada e temperatura zero não implica
determinismo absoluto.

## Auditoria dos prompts

### Planner

`src/app/agente_v2/planner.py` recebe a mensagem atual e um histórico limitado.
O prompt distingue `conversational`, `ambiguous`, `normative_query`,
`action_request`, `out_of_scope` e `unknown`. Perguntas normativas amplas são
orientadas a um único esclarecimento específico; decisões com recuperação são
normalizadas para a rota normativa. O fallback determinístico continua sendo a
proteção quando a saída estruturada falha.

### Resolução de esclarecimentos

O prompt de resolução exige uma pergunta autossuficiente, preserva o assunto
original e incorpora somente o aspecto respondido. Os mapeamentos determinísticos
existentes para `Autoria`, `Elementos`, `Formatação` e `Citação direta longa`
foram reutilizados. Um esclarecimento ainda visível no histórico pode ser
recuperado quando o estado pendente já foi consumido, sem transformar saudações
ou mudança explícita de assunto em contexto normativo.

### Synthesizer

O prompt antigo favorecia copiar literalmente uma frase completa para cada
afirmação. Isso reproduziu fragmentos corretos, porém irrelevantes, e aumentou
rejeições de paráfrases. A instrução foi substituída por uma síntese natural
baseada somente nos trechos fornecidos, preservando números, unidades,
obrigações, permissões, negações, condições e exceções. A seleção de evidências
é compactada para até quatro trechos, priorizando `direct_match`, e o título,
similaridade lexical e marcador `direct_match` são explicitamente declarados
insuficientes como prova.

Saídas estruturadas continuam obrigatórias. IDs inline válidos são apenas
normalizados para metadados antes da validação; não constituem prova factual.

### Fallback e parsing

Falhas de parsing têm uma segunda tentativa limitada. Contratos inválidos
resultam em falha de síntese, não em resposta normativa inventada. O caminho de
recuperação sem evidência continua fail-closed.

## Matriz de guardrails

| Regra | Entrada | Aceita | Rejeita | Risco residual | Efeito público |
|---|---|---|---|---|---|
| Planner seguro | pergunta + histórico | intenção estruturada compatível | contrato inválido, intenção conflitante ou rota não normativa para recuperação | LLM pode classificar uma pergunta ampla de modo incompleto | conversa, esclarecimento ou recuperação |
| Escopo | mensagem atual e histórico | conversa acadêmica dentro do escopo | ação sem tool, assunto fora do escopo ou mensagem privilegiada | heurísticas podem produzir falso negativo em linguagem nova | resposta segura sem RAG |
| Recuperação | pergunta contextualizada | tool bem-sucedida com proveniência de turno | erro, timeout ou ausência de evidência | cobertura depende do índice existente | limitação explícita |
| Seleção | IDs e trechos recuperados | ID existente no payload do turno | ID ausente, evidência não selecionada ou tópico incompatível | consulta ampla pode recuperar páginas extras | somente IDs selecionados são publicados |
| Grounding determinístico | afirmações, pergunta e texto | correspondência literal/compatível com números, polaridade e qualificadores | contradição, condição ausente, norma não pertinente ou evidência insuficiente | paráfrases legítimas podem exigir verificador | `supported`, `partial` ou `unsupported` |
| Verificador semântico | somente claims e trechos do turno | paráfrase sustentada com citação literal suficiente | JSON inválido, ID inexistente, tópico incompatível ou dúvida | depende de outra chamada ao mesmo LLM | só é usado após falha determinística |
| Publicação | resultado selado | grounding e proveniência coerentes | falha de síntese/grounding ou mensagem normativa sem suporte | qualidade linguística não é provada por status | resposta, limitação e evidências |

O verificador semântico não substitui as verificações determinísticas: a função
`_verified_support` primeiro exige pertinência temática, ID recuperado e contexto
literal compatível. A afirmação da LLM não é aceita como prova por si só.

## Experimentos controlados

Os experimentos foram qualitativos e executados com o mesmo corpus e banco
locais. Não constituem métrica científica de fidelidade geral.

| Experimento | Configuração | Observação reproduzida |
|---|---|---|
| A — baseline | prompt antigo, temperatura `0,7` | perguntas diretas e complementares tiveram rejeições ou respostas conversacionais apesar de haver evidência disponível |
| B — temperatura | prompt antigo, temperatura `0` | a rejeição do caminho literal permaneceu; temperatura zero sozinha não resolveu pertinência |
| C — prompt | prompt revisado, temperatura `0`, grounding literal | a síntese tornou-se mais natural, mas uma paráfrase correta ainda foi rejeitada pelo caminho literal |
| D — grounding | prompt revisado + verificador semântico restrito + filtro de tópico | uma citação direta longa foi publicada com página `document:1:page:16`; consulta ampla de referências virou esclarecimento; `Elementos` e `Formatação` recuperaram NBR 6023 em execuções reais |

No experimento D, uma execução também produziu uma resposta parcial para
`Formatação`, com a limitação documental publicada. Isso é preferível a
completar regras que não estavam nos trechos disponíveis.

## Cenários reais Ollama/PostgreSQL

### Citação direta longa

Pergunta: `Como formatar uma citação direta longa?`
Temperatura: `0`
Resultado observado em execução direta: resposta natural sobre recuo e regras
de citação, `grounding_status=supported` ou `partial` conforme os trechos
recuperados, com publicação de `document:1:page:16` e sem ID inventado.

Uma execução pela interface Streamlit em `8502` carregou o entry point e exibiu
a resposta de limitação sem evidência publicada. Essa variação foi preservada
como limitação da integração real; não foi convertida artificialmente em
sucesso.

### Conversa sobre referências

1. `Como formatar referências?` → esclarecimento sobre autoria, elementos ou
   formatação, sem IDs publicados.
2. `Elementos` → consulta resolvida para a NBR 6023, com páginas 12/18 e
   resposta apoiada em elementos essenciais.
3. `Formatação` → após a correção de continuidade implícita, consulta resolvida
   para as regras de formatação da NBR 6023; a execução observada publicou uma
   resposta parcial com a limitação correspondente.

O histórico conversacional permanece separado das evidências. Uma pergunta
autossuficiente sobre citação direta cancela o contexto pendente de referências.

### Cenários negativos

- Norma não pertinente: uma resposta que usava NBR 6023 para uma consulta sobre
  NBR 10520 foi rejeitada, mesmo com ID válido.
- Evidência irrelevante: páginas recuperadas para uma pergunta fora do assunto
  não foram publicadas como suporte.
- Contradições numéricas, de polaridade, condições ou exceções permanecem sob
  as verificações determinísticas.
- IDs inline ou similaridade lexical não autorizam publicação sem registro real
  no turno.

## TDD e regressões

Foram adicionados ou ajustados testes para:

- prompt de síntese natural e seleção compacta de trechos;
- pedido de esclarecimento específico para perguntas amplas;
- verificador semântico usado somente depois da falha determinística;
- filtro de tópico impedindo que o verificador aprove norma irrelevante;
- configuração `OLLAMA_TEMPERATURE=0` chegando ao `ChatOllama`;
- continuidade de `Formatação` após uma resposta anterior a `Elementos`.
- rejeição de contexto implícito depois de uma pergunta autossuficiente sobre
  outro assunto;
- pertinência de uma regra literal sobre espaçamento de referências localizada
  na NBR 14724.

O teste de continuidade reproduzia a falha com consulta curta sem contexto e
passou após a recuperação genérica do pedido de esclarecimento visível no
histórico. A alteração não adiciona um novo classificador nem muda a recuperação
híbrida.

Após a revisão independente do commit `9fd6560`, foram corrigidas duas lacunas
adicionais. A recuperação retroativa de esclarecimento agora é invalidada por
uma pergunta normativa autossuficiente posterior, e o filtro de referências
aceita conteúdo de outras normas somente quando o próprio trecho contém uma
regra explícita sobre referências (por exemplo, separação por espaço simples).
Uma simples menção a NBR 6023 continua insuficiente.

Na revisão seguinte, a compactação de evidências também foi ajustada para
preservar páginas adjacentes do mesmo documento quando uma página direta é
selecionada. O limite de quatro trechos continua valendo; a mudança apenas
preenche posições restantes com continuidades adjacentes, sem alterar a busca.

O recorte de cada trecho também passou a usar `matched_text` quando disponível.
Assim, uma regra localizada depois do primeiro milhar de caracteres da página
continua chegando ao Synthesizer, sem aumentar o orçamento global nem alterar a
recuperação.

## Limitações e pendências

- A interface Streamlit foi inicializada e exercitada com Playwright, mas uma
  execução real terminou sem evidência publicada; a causa pode ser variação do
  modelo ou da recuperação e não foi mascarada.
- A qualidade semântica do LLM não é demonstrada por testes determinísticos ou
  por `grounding_status` isolado.
- O verificador semântico depende do mesmo modelo e pode falhar com JSON inválido;
  nesse caso o caminho permanece rejeitado.
- O gate global ub-mode permanece incompleto: o Crapper não importou `coverage`,
  o Dryer reportou duplicações preexistentes e o Mutator expirou o orçamento
  compartilhado. Esses resultados não foram classificados como aprovação.
- Não foram usados os 80 casos de holdout e não foram alterados OCR, embeddings,
  RRF, Gold, banco produtivo ou o agente V1.
