# Configuração do harness do agente com RAG

## Objetivo

Garantir que respostas sobre normas acadêmicas e ABNT sejam fundamentadas no
RAG e sempre indiquem o documento normativo utilizado. Quando não houver
evidência suficiente, o agente não deve inventar uma regra ou referência.

## Alterações realizadas

### 1. Metadado legível da norma — `src/app/tools/rag_search.py`

Foi adicionado o campo `standard_label` ao resultado da ferramenta RAG.
Identificadores internos como `abnt_nbr_10520` passam a ser apresentados como
`ABNT NBR 10520`.

Objetivo: facilitar citações corretas e evitar que o modelo precise inferir ou
formatar sozinho o identificador da norma.

### 2. Regras de fundamentação — `src/app/prompt/prompt_sys.yaml`

O prompt agora determina que toda resposta normativa termine com `Base
normativa`, informe norma, versão/ano e página ou seção quando disponíveis,
use somente documentos retornados pelo RAG e informe explicitamente quando não
houver evidência suficiente.

Objetivo: orientar o comportamento do modelo durante a geração da resposta.

### 3. Garantia determinística — `src/app/agente.py` e `src/api/services/agent_service.py`

O wrapper central `ScopedAgent` agora extrai as mensagens internas da ferramenta
RAG, identifica documentos com `evidence_found=true`, adiciona automaticamente
a seção `Base normativa` quando necessário e usa a norma, versão e páginas
recuperadas. Essa camada é usada pela interface Streamlit e pelo terminal.

A mesma validação permanece no `AgentService`, garantindo o comportamento
também para a API HTTP.

Quando uma pergunta normativa não possui evidência documental válida, o
serviço retorna uma resposta segura informando que não foi localizada base
suficiente.

O wrapper também rejeita respostas-placeholder, como "faça sua pergunta" ou
"estou pronto para ajudar", quando a entrada é uma pergunta acadêmica concreta.
Isso evita que uma saudação do modelo seja exibida como se fosse uma resposta.

Quando o modelo não retorna evidência própria, o `ScopedAgent` executa uma
recuperação de contingência diretamente no RAG. Se ainda assim o modelo só
retornar uma saudação, os trechos normativos recuperados são apresentados de
forma extrativa, com a respectiva base normativa, em vez de uma resposta vazia.

Objetivo: transformar a exigência de citação em uma garantia do sistema, e não
apenas em uma instrução sujeita a ser esquecida pelo modelo.

### 4. Recuperação adaptativa para perguntas amplas

Foi adicionado `src/app/query_planner.py`. Perguntas amplas, como "quais são
as principais regras de formatação de um TCC", recebem uma consulta complementar
e limites de recuperação maiores. Os resultados são mesclados e reordenados sem
alterar o RRF original.

Objetivo: ampliar a cobertura para perguntas que envolvem vários subtemas, sem
criar cadastro manual por documento e sem tornar a recuperação dependente de
uma norma específica.

## Comportamento esperado

- Pergunta normativa com evidência: resposta fundamentada e citada.
- Pergunta normativa sem evidência: aviso sem criação de regra.
- Saudação ou pergunta fora do escopo normativo: não exige citação.

Exemplo:

```text
A citação direta curta deve seguir a regra aplicável da norma consultada.

### Base normativa

- ABNT NBR 10520:2023, p. 12.
```

## Validação

Os testes foram atualizados para simular evidência real do RAG e verificar a
inclusão da base normativa. Execute na raiz:

```bash
uv run pytest -q
```

## Validação de citações e evidências

Foi adicionado `src/app/citation_validator.py`. A validação usa os trechos já
retornados em `page_context`, sem alterar o RRF ou criar uma nova tabela.

Ela verifica se:

- a seção `Base normativa` existe;
- a norma citada pertence aos documentos recuperados;
- a versão citada corresponde à evidência;
- a página citada foi recuperada;
- trechos literais entre aspas aparecem no OCR retornado.

Quando um trecho literal não pode ser localizado, o sistema não o apresenta
como citação normativa. O regex é usado como validação da evidência, não como
filtro obrigatório da recuperação.

Quando existem frases normativas no `page_context`, a resposta também exibe a
seção `Trechos que sustentam a resposta`, com o trecho OCR, a norma, a versão e
a página recuperada. A seleção considera também os termos da pergunta, para
evitar mostrar apenas qualquer frase que contenha `deve` ou `devem`. Esses
trechos são evidências explicáveis; não substituem a resposta do agente nem
alteram o ranking RRF.

## Validação do pipeline de dados

O acesso ao PostgreSQL passou a carregar o `.env` dentro de `connect()`, o que
permite executar a auditoria estrutural diretamente pelo módulo do RAG.

Na validação realizada após a alteração:

- 10 documentos estavam ativos;
- 177 páginas estavam indexadas;
- 177 embeddings estavam presentes;
- todos os embeddings tinham dimensão válida;
- todos os hashes de embedding correspondiam ao texto;
- 354 de 354 páginas estavam avaliadas;
- não havia erros ou páginas pendentes.

Também foi criado `rag_eval/evals/datasets/abnt_grounding.csv` com casos de
avaliação de citações ABNT e abstinência quando não há evidência.
