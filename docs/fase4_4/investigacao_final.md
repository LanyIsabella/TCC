# Fase 4.4 — Investigação final

## HTTP 400 do GLM-OCR

### Evidência observada

- Endpoint: `http://localhost:11434/api/generate`.
- Modelo observado em `/api/tags` e `/api/show`: `glm-ocr:latest`.
- O cliente envia JSON com `model`, `prompt="Text Recognition:"`, uma imagem
  PNG em Base64 no campo `images`, `stream=false`, `keep_alive` e opções de
  temperatura, `num_predict` e `num_ctx`.
- A imagem de teste do snapshot é PNG e tinha 325891 bytes; não foi alterada.
- A requisição reproduzida com `num_ctx=2048` retornou HTTP 400 com a mensagem:
  `request (2592 tokens) exceeds the available context size (2048 tokens), try increasing it`.
- A mesma forma de requisição com `num_ctx=16384` retornou HTTP 200. O modelo,
  porém, respondeu `done=false` sem `done_reason`; o cliente marcou
  `completion_unconfirmed` e a política não considera o texto uma extração
  elegível. Isso é diferente de uma saída GLM-OCR confirmada.

### Causa e decisão

A causa do 400 foi configuração externa incompatível: o contexto efetivo de
2048 tokens era menor que o prompt visual de 2592 tokens. A configuração
versionada usa contexto padrão de 16384; o piloto que produziu o 400 executou
com contexto reduzido. Não há evidência de endpoint, modelo, JSON ou Base64
incompatíveis.

O comportamento exigido para execução é:

```powershell
$env:RAG_GLM_OCR_MODE = "direct_ollama"
$env:GLMOCR_DIRECT_CONTEXT = "16384"
$env:GLMOCR_DIRECT_MAX_TOKENS = "16384"
$env:GLMOCR_DIRECT_RETRY_MAX_TOKENS = "32768"
```

Os valores são configuração operacional, não um limiar de qualidade. Aumentar o
contexto não transforma uma resposta `done=false` em verdade factual.

### Fallback e identidade

Quando o GLM falha, `extract_page` mantém o candidato com identidade
`extractor="glm_ocr"` e registra `structured_output.fallback` como
`docling` ou `pdf_reader`. A política determinística agora classifica esse
registro como `technical_fallback`, portanto ele não pode ser selecionado como
GLM-OCR bem-sucedido. O texto de fallback não é rebatizado nem contabilizado
como saída independente do GLM.

## Falha intermitente da regressão

O teste que falhou na primeira execução foi
`tests/test_extraction_provenance.py::test_independent_processes_publish_one_valid_snapshot`,
com `PermissionError` transitório ao publicar/acessar o arquivo temporário no
workspace sincronizado do OneDrive. O teste usa diretório `tmp_path`, quatro
processos independentes, nomes temporários únicos e publicação por rename; não
há banco compartilhado nem arquivo temporário global.

O erro foi reproduzido uma vez na regressão completa e não ocorreu em cinco
execuções isoladas subsequentes. A causa funcional identificada era o processo
que publicava seu próprio arquivo e imediatamente reabria o destino para
validá-lo; no Windows, essa reabertura podia colidir com a publicação concorrente
e produzir `PermissionError`. A correção mínima registra quando o `rename`
atômico foi bem-sucedido e, nesse processo, retorna o digest já calculado sem
reabrir o destino. Processos que perderam a corrida continuam validando o
arquivo existente. Não foram adicionados retries, `sleep` ou assertivas mais
fracas.

## Auditoria das seleções

Os testes confirmam que:

- a decisão carrega `page_extraction_id` e `execution_id` por candidato;
- a seleção é feita por página e pode combinar Docling e GLM-OCR no mesmo
  documento;
- cada execução de seleção gera novas linhas append-only;
- `retry_required` e `quarantined` bloqueiam a aplicação na Gold;
- uma quarentena não desativa nem substitui a Gold ativa;
- concordância entre candidatos, sem referência independente, é quarentena e
  não prova de qualidade;
- o fallback preserva a identidade do extrator real, mas é inelegível.

No piloto, as quatro decisões foram: NBR 10520 p.8 — Docling selecionado;
NBR 6023 p.5 — quarentena por `no_eligible_candidate` (corrupção Unicode);
NBR 6028 p.4 — Docling selecionado; NBR 14724 p.14 — quarentena por
`insufficient_reference` (divergência estrutural/tabela sem referência
independente). O GLM não produziu saída independente elegível nesse conjunto.

## Validação final

### Validação operacional isolada do GLM-OCR

