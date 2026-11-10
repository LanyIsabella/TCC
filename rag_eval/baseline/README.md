# Baseline experimental ABNT

Este pacote prepara comparações da aplicação real com versões futuras. Não corrige
produção, não executa ingestão e não usa o demonstrador `rag_eval/rag.py`.

A captura inicial está em `artifacts/initial_state.json`. O banco foi consultado em
transação `REPEATABLE READ READ ONLY`, com verificação explícita do modo e timeout.
Os textos existentes foram copiados para evidência local, sem OCR ou geração.
Os vetores não foram exportados. A reprodução depende dos PDFs, dos checkpoints
locais e do estado indexado correspondente; isto não é um backup integral do banco.

## Estado e terminologia

- Página física: posição no PDF, começando em 1.
- Página impressa: rótulo visível no original; a captura oferece somente um
  candidato automático, que precisa de conferência humana.
- Extração: registro persistido com texto, extrator, versão e avaliação. Os IDs
  atuais não constituem um histórico imutável de execução.
- Referência de consulta: localizador verificável por hash, página e fragmento
  nativo. Sua existência não comprova relevância, completude ou correção da resposta.
- Revisão humana: transcrição/conferência produzida por pessoa identificada.
  Nenhuma transcrição humana foi preenchida nesta fase.

As configurações observadas agora ficam separadas das configurações históricas,
que não foram integralmente persistidas. Valores desconhecidos continuam `null`.
O arquivo `.env`, credenciais e vetores não são incluídos no snapshot.

## Arquivos e comandos

Execute os comandos na raiz, com o ambiente já instalado; nenhuma instalação nova
é necessária. Em PowerShell, evite bytecode e a integração externa de GEDWeb:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:RUN_GEDWEB_PLAYWRIGHT='0'
.\.venv\Scripts\python.exe -B -m pytest -q -rxs -p no:cacheprovider
```

Os contratos de defeitos conhecidos usam `xfail(strict=True)`: uma correção futura
que os faça passar produzirá XPASS estrito, exigindo retirar a marca. Para observar
as falhas reais agora, sem corrigir a implementação:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/baseline/test_defect_agent.py tests/baseline/test_defect_pipeline.py --runxfail -q -p no:cacheprovider
```

O retorno não zero dessa execução é esperado. Não o confundir com regressão
introduzida na infraestrutura. As caracterizações atuais passam; os contratos
corrigidos falham por comportamento. SQLite em memória é usado em F2 como adapter
DB-API; não comprova semântica de PostgreSQL, concorrência ou migrações. F1 exercita
o gate, não uma promoção Gold completa.

Uma nova observação deve usar outro diretório. `snapshot.capture` recusa substituir
o `initial_state.json` já preservado:

```powershell
.\.venv\Scripts\python.exe -B -m rag_eval.baseline.snapshot --output-dir rag_eval/baseline/artifacts/observations/new_capture
.\.venv\Scripts\python.exe -B -m rag_eval.baseline.audit --snapshot rag_eval/baseline/artifacts/initial_state.json --queries rag_eval/baseline/queries.json --output rag_eval/baseline/artifacts/integrity_report.json
```

## Protocolo documental

O inventário contém as 177 páginas e suas 531 extrações. As listas completas de
páginas ativas com revisão pendente e conclusão não confirmada estão no relatório
de integridade. Conferir cada indicador com o original: não classificar a flag
isoladamente como perda de texto. Páginas sem conteúdo normativo podem ser vazias.

`artifacts/human_reference.json` seleciona 40 páginas: três por norma por cobertura
física de início/meio/fim e dez adicionais por indicadores de risco/estrutura.
É uma seleção preliminar determinística, não uma amostra aleatória nem uma coleção
de casos já rotulados por humanos. Candidatos de tabela podem ser sumários.

Para cada página selecionada, dois revisores devem conferir o PDF original e:

1. Confirmar identidade, hash, página física e número impresso.
2. Transcrever o conteúdo de referência sem usar outro LLM como suposto humano.
3. Anotar ordem de leitura, parágrafos, seções, listas, tabelas, fórmulas quando
   presentes, números, unidades, negações, condições e referências cruzadas.
4. Classificar omissão, inserção, duplicação, ruído e efeito semântico, distinguindo
   conteúdo normativo de cabeçalhos, carimbos e marcas d'água.
5. Registrar divergências entre revisores e a adjudicação, preservando versões.
6. Preencher `transcription`, `transcription_origin="human"`, `reviewer`,
   `reviewed_at` e `review_status="reviewed"` apenas após a conferência.

Usar pseudônimos estáveis para revisores. `review.py` verifica a declaração de
origem/autoria e o hash; ele não consegue provar quem digitou uma transcrição.
CER/WER são calculados pela implementação existente, contra a transcrição
declarada, sem normalização silenciosa. Não são calculados contra uma referência
pendente. Comparações normalizadas, se adotadas depois, devem ser métricas
adicionais com regras versionadas. Uma nota agregada não pode ocultar erro crítico
em valor, condição, exceção ou referência normativa.

