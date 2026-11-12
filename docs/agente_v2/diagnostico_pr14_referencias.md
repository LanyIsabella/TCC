# PR #14 — Diagnóstico das consultas sobre referências

> Atualização da revisão: o diagnóstico abaixo preserva os registros da
> execução anterior. A configuração efetiva atual é `OLLAMA_TEMPERATURE=0`;
> resultados adicionais e a correção de continuidade implícita estão em
> [`auditoria_prompts_guardrails_pr14.md`](auditoria_prompts_guardrails_pr14.md).

Data da verificação: 2026-11-12
Branch: `fix/agente-v2-post-merge`
Modelo: `gemma4:e2b`
Banco: PostgreSQL local configurado pelo `.env`
Base documental: snapshot ativo, sem reingestão

## Causa reproduzida

Antes da correção, a pergunta curta respondida ao esclarecimento (`Elementos` ou
`Formatação`) era usada como pergunta de validação do grounding. A recuperação
usava a pergunta contextualizada, mas a validação via `ground_answer` recebia
apenas o termo curto e rejeitava trechos condicionais ou específicos da NBR
6023. Em seguida, uma extração posterior reavaliava a mensagem de fallback e
expunha o estado como `conversational`.

Também foi observado que o Ollama, em algumas respostas estruturadas, colocou
`evidence_id: ...` no texto da resposta e deixou `evidence_ids` vazio. O
grounding rejeitava corretamente a resposta por ausência de seleção formal,
mesmo quando o identificador textual era válido e a frase estava literalmente
no trecho recuperado.

## Alterações aplicadas

- `orchestrator.py`: passa a pergunta resolvida somente para a validação do
  grounding; a pergunta pública e o histórico continuam sendo os originais.
- `grounding_adapter.py`: extrai o resultado a partir da decisão selada, sem
  reavaliar o texto `INSUFFICIENT_EVIDENCE` com a pergunta curta.
- `grounding.py`: preserva condições anteriores e exceções explícitas seguintes,
  sem anexar automaticamente uma condição posterior de outra regra ao trecho
  literal citado.
- `synthesis.py`: quando a lista estruturada está vazia, recupera apenas tokens
  estritos no formato `evidence_id: <id>`. O ID continua sujeito à existência no
  payload e à validação textual do grounding; a extração não é prova factual.
- Ainda em `synthesis.py`, os marcadores inline reconhecidos são removidos do
  texto antes da validação e da publicação; eles permanecem apenas como
  metadados de seleção.
- Em `grounding.py`, restrições posteriores da mesma regra (`somente`, `apenas`,
  exceções e referências anafóricas à regra) continuam no contexto de validação.
  Sentenças condicionais posteriores que introduzem outra regra, como a
  orientação específica para notas de rodapé, não são anexadas ao primeiro
  enunciado literal.
- Testes determinísticos em `tests/test_agent_v2.py` e
  `tests/test_grounding_policy.py` cobrem esses contratos.

## Cenários contextualizados reais

Em cada cenário foi criada uma conversa independente. A primeira pergunta foi
`Como formatar referências?`; ela é ampla (`is_broad_question=True`) e terminou
em esclarecimento. Os payloads entregues ao sintetizador tinham
`status=success`, documentos compactados por página, os IDs listados abaixo e
nenhum texto integral além do orçamento da ferramenta.

| Resposta ao esclarecimento | Pergunta contextualizada | Consultas RAG | Documentos/páginas e evidências | Síntese e decisão |
|---|---|---|---|---|
| `Autoria` | `Segundo a ABNT NBR 6023, como indicar o nome do autor nas referências bibliográficas?` | A consulta contextualizada, sem expansão adaptativa | `abnt_nbr_6023`: páginas 11, 7 e 40; IDs `document:32:page:7`, `document:32:page:11`, `document:32:page:40` | Síntese selecionou 40 (e, em uma execução, também 11). A frase sobre o último sobrenome foi publicada; `supported`, `grounded_answer`, publicada `document:32:page:40`, sem erros. |
| `Elementos` | `Segundo a ABNT NBR 6023, quais são os elementos necessários para elaborar referências bibliográficas?` | Consulta contextualizada + expansão `referências elaboração autores elementos essenciais ABNT NBR 6023` | `abnt_nbr_6023`: páginas 12, 30, 14, 29 e 18; IDs disponíveis `document:32:page:12`, `document:32:page:14`, `document:32:page:18` | Síntese selecionou `document:32:page:12` e reproduziu a lista de elementos de livro/folheto. `supported`, `grounded_answer`, publicada `document:32:page:12`, sem erros. |
| `Formatação` | `Segundo a ABNT NBR 6023, quais são as regras de formatação das referências?` | Consulta contextualizada + expansão `referências elaboração autores elementos essenciais ABNT NBR 6023` | `abnt_nbr_6023`: páginas 11, 58, 68, 29, 14 e 18; IDs disponíveis `document:32:page:11`, `document:32:page:14`, `document:32:page:18` | Síntese reproduziu a regra de espaço simples e alinhamento e selecionou `document:32:page:11` (inclusive quando o modelo escreveu o ID dentro do texto). `supported`, `grounded_answer`, publicada `document:32:page:11`, sem erros após a correção do escopo literal. |

