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