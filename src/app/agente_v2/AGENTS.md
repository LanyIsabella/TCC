## Code Review Rules

### Objetivo da revisão

Garantir que cada Pull Request contribua para entregar um agente acadêmico conversacional funcional, capaz de interpretar solicitações, manter contexto, utilizar o RAG e fundamentar orientações normativas em evidências documentais reais.

Priorizar defeitos funcionais, regressões, violações de contratos e incompatibilidades. Não bloquear entregas por preferências estilísticas ou refatorações sem impacto comprovado.

### 1. Preservação da infraestrutura

**Regra:** a implementação V2 deve reutilizar a infraestrutura existente, sem alterar silenciosamente sua metodologia.

Verificar especialmente:

- Preservação da construção de `client.py`.
- Continuidade do uso de LangChain e Ollama.
- PostgreSQL e pgvector.
- `nomic-embed-text`, dimensão 768.
- Indexação e recuperação baseadas em páginas.
- Busca híbrida e RRF ponderado.
- Preservação dos parâmetros configurados, incluindo RRF_K=60 e pesos 1,0 / 1,3 / 1,5 / 4,0.
- Preservação da implementação anterior do agente.

**Bloquear:** alterações que substituam, dupliquem ou modifiquem esses componentes sem necessidade comprovada e aprovação explícita.

**Caminho seguro:** consumir as interfaces existentes por adaptadores e preservar a configuração efetiva.

### 2. Fundamentação normativa

**Regra:** nenhuma afirmação normativa deve ser apresentada como fundamentada sem suporte documental verificável.

Verificar:

- IDs de evidências realmente recuperadas.
- Documento, edição e página corretos.
- Evidências pertinentes às afirmações produzidas.
- Preservação de condições e exceções.
- Separação entre evidências disponíveis, selecionadas e publicadas.
- Tratamento de contradições, omissões e ausência de suporte.

**Bloquear:** referências inventadas, evidências não selecionadas publicadas como suporte ou respostas normativas que contornem o grounding.

**Caminho seguro:** validar a síntese contra as evidências recuperadas e apresentar limitações ou abstenção quando necessário.

### 3. Conversação e contexto

**Regra:** o agente deve compreender solicitações em linguagem natural, sem depender exclusivamente de perguntas predefinidas.

Verificar:

- Interpretação semântica pela LLM.
- Esclarecimento de solicitações ambíguas.
- Continuidade com mensagens anteriores.
- Isolamento por conversa e turno.
- Funcionamento de Nova conversa.
- Ausência de reutilização indevida de evidências anteriores.

**Bloquear:** vazamento de contexto, reutilização de respostas anteriores como evidência normativa ou roteamento rígido que impeça solicitações equivalentes.

**Caminho seguro:** manter histórico conversacional separado da recuperação documental.

### 4. Encerramento e utilidade das respostas

**Regra:** consultas normativas devem conseguir produzir respostas utilizáveis quando houver evidências suficientes e uma síntese validada.

Verificar:

- A conclusão normativa não depende obrigatoriamente de uma chamada final à ferramenta `AgentAnswer`.
- O modelo pode sintetizar utilizando as evidências.
- Erros de parsing são identificados.
- Tentativas adicionais possuem orçamento limitado.
- Encerramentos inválidos não publicam afirmações normativas como fundamentadas.
- Respostas conversacionais não são bloqueadas por ausência de evidência desnecessária.

**Bloquear:** regressões que façam o agente recuperar evidências adequadas e perder sistematicamente a resposta por falha evitável de encerramento.

**Caminho seguro:** separar recuperação, síntese estruturada, validação e publicação, preservando o grounding.

### 5. Integração funcional

**Regra:** funcionalidades críticas precisam funcionar com os serviços reais, e não somente com mocks.

Para alterações relacionadas à orquestração ou à recuperação, verificar a existência de validação apropriada com:

- Ollama.
- PostgreSQL.
- Recuperação híbrida.
- Grounding.
- Interface conversacional.

Uma consulta sobre formatação de citação direta longa deve ser capaz de recuperar a norma pertinente e produzir uma resposta fundamentada quando o conteúdo recuperado for suficiente.

Se a infraestrutura necessária estiver indisponível, registrar a limitação; não declarar a integração validada.

### 6. Testes e regressões

Utilizar o ambiente gerenciado pelo projeto.

Comandos principais:

- `uv run --locked pytest -q`
- `uv run --locked ruff check .`
- `git diff --check`

Verificar testes relevantes para:

- Comportamento conversacional.
- Isolamento de contexto.
- Recuperação normativa.
- Síntese.
- Grounding.
- API e Streamlit.

Não tratar gates incompletos ou indisponíveis como aprovados.

Não exigir a resolução de problemas preexistentes fora do escopo da PR, salvo quando impedirem a validação obrigatória.

### 7. Critérios de severidade

**Bloqueante:** defeito funcional reproduzido, regressão essencial, ausência de grounding normativo, exposição de dados, alteração metodológica indevida ou incompatibilidade relevante.

**Importante:** tratamento de erro insuficiente, falta de teste crítico ou problema de integração demonstrável.

**Melhoria futura:** refatoração cosmética, otimização prematura ou melhoria sem impacto na entrega atual.

Cada apontamento deve indicar o arquivo, a linha, o comportamento incorreto, seu impacto e uma correção viável.

### 8. Limites da revisão

Não recomendar reingestão, mudanças em embeddings, troca de modelo, substituição de framework ou reconstrução da infraestrutura sem defeito comprovado.

Não utilizar os 80 casos reservados do holdout.

Não exigir comparação científica LLM com e sem RAG nesta etapa.

Não transformar a revisão em auditorias extensas que atrasem a entrega.

**Prioridade: garantir um agente funcional, conversacional e capaz de responder com evidências normativas reais.**
