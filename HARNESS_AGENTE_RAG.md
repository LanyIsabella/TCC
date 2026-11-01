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

Objetivo: transformar a exigência de citação em uma garantia do sistema, e não
apenas em uma instrução sujeita a ser esquecida pelo modelo.

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
