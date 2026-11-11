# AGENTS.md — Diretrizes de Engenharia do Projeto TCC

## 1. Identidade e objetivo do projeto

Este repositório contém um sistema conversacional baseado em Retrieval-Augmented Generation (RAG), desenvolvido como Trabalho de Conclusão de Curso.

O objetivo é permitir consultas fundamentadas a documentos normativos da ABNT relacionados à produção de trabalhos acadêmicos.

A solução deve priorizar:

- Fidelidade às fontes documentais.
- Qualidade da recuperação de informações.
- Rastreabilidade das evidências.
- Precisão das respostas.
- Reprodutibilidade experimental.
- Escalabilidade e manutenabilidade.
- Qualidade e consistência da arquitetura.

O agente de desenvolvimento deve sempre considerar esses objetivos ao propor ou implementar alterações.

## 2. Princípios de engenharia de software

Toda implementação deverá seguir os seguintes princípios:

- Separação de responsabilidades.
- Baixo acoplamento e alta coesão.
- SOLID quando aplicável.
- DRY sem abstrações prematuras.
- KISS e simplicidade arquitetural.
- Tipagem explícita sempre que apropriado.
- Tratamento adequado de exceções.
- Logging estruturado.
- Configurações externas ao código.
- Testabilidade e modularidade.

Não introduzir padrões arquiteturais apenas por formalidade.

Priorizar soluções simples, justificáveis e sustentáveis.

## 3. Protocolo obrigatório de desenvolvimento

Antes de implementar qualquer alteração:

1. Identificar os componentes envolvidos.
2. Ler o código existente.
3. Compreender os contratos e dependências.
4. Identificar impactos e riscos.
5. Definir os comportamentos esperados.
6. Criar ou ajustar os testes necessários.
7. Executar os testes para estabelecer a baseline.
8. Implementar a alteração incrementalmente.
9. Executar novamente os testes.
10. Verificar regressões e documentar os resultados.

Não realizar refatorações extensas sem justificativa técnica.

Não modificar funcionalidades fora do escopo solicitado.

## 4. Test-Driven Development

Adotar TDD nas alterações de comportamento que permitam testes automatizados determinísticos.

Aplicar o ciclo:

- Red: implementar teste que represente o comportamento desejado.
- Green: implementar a menor alteração capaz de satisfazer o teste.
- Refactor: melhorar o código preservando o comportamento validado.

Para código existente, realizar testes de caracterização quando necessário.

Nenhum teste poderá ser declarado aprovado sem execução real.

Falhas, testes bloqueados e limitações do ambiente deverão ser explicitamente relatados.

Para componentes probabilísticos, complementar os testes com avaliações experimentais reproduzíveis.

## 5. Qualidade documental e ingestão

A ingestão deve preservar a fidelidade aos documentos originais.

Requisitos permanentes:

- Não descartar conteúdo silenciosamente.
- Preservar a rastreabilidade documental e por página.
- Não fabricar metadados.
- Registrar erros e incertezas de extração.
- Preservar documentos originais.
- Permitir reprocessamento e comparação de versões.
- Validar integridade e completude dos resultados.
- Diferenciar extração nativa de texto e OCR.
- Preservar elementos normativos relevantes.

Alterações no pipeline devem ser acompanhadas de testes e evidências de qualidade.

## 6. Persistência e integridade

O projeto utiliza PostgreSQL e pgvector, conforme a implementação atual.

Antes de qualquer alteração:

- Inspecionar os schemas e modelos existentes.
- Avaliar compatibilidade com registros persistidos.
- Evitar alterações destrutivas.
- Preservar integridade referencial.
- Utilizar migrações versionadas quando apropriado.
- Garantir estratégias de reversão.
- Não apagar dados sem autorização explícita.

Manter separação entre regras de negócio e acesso à persistência.

## 7. Recuperação e geração de respostas

O mecanismo RAG deve priorizar recuperação relevante e fundamentação documental.

Não alterar estratégias de indexação, embeddings, ranking ou fusão sem:

- Diagnóstico.
- Hipótese de melhoria.
- Testes comparativos.
- Métricas adequadas.
- Evidências de resultados.

Preservar a rastreabilidade entre evidências e documentos originais.

Não utilizar respostas aparentemente plausíveis como evidência de correção.

## 8. Arquitetura do agente e ferramentas

Separar claramente:

- Serviços internos.
- Casos de uso.
- Adaptadores de infraestrutura.
- Ferramentas invocáveis pelo LLM.

Uma capacidade deve ser disponibilizada como tool quando sua seleção dinâmica pelo agente for funcionalmente necessária.

Não transformar indiscriminadamente funções internas em tools.

Toda tool deve possuir:

- Responsabilidade bem definida.
- Contrato de entrada e saída.
- Validação.
- Tratamento de falhas.
- Testes.
- Descrição clara para o modelo.
- Limites operacionais.