Na primeira consulta ampla, o RAG recuperou também NBR 10520 e NBR 6022.
Isso foi registrado como contexto de recuperação ampla, não como suporte
publicável. O agente converteu a resposta não fundamentada em pedido de
esclarecimento e publicou zero IDs.

## Consultas diretas e negativas

- Consulta direta de autoria: `supported`, página 40, ID publicado
  `document:32:page:40`.
- Consulta direta de elementos: `supported`, página 12, ID publicado
  `document:32:page:12`.
- Consulta direta de formatação: após a correção, `supported`, página 11, ID
  publicado `document:32:page:11`.
- Consulta direta de formatação repetida após o ajuste P2 com temperatura 0:
  o sintetizador selecionou `document:32:page:11`; o texto público não contém
  `evidence_id` e o resultado foi `supported`/`grounded_answer`.
- Continuidade após autoria: `E quanto aos elementos?` foi contextualizada com
  a pergunta anterior, recuperou NBR 6023 páginas 11, 24 e 26 e publicou uma
  síntese sustentada pela página 11.
- Ausência semântica de evidência: a pergunta sobre armazenar discos de vinil
  recuperou páginas da NBR 6023, mas a síntese reconheceu que a norma não trata
  do assunto; o grounding publicou zero IDs e retornou `unsupported`.
- Norma não pertinente: a pergunta sobre elementos de referências segundo a
  NBR 10520 recuperou somente NBR 10520. Uma síntese que citou NBR 6023 foi
  rejeitada; `unsupported`, zero IDs publicados e erro `grounding_rejected`.

Esses casos distinguem recuperação disponível de suporte factual. IDs válidos,
similaridade lexical ou uma resposta plausível não autorizam publicação.

## Validação da interface

Com uma instância Streamlit isolada na porta 8502 e `OLLAMA_TEMPERATURE=0`, o
Playwright validou conversas independentes `Como formatar referências?` →
`Elementos`, `...` → `Formatação` e `...` → `Autoria`. As três respostas foram
renderizadas com grounding e o expander de evidências documentais. Capturas:

- `target/playwright-v2/pr14-autoria-final.png`
- `target/playwright-v2/pr14-elements-final.png`
- `target/playwright-v2/pr14-formatacao-final.png`

## Testes determinísticos

- RED: o teste de esclarecimento curto falhava com `conversational` em vez de
  `supported`; o teste de escopo literal falhava por incorporar uma condição
  posterior não relacionada; o teste de IDs inline retornava lista vazia.
- GREEN: os três testes passaram após as menores correções correspondentes.
- Suíte completa após os ajustes P1/P2: **398 passed, 1 skipped, 9 xfailed**.
- Ruff: **aprovado** (`uv run --locked ruff check .`).
- Diferenças: **aprovado** (`git diff --check`).

## Limitações

- A temperatura configurada no `.env` é 0,7; saídas do modelo podem variar. A
  confirmação reprodutível da interface usou 0 apenas como configuração de
  validação, sem alterar o arquivo `.env`.
- A validação real não é prova científica de fidelidade geral do LLM; ela
  documenta os casos executados e a decisão determinística do grounding.
- Os gates globais ub-mode continuam com limitações históricas de cobertura,
  mutação e duplicação; não foram feitas refatorações fora desta correção.

## Verificação complementar da continuidade

Foi reproduzido o caso em que `Formatação` e `Autoria` eram enviados depois de
uma resposta anterior a `Elementos`. Sem contexto implícito, a consulta era
montada apenas com o termo curto e podia recuperar NBR 10520. O Orchestrator
agora recupera um pedido de esclarecimento ainda visível no histórico e
reutiliza o resolvedor existente da Planner. O teste determinístico correspondente
passou e uma execução real passou a enviar:

`Segundo a ABNT NBR 6023, quais são as regras de formatação das referências?`

O resultado real observado foi uma resposta parcial com limitação explícita e
publicação somente da evidência selecionada da NBR 6023. A variação do modelo e
da recuperação continua sendo uma limitação documentada.

Uma revisão independente posterior também cobriu a mudança de assunto entre um
esclarecimento e um novo tópico normativo, além da regra literal de espaçamento
entre referências presente na NBR 14724. Ambos os casos receberam regressões
determinísticas e passaram na suíte.