Foi executada uma cópia temporária de NBR 6028, página física 4, sem iniciar
ingestão nem escrever no banco. O modelo `glm-ocr:latest` estava disponível em
`/api/tags`. A chamada usou `/api/generate`, `stream=false`, prompt
`Text Recognition:`, imagem PNG Base64 de 395563 bytes, temperatura 0,
`num_ctx=16384`, `num_predict=16384` e `keep_alive=5m`.

O Ollama respondeu HTTP 200 em aproximadamente 6,7 s, com `model` igual a
`glm-ocr:latest`, `done=false`, `done_reason=null` e 1900 caracteres retornados.
Isso é uma requisição aceita com geração incompleta, não uma extração concluída.
O conteúdo começou com o cabeçalho `ABNT NBR 6028:2021` e texto de prefácio;
essa observação descreve a saída, mas não valida sua completude ou fidelidade.
Na execução pelo adaptador, o extrator permaneceu `glm_ocr`, não houve fallback e
`assess_candidate` retornou `eligible=false` com `truncated_output`. O texto
retornado foi preservado apenas para diagnóstico; não foi promovido nem usado
como evidência independente elegível.

### Identidade do ambiente e diagnóstico de término

O ambiente local foi registrado sem alterar a instalação: Ollama `0.30.11`,
modelo `glm-ocr:latest`, digest
`6effedd0dc8aec66ad86c94b8099395376e212f22c87a9d7147c422f7e447be4`, tamanho
`2219299168` bytes. O `Modelfile` observado usa `TEMPLATE {{ .Prompt }}`,
`RENDERER glm-ocr`, `PARSER glm-ocr` e `temperature 0`. O metadado GGUF expõe
`tokenizer.ggml.eos_token_id=59246` e a lista `[59246, 59253]`; contudo, o log
do servidor registra somente `59246 ('<|endoftext|>')` como EOG. Isso é uma
hipótese operacional consistente com o término não confirmado, não uma prova
de que todo build do Ollama apresente o mesmo defeito.

Foi executada uma matriz pequena na mesma cópia temporária da página, sem tocar
no PDF original:

| Variante | Resultado bruto | Interpretação |
| --- | --- | --- |
| Atual, `stream=false`, contexto 16384, `num_predict=16384` | HTTP 200, 1900 caracteres, `done=false`, sem `done_reason` | geração incompleta |
| Mínima, `stream=false`, somente contexto 16384 | HTTP 200, 1900 caracteres, `done=false`, sem `done_reason` | não depende de `keep_alive`, temperatura ou `num_predict` explícitos |
| `stream=true` com a configuração atual | 604 eventos, 1900 caracteres, nenhum evento final `done=true` | o cliente não perdeu um evento final |
| `stop=["<|user|>"]`, contexto 16384 | HTTP 200, 1900 caracteres, `done=false`, sem `done_reason` | workaround não demonstrado |

