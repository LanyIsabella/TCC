# API do Agente

Este diretório concentra a API HTTP do projeto construída com `FastAPI`.
Ela expõe endpoints simples para verificar a saúde da aplicação e para
enviar mensagens ao agente definido em `src/app/agente.py`.

## Objetivo

A API foi organizada para separar responsabilidades:

- `core/`: configurações e exceções da camada HTTP.
- `routers/`: definição dos endpoints.
- `schemas/`: contratos de entrada e saída com `Pydantic`.
- `services/`: regras de orquestração entre rota e agente.
- `dependencies.py`: criação e injeção de dependências reutilizáveis.
- `main.py`: montagem da aplicação FastAPI.

## Estrutura da pasta

```text
src/api/
├── __init__.py
├── README.md
├── dependencies.py
├── main.py
├── core/
│   ├── __init__.py
│   ├── config.py
│   └── exceptions.py
├── routers/
│   ├── __init__.py
│   ├── agent.py
│   └── health.py
├── schemas/
│   ├── __init__.py
│   ├── agent.py
│   ├── common.py
│   └── health.py
└── services/
    ├── __init__.py
    └── agent_service.py
```

## Fluxo da requisição

1. A requisição chega em uma rota dentro de `routers/`.
2. O corpo é validado por um schema definido em `schemas/`.
3. A rota usa uma dependência de `dependencies.py`.
4. A dependência entrega uma instância de `AgentService`.
5. O serviço chama o agente real em `src/app/agente.py`.
6. A resposta do agente é normalizada e devolvida em JSON.

## Arquivos principais

### `main.py`

Cria a aplicação FastAPI com:

- metadados da API;
- registro das rotas;
- handlers de exceção para erros do agente;
- rota raiz `/` com informações básicas da aplicação.

### `dependencies.py`

Expõe `get_agent_service()`, que:

- instancia o agente da camada `src/app`;
- encapsula falhas de inicialização;
- usa cache para evitar recriação desnecessária.

### `core/config.py`

Centraliza a leitura do `.env` e monta o objeto `Settings`, que contém:

- nome da aplicação;
- versão;
- prefixo da API;
- variáveis relacionadas ao Ollama;
- host do LangSearch.

### `core/exceptions.py`

Define as exceções de domínio usadas na API:

- `AgentNotConfiguredError`;
- `AgentExecutionError`;
- `AgentResponseError`.

### `routers/agent.py`

Contém a rota:

- `POST /api/v1/agent/chat`

Essa rota recebe uma mensagem, opcionalmente um histórico, e retorna a
resposta do agente com as mensagens normalizadas.

### `routers/health.py`

Contém a rota:

- `GET /api/v1/health`

Usada para verificar se a API está de pé e para retornar nome e versão.

### `schemas/agent.py`

Modelos Pydantic da conversa:

- `ConversationMessage`;
- `AgentChatRequest`;
- `AgentChatResponse`.

Esses modelos impedem payloads malformados e garantem que campos como
`message` e `content` não sejam vazios.

### `schemas/common.py`

Modelos compartilhados:

- `ErrorResponse`;
- `APIInfoResponse`.

### `schemas/health.py`

Modelo da resposta de health check:

- `HealthResponse`.

### `services/agent_service.py`

Implementa a regra principal da API:

- recebe o schema validado;
- monta o payload esperado pelo agente;
- executa `agent.invoke(...)`;
- normaliza mensagens vindas em formatos diferentes;
- extrai a resposta final do assistente;
- converte falhas para exceções de domínio.

## Endpoints

### `GET /`

Retorna metadados da API.

Exemplo de resposta:

```json
{
  "app_name": "TCC Sistema Agent API",
  "version": "0.1.0",
  "docs_url": "/docs",
  "api_prefix": "/api/v1"
}
```

### `GET /api/v1/health`

Retorna o estado da aplicação.

Exemplo de resposta:

```json
{
  "status": "ok",
  "app_name": "TCC Sistema Agent API",
  "version": "0.1.0"
}
```

### `POST /api/v1/agent/chat`

Envia uma pergunta para o agente.

Exemplo de requisição:

```json
{
  "message": "Como fazer uma citacao direta curta na ABNT?",
  "history": [
    {
      "role": "assistant",
      "content": "Posso ajudar com normas ABNT."
    }
  ]
}
```

Exemplo de resposta:

```json
{
  "answer": "A citacao direta curta deve permanecer no corpo do texto...",
  "messages": [
    {
      "role": "assistant",
      "content": "Posso ajudar com normas ABNT."
    },
    {
      "role": "user",
      "content": "Como fazer uma citacao direta curta na ABNT?"
    },
    {
      "role": "assistant",
      "content": "A citacao direta curta deve permanecer no corpo do texto..."
    }
  ]
}
```

## Possíveis erros

### `422 Unprocessable Entity`

Retornado quando o payload não respeita os schemas Pydantic.

Exemplos:

- `message` vazio;
- `content` vazio no histórico;
- campo extra não permitido.

### `503 Service Unavailable`

Retornado quando a API não consegue inicializar o agente.

Exemplo:

```json
{
  "detail": "Nao foi possivel inicializar o agente."
}
```

### `502 Bad Gateway`

Retornado quando o agente falha na execução ou responde em formato inválido.

## Como executar

Na raiz do projeto:

```bash
uv run uvicorn src.api.main:app --reload
```

Depois, acesse:

- documentação Swagger: `http://127.0.0.1:8000/docs`
- documentação ReDoc: `http://127.0.0.1:8000/redoc`

## Como testar

Na raiz do projeto:

```bash
uv run --group dev pytest
```

## Observações

- A API depende das variáveis de ambiente usadas pelo agente em `src/app`.
- O serviço da API não contém a lógica de IA; ele apenas adapta entrada e
  saída entre HTTP e o agente.
- A documentação inline dos módulos em `src/api` está em português
  brasileiro para facilitar manutenção do projeto.
