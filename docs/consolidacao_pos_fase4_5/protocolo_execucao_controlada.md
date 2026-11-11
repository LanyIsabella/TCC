# Protocolo para avaliação experimental controlada

Este protocolo descreve uma execução futura. Nenhum experimento é iniciado por
esta consolidação.

## A. Executável sem referência humana completa

Pode ser executado somente no split `development`, com o snapshot e o banco em
leitura:

- preflight de Ollama e registro dos digests de `gemma4:e2b` e
  `nomic-embed-text`;
- recuperação documental no estágio `retrieval`;
- rastreabilidade de consulta, documento, página, `evidence_id`, turno e
  `tool_call_id`;
- latência por caso e, quando exposto pelo adaptador, contagem de tokens;
- cobertura de localizador de documento/página;
- retenção literal apenas quando o fragmento já existia no texto recuperado
  antes da compactação;
- testes de grounding determinístico com critérios verificáveis, sem usar a
  saída como prova de verdade documental.

Essas medições avaliam execução e rastreabilidade. Não autorizam concluir
correção factual, qualidade de OCR ou superioridade de extrator.

## B. Dependente de avaliação humana amostral

Exige referência humana para uma amostra documentada, não para todas as 177
páginas:

- fidelidade de `pdf_reader`, Docling e GLM-OCR;
- omissões, inclusões, duplicações, números, condições e estrutura;
- correção factual e suporte por afirmação;
- Recall@k, MRR/nDCG e cobertura de subperguntas quando o localizador tiver
  sido adjudicado;
- abstenção correta, falsa recusa, continuidade temática e avaliação de
  respostas ambíguas;
- calibração de CER/WER/similaridade e qualquer limiar de promoção Gold.

O lote de 12 páginas pode servir como amostra operacional inicial. As 40
páginas de `human_reference.json` são uma seleção adicional de cobertura e
risco. A escolha da amostra deve ser registrada antes da pontuação; não se deve
tratar texto nativo, concordância entre extratores ou nota do LLM como ground
truth.

## Sequência controlada

1. Confirmar branch, commit, hash do snapshot, hashes do dataset e estado
   somente leitura do banco.
2. Confirmar que Ollama responde ao preflight e registrar host lógico, modelos,
   digests e configuração efetiva sem versionar credenciais.
3. Criar novos arquivos de saída fora dos artefatos congelados; nunca sobrescrever
   `human_reference.json`, `reviews.json` ou o holdout.
4. Executar primeiro o estágio `retrieval` nos 40 casos de desenvolvimento;
   registrar `blocked`, `timeout` e `execution_error` separadamente de respostas.
5. Executar o estágio `agent` somente se o estágio anterior e a leitura do
   banco estiverem disponíveis; conservar os mesmos parâmetros observados.
6. Calcular apenas as métricas permitidas pelo estado das referências. Campos
   sem referência humana permanecem `null`, nunca zero ou aprovação.
7. Revisar a amostra documental e adjudicar divergências antes de qualquer
   métrica factual ou decisão de Gold.
8. Manter os 80 casos reservados intocados até haver protocolo e autorização
   específicos.

## Critérios para iniciar

A avaliação pode começar quando:

- o preflight confirmar ambos os modelos e os digests forem registrados;
- a conexão PostgreSQL de avaliação estiver confirmada como somente leitura;
- o snapshot, dataset e hashes de implementação estiverem congelados;
- os arquivos de saída forem novos e identificados pelo split;
- os critérios de referência humana da amostra estiverem definidos;
- o protocolo distinguir execução, rastreabilidade, fidelidade textual e
  correção factual;
- houver concordância explícita para não usar o holdout nem promover Gold durante
  a rodada.

Uma execução com Ollama indisponível deve terminar como `blocked`, com métricas
`null`; não deve ser repetida indefinidamente nem convertida em resultado
negativo ou aprovado.