Os logs locais também registram execuções que chegaram a milhares de tokens
sem EOG e uma execução cancelada após cinco minutos. A comparação pública mais
próxima é o [issue #18609 do Ollama](https://github.com/ollama/ollama/issues/18609),
que descreve GLM-OCR sem EOG para o token de usuário e mudanças de runner em
versões `0.34.1+`; a versão local é `0.30.11`, portanto a referência é
diagnóstica, não uma confirmação de igualdade de versão. A documentação oficial
do [modelo GLM-OCR no Ollama](https://ollama.com/library/glm-ocr) e do
[adaptador `/api/generate`](https://github.com/zai-org/GLM-OCR/blob/main/README.md)
é compatível com o formato usado; não há evidência de erro de endpoint ou de
interpretação do JSON.

Não foi feito upgrade/downgrade nem substituição do modelo original. Antes do
teste alternativo, não havia correção segura no cliente: aceitar `done=false`
ou truncar a saída violaria a proveniência. A decisão permanece preservar
`glm_ocr`, registrar `truncated_output`/`completion_unconfirmed` e impedir
promoção ou uso como evidência independente; o teste do artefato corrigido está
registrado na seção conclusiva abaixo.

- Testes direcionados do ajuste: aprovados.
- Integração PostgreSQL isolada, incluindo preservação da Gold ativa:
  aprovada.
- Regressão com `uv`: 397 aprovados, 1 ignorado, 2 xfail conhecidos.
- Ruff: aprovado.
- `git diff --check`: aprovado.
- Crapper, Dryer e Mutator: não reexecutados; as limitações já documentadas
  permanecem válidas.

O relatório automático mais recente do ub-mode (`.../ub-mode/6d55bcec9bbdadbe6d16/report.json`)
não constitui aprovação: Crapper terminou com código 2 por timeout/ausência de
cobertura, Dryer encontrou duplicações existentes e Mutator terminou com código
2, deixando pontos não cobertos. Esses gates não foram repetidos nesta
investigação, pois não houve alteração funcional adicional.

## Conclusão

O HTTP 400 é uma limitação de configuração operacional, não um bloqueio
funcional do pipeline. A rejeição de fallback como GLM-OCR foi corrigida e
testada. A resposta `done=false` observada com contexto suficiente permanece
uma limitação externa do modelo/serviço e corretamente leva a revisão/quarentena.
O piloto de quatro páginas continua insuficiente para concluir superioridade ou
fidelidade factual; a política conservadora de promoção permanece necessária.

### Parecer de encerramento da investigação

- **Resolvido no código:** contexto 2048 rejeitado com diagnóstico preservado;
  fallback não é reclassificado como GLM-OCR; respostas sem término confirmado
  não são elegíveis.
- **Causa externa reproduzível:** o modelo/runner local aceita a requisição,
  mas não sinaliza conclusão e não registra todos os tokens EOG declarados.
- **Indeterminado naquele estágio:** a troca de artefato ainda não havia sido
  testada; essa lacuna foi resolvida pelo teste controlado documentado abaixo.
- **Próximo passo delimitado:** avaliar uma amostra maior do artefato corrigido
  com critérios independentes, sem iniciar ingestão, backfill ou avaliação
  produtiva.

## Teste conclusivo com metadados corrigidos

### Procedência e preservação

O artefato alternativo está publicado como `frob/glm-ocr` no registro do
Ollama, descrito pelo mantenedor como “Fix missing metadata”. A página pública
lista as variantes `latest`, `q8_0` e `bf16` e documenta a adição de
`tokenizer.ggml.eot_token_id=59253`
([página do artefato](https://ollama.com/frob/glm-ocr)). Foi baixada somente a
tag `frob/glm-ocr:bf16`; o modelo original permaneceu instalado e inalterado.

Metadados observados localmente após o download:

- digest Ollama: `899cbcb09e30e0b9a5b555f15d3e4d89e0506f61c9b971f5ada141e718d9cb5d`;
- blob GGUF: `sha256-b2891fe9ce386254e6ad799ff3a03d2b262f22f21973549ca1e71b71260817be`;
- tamanho: `2219298956` bytes; família `glmocr`, F16, 1.1B, contexto 131072;
- `eos_token_id=59246`, `eot_token_id=59253`;
- `TEMPLATE {{ .Prompt }}`, `RENDERER/PARSER glm-ocr`, temperatura 0.

O artefato é uma republicação comunitária, não uma nova versão oficial da ZAI;
por isso o digest deve ser fixado e sua procedência revisada antes de qualquer
uso operacional permanente.

### Matriz controlada

Foi usada a mesma cópia temporária de NBR 6028, página física 4, sem modificar
o PDF, o PNG original, o banco ou a Gold.

1. **Reprodução textual mínima da issue:** prompt `Reply with the single word:
   OK`, `stream=false`, `num_predict=5000`. Resultado: HTTP 200, resposta
   `OK`, `done=true`, `done_reason=stop`, dois tokens de saída, sem repetição.
2. **Página com configuração equivalente ao modelo original:** prompt
   `Text Recognition:`, PNG Base64, `stream=false`, `temperature=0`,
   `num_ctx=16384`, `num_predict=16384`, `keep_alive=5m`. Resultado: HTTP 200,
   `done=true`, `done_reason=stop`, 604 tokens de saída, 1854 caracteres,
   23 linhas, SHA-256 do texto
   `8991d6e7f2810608683885cf6f5bc47833b5a9ab702bbec754823c080cbf6833`.
   Não foram encontradas linhas repetidas ou cauda degenerada.

O modelo original, na mesma configuração, havia retornado 1900 caracteres com
`done=false` e sem `done_reason`; portanto a troca controlada **resolveu o
problema de término da geração** neste host.

### Qualidade e passagem pelo adaptador

O texto alternativo contém o conteúdo principal da página e foi concluído, mas
uma inspeção visual identificou erros que impedem classificá-lo como extração
fiel: `Especiais` foi transcrito como `Especialis`, ocorrências de `A ABNT`
foram unidas como `AABNT`, e elementos visuais periféricos (marca d'água,
rodapé/página e aviso institucional em vermelho) não foram transcritos. O
avaliador determinístico retornou `eligible=true`, sem referência independente,
porque seus indicadores não medem fidelidade visual ou semântica; esse resultado
não foi tratado como aprovação factual nem promovido à Gold.

Executado pelo adaptador com `GLMOCR_MODEL=frob/glm-ocr:bf16`, o resultado foi
`extractor=glm_ocr`, sem fallback, sem diagnóstico de truncamento e com o mesmo
hash textual. A seleção automática não foi forçada; a saída deve permanecer em
revisão humana até haver referência/critério de qualidade que detecte essas
divergências.

### Decisão operacional

- **Compatibilidade corrigida:** confirmada para término (`done=true`/`stop`) e
  para o endpoint `/api/generate`.
- **Extração válida para uso automático:** não confirmada; a geração é completa,
  mas a qualidade desta página é insuficiente para promoção sem revisão.
- **Configuração segura limitada:** usar o artefato por digest fixado,
  `GLMOCR_DIRECT_CONTEXT=16384`, `GLMOCR_DIRECT_MAX_TOKENS=16384`, preservando
  a rejeição de falhas e a revisão humana. Não trocar o modelo padrão nem
  promover automaticamente com base apenas em `done=true`.
- **Pendência:** validar o artefato alternativo em amostra maior e com critérios
  independentes de completude/fidelidade antes de qualquer adoção permanente.

## Verificação final do contrato de elegibilidade

`assess_candidate` em `data/extraction_quality.py` define `eligible` como
ausência de falhas técnicas determinísticas: status de processamento inválido,
fallback, texto vazio (exceto página explicitamente vazia), geração não
confirmada ou densidade Unicode suspeita. O campo não significa que o conteúdo
seja fiel. Quando não há referência independente, o próprio resultado registra
`reference_status="unavailable"` e `reference_is_ground_truth=False`.

`select_page_candidate` usa essa elegibilidade técnica somente para ordenar e
registrar uma seleção provisória por página. Com um único candidato concluído,
sem referência, a decisão pode ser `selected` com razão
`deterministic_integrity_rank`; isso não é promoção nem evidência positiva de
fidelidade. Com dois candidatos idênticos sem referência, a seleção é
`quarantined` por `peer_agreement_without_reference`.

O caminho de avaliação em `data/rag_pipeline.py` grava `automatic_quality` e
transforma falhas técnicas em revisão/erro. A promoção passa por
`data/gold_policy.py`: para páginas não vazias, `_deterministic_metrics_decision`
exige `deterministic_validation.status="passed"`, referência do tipo
`independent_reference` ou `human_verified`, fingerprint e status confiáveis.
Métricas presentes, texto concluído ou `automatic_quality.eligible=true` não
substituem essa validação. Sem ela, a decisão é `retry_required` ou
`quarantined`; `_apply_page_selection` também rejeita qualquer seleção em
quarentena antes da Gold.

O cenário observado foi reproduzido deterministicamente nos testes:

- texto plausível com erro (`AABNT ...`) ficou tecnicamente elegível e foi
  selecionável para comparação, sem ser tratado como ground truth;
- a mesma situação, representada na política de promoção com métricas
  aparentemente boas e `automatic_quality.eligible=true`, mas sem
  `deterministic_validation`, resultou em `quarantined` e `eligible=False`.

Assim, não foi necessária alteração funcional: o contrato existente separa
conclusão técnica, integridade, seleção e promoção. A documentação e os testes
foram ampliados para impedir que `eligible=true` seja interpretado como
aprovação factual. O único bypass é `allow_unvalidated`, uma opção explícita de
operação (`--allow-unvalidated`); ela não é usada pelo caminho automático normal
e permanece uma decisão consciente fora do contrato de promoção validada.

### Validação desta etapa

- Direcionados F1/F2/F3/F4 e regressão de proveniência/agente: **98 passed, 2
  xfailed**.
- Integração PostgreSQL isolada (`extraction_quality_pg` e `gold_policy_pg`):
  **7 passed**.
- Suíte completa via `uv`: **399 passed, 1 skipped, 2 xfailed**.
- Ruff nos arquivos tocados: aprovado.
- `git diff --check`: aprovado.
- Crapper, Dryer e Mutator não foram repetidos, conforme a restrição desta
  fase; o relatório anterior continua incompleto e não constitui aprovação.

### Parecer

O cenário do GLM-OCR não permite promoção indevida apenas por
`eligible=true`. A extração corrigida pode ser selecionada como candidata
técnica, mas a Gold continua bloqueada sem referência independente confiável ou
revisão humana auditável. A Fase 4.4 está tecnicamente pronta para encerramento
e commit, sem necessidade de nova alteração funcional; o commit ainda não foi
realizado nesta execução.