Evitar duplicidade entre ferramentas e chamadas desnecessárias.

## 9. Qualidade científica e rastreabilidade

Considerar que o sistema integra uma pesquisa acadêmica.

Portanto:

- Registrar decisões metodológicas relevantes.
- Preservar parâmetros experimentais.
- Versionar configurações de avaliação.
- Não fabricar métricas ou resultados.
- Diferenciar hipóteses, observações e conclusões.
- Não utilizar referências bibliográficas inexistentes.
- Priorizar experimentos reproduzíveis.

Mudanças que afetem a metodologia descrita no TCC devem ser identificadas explicitamente.

## 10. Organização do repositório

Antes de criar arquivos ou diretórios:

1. Inspecionar a estrutura existente.
2. Identificar o módulo responsável.
3. Reutilizar componentes adequados.
4. Evitar duplicação funcional.
5. Respeitar convenções do repositório.

Não criar scripts, relatórios ou módulos soltos na raiz sem justificativa.

Manter testes próximos de suas responsabilidades funcionais, seguindo o padrão existente.

## 11. Restrições permanentes

- Não modificar a UI sem solicitação explícita.
- Não executar operações destrutivas sem autorização.
- Não remover funcionalidades existentes sem análise de impacto.
- Não modificar parâmetros experimentais arbitrariamente.
- Não instalar dependências sem justificativa.
- Não alterar configurações sensíveis sem necessidade.
- Não armazenar segredos em arquivos versionados.
- Não ocultar falhas de testes.
- Não declarar qualidade comprovada sem evidências.

## 12. Comunicação e prestação de contas

Em tarefas de implementação relevantes, apresentar:

- Diagnóstico resumido.
- Alterações realizadas.
- Justificativas das decisões.
- Testes executados e resultados.
- Riscos ou limitações.
- Pendências e próximos passos.

Diferenciar claramente:

- Implementado.
- Testado.
- Validado experimentalmente.
- Pendente.

Não afirmar que uma funcionalidade foi validada apenas porque o código foi implementado.

## 13. Hierarquia das instruções

Este documento define as diretrizes permanentes do repositório.

As tarefas específicas devem respeitar estas diretrizes, salvo quando uma alteração for explicitamente autorizada e compatível com as instruções de prioridade superior.

Em caso de conflito entre a documentação acadêmica e a implementação, registrar a divergência e investigar antes de decidir.

Não presumir que documentação histórica corresponde ao estado atual da solução.

## Code Review Rules — Agente Acadêmico V2

## Objetivo da revisão

Garantir que cada Pull Request contribua para entregar um agente acadêmico conversacional funcional, capaz de interpretar solicitações, manter contexto, utilizar o RAG e fundamentar orientações normativas em evidências documentais reais.

Priorizar defeitos funcionais, regressões, violações de contratos e incompatibilidades. Não bloquear entregas por preferências estilísticas ou refatorações sem impacto comprovado.

## 1. Preservação da infraestrutura

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

## 2. Fundamentação normativa

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

## 3. Conversação e contexto

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

## 4. Encerramento e utilidade das respostas

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

## 5. Integração funcional

**Regra:** funcionalidades críticas precisam funcionar com os serviços reais, e não somente com mocks.

Para alterações relacionadas à orquestração ou à recuperação, verificar a existência de validação apropriada com:

- Ollama.
- PostgreSQL.
- Recuperação híbrida.
- Grounding.
- Interface conversacional.

Uma consulta sobre formatação de citação direta longa deve ser capaz de recuperar a norma pertinente e produzir uma resposta fundamentada quando o conteúdo recuperado for suficiente.

Se a infraestrutura necessária estiver indisponível, registrar a limitação; não declarar a integração validada.

## 6. Testes e regressões

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

## 7. Critérios de severidade

**Bloqueante:** defeito funcional reproduzido, regressão essencial, ausência de grounding normativo, exposição de dados, alteração metodológica indevida ou incompatibilidade relevante.

**Importante:** tratamento de erro insuficiente, falta de teste crítico ou problema de integração demonstrável.

**Melhoria futura:** refatoração cosmética, otimização prematura ou melhoria sem impacto na entrega atual.

Cada apontamento deve indicar o arquivo, a linha, o comportamento incorreto, seu impacto e uma correção viável.

## 8. Limites da revisão

Não recomendar reingestão, mudanças em embeddings, troca de modelo, substituição de framework ou reconstrução da infraestrutura sem defeito comprovado.

Não utilizar os 80 casos reservados do holdout.

Não exigir comparação científica LLM com e sem RAG nesta etapa.

Não transformar a revisão em auditorias extensas que atrasem a entrega.

**Prioridade: garantir um agente funcional, conversacional e capaz de responder com evidências normativas reais.**