Há mecanismos para revisar qualquer página e avaliar todas as extrações existentes:

```powershell
.\.venv\Scripts\python.exe -B -m rag_eval.baseline.review --snapshot rag_eval/baseline/artifacts/initial_state.json --output rag_eval/baseline/artifacts/all_pages_review.json
.\.venv\Scripts\python.exe -B -m rag_eval.baseline.review --snapshot rag_eval/baseline/artifacts/initial_state.json --reviews rag_eval/baseline/artifacts/human_reference.json --output rag_eval/baseline/artifacts/extraction_evaluation.json
```

O primeiro comando cria um formulário vazio de 177 páginas. O segundo produz uma
linha por extração e conserva CER/WER `null` onde falta revisão. Não há reextração,
reavaliação LLM ou alteração da Gold. Para uma rodada real, escrever novos arquivos
de revisão/resultados, preservando os modelos pendentes desta baseline.

## Consultas e avaliação da aplicação real

`queries.json` contém 120 propostas: 60 específicas (seis por norma), 20 amplas,
20 turnos de dez diálogos, dez negativas e dez ambíguas. São 40 casos de
desenvolvimento e 80 reservados. Grupos, diálogos e templates literais não cruzam
splits. Similaridade semântica e adequação das expectativas ainda exigem revisão.

Cada referência possui documento, edição observada no PDF, SHA-256, página física,
fragmento literal e método de localização. Os testes verificam sua presença no
original. Na NBR 6023, fragmentos nativos podem conter caracteres Unicode privados;
isso foi preservado, sem criar uma transcrição corrigida artificialmente.

Os históricos dos diálogos são controlados e contêm perguntas anteriores, sem
respostas normativas fabricadas. Avaliam contextualização com histórico fixo;
não substituem diálogos encadeados com respostas reais, que serão uma rodada
adicional. As expectativas são propostas, não gold humano. Antes de pontuar
correção/completude, os revisores devem anotar afirmações esperadas, exceções,
suporte documental e comportamento adequado para ambiguidades.

```powershell
.\.venv\Scripts\python.exe -B -m rag_eval.baseline.run --stage retrieval --output rag_eval/baseline/artifacts/runs/retrieval_development.json
.\.venv\Scripts\python.exe -B -m rag_eval.baseline.run --stage agent --output rag_eval/baseline/artifacts/runs/agent_development.json
```

O estágio retrieval chama a tool real e observa `search_documents` antes da
compactação. O estágio agent chama `build_agent().invoke` e o adaptador real
`extract_agent_result`, correspondente ao contrato compartilhado com a UI.
Chamadas ao PostgreSQL passam pela conexão somente leitura. Não há ranking
alternativo, alteração de pesos, de prompt, de temperatura ou de embeddings.

Cada caso executa em processo separado com timeout externo de 180 segundos. Isso
limita a avaliação, sem alterar parâmetros do modelo. Pré-verificação indisponível
produz `blocked`, métricas `null` e código de saída 2; não são fabricadas respostas.
Timeout/erro também não contam como resposta. O supervisor registra hash do dataset,
hash da captura inicial e hashes atuais dos componentes para comparar versões.

Ollama precisa estar acessível com `gemma4:e2b` e `nomic-embed-text` disponíveis,
conforme configuração preservada. O banco precisa disponibilizar o estado indexado
correspondente em leitura. Registrar os digests reais antes da rodada: tags são
mutáveis e o serviço indisponível impediu observá-los agora. Alterar os endpoints
na máquina ou usar outro estado exige registrar uma nova condição experimental.

Os 80 reservados só podem ser selecionados com `--split reserved --allow-reserved`.
Não usá-los para ajustes. Não foram enviados ao modelo nesta execução.

As métricas automáticas atuais são cobertura de localizadores de documento/página
e retenção literal quando o fragmento já existia no texto recuperado antes do corte.
Fragmento ausente antes do corte não é classificado automaticamente como perda da
compactação. Não há pontuação fabricada de correção factual ou suporte por afirmação.

Depois da anotação, medir Recall@k, MRR/nDCG, cobertura de subperguntas, suporte por
afirmação, números/edições, abstenção correta, falsa recusa e continuidade temática.
Registrar latência/tokens e comparar condições pareadas, com incerteza por estrato.
Repetições do LLM devem manter o mesmo corpus e parâmetros; usar inicialmente três
por condição, preservando seed quando suportada. Juiz LLM deve ser calibrado contra
revisão humana. Não há execução Ragas/juiz integrada nesta etapa.

## Limites e próximo gate

Faltam revisões humanas, execução com Ollama, integração PostgreSQL isolada das
correções e avaliação por afirmação. A captura é evidência estrutural e operacional,
não validação de fidelidade. Consulte `docs/baseline_fase2.md` para resultados,
matriz F1–F13, critérios de início e sequência de correções.
