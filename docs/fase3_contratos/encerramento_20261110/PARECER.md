# Parecer técnico de encerramento da Fase 3

Data: 10/11/2026. Branch: `fix/fase3-contratos-agente-20261110`.
HEAD de referência: `3a279ab5bfe1215521e0fd476faaec8eab563baa`.

**Recomendação: encerrar tecnicamente a Fase 3 com ressalvas explícitas.**
Os contratos F10–F13 permanecem aprovados e não foi demonstrado defeito novo
bloqueante pelas verificações desta revisão. O Stop hook **continua sem
aprovação**. Suas falhas combinam limitações de infraestrutura, métricas
históricas e dívidas de funções antigas. Isso não permite declarar qualidade
global aprovada ou fidelidade factual geral do LLM.

Não houve alteração funcional, mudança de UI, instalação de dependência,
mudança de limiares, OCR, ingestão, embeddings, migração ou escrita no banco
produtivo. Foram acrescentados somente este pacote de evidências e testes
suplementares de auditoria. Os relatórios anteriores foram preservados.

## Classificação dos controles

As classificações avaliam o encerramento no escopo da Fase 3. Uma aprovação
com ressalvas não transforma um gate global reprovado em aprovação.
O registro estruturado correspondente está em [controles.json](controles.json).

| Controle | Classificação | Evidência e limite |
|---|---|---|
| 1. Seis contratos corrigidos | **Aprovado** | [Execução atual](contratos.xml): 6 aprovados; nenhum contrato F10–F13 marcado como xfail |
| 2. Suíte completa | **Aprovado com ressalvas** | [Regressão](regressao.log): 291 aprovados, 1 ignorado, 9 xfail; nenhuma falha inesperada |
| 3. Nove xfail restantes | **Aprovado** | [Inventário coletado](xfail_inventario.json): F1 = 3, F2 = 4, F6 = 2; todos `strict=True` |
| 4. Crapper e impactos indiretos | **Aprovado com ressalvas** | [Medição atual isolada](complexidade_verificada.json): 67 funções novas/alteradas com CRAP < 10, máximo 9; quatro violações antigas persistem |
| 5. Coverage automático | **Bloqueado por infraestrutura** | [Sondagens](ambientes_coverage_confirmados.json): pacote ausente no ambiente selecionado pelo hook; instalado somente no ambiente isolado de ferramentas |
| 6. Dryer | **Aprovado com ressalvas** | [Revisão](dryer_revisao.json): wrappers semelhantes, regra centralizada; getters e pipeline preexistentes; não é aprovação global sem duplicações |
| 7. Mutator do Stop | **Bloqueado por infraestrutura** | [Relatório preservado](stop_report.json): exit 124, orçamento compartilhado esgotado; métricas persistentes não comprovam execução integral |
| 8. Dois sobreviventes de serialização | **Aprovado com ressalvas** | [Reexecução](mutantes_ascii.log) e [análise](mutacao_revisao.json): sobreviventes reais; sem perda de dados demonstrada; sensibilidade do LLM não comprovada |
| 9. Preservação | **Aprovado com ressalvas** | [Arquivos](integridade.json) e [banco somente leitura](preservacao_banco.json) conferidos; snapshot não contém os valores históricos dos vetores |
| 10. Início da reconstrução isolada | **Aprovado com ressalvas** | Sem bloqueio novo demonstrado nesta fase; separa-se início do desenvolvimento de ativação produtiva |
| Confiabilidade atual de F1/F2/F6 | **Reprovado por defeito real** | Falhas preexistentes reproduzidas; continuam fora do escopo da Fase 3 e precisam integrar os critérios da reconstrução |

## Execuções novas e evidências anteriores

- Os seis contratos foram executados separadamente: [log](contratos.log).
- A suíte `tests` foi executada integralmente, com cobertura: [JUnit](regressao.xml).
- Foram executados **17 testes suplementares**, separados da suíte de produção:
  [código](test_impactos.py), [log](impactos.log) e [JUnit](impactos.xml).
  Cobrem os caminhos indiretos do CLI, importação do agente, formatos de conteúdo
  e as duas representações JSON. Nenhuma inferência real foi necessária.
- A cobertura foi registrada separadamente para [regressão](coverage.json),
  [suplementares](coverage_impactos.json) e [combinação](coverage_combinada.json).
  Avisos de módulos da API não importados na execução suplementar são esperados:
  esses módulos foram cobertos pela regressão, não por esse conjunto separado.
- As mutações manuais amplas da entrega anterior não foram repetidas integralmente.
  Seus logs continuam no diretório de artefatos anterior: política 70/70 eliminados;
  agente/evidências 110 eliminados e 2 sobreviventes; API 5/5; função alterada
  do terminal 4/4. Esses números são históricos, de escopos distintos, e não uma
  execução integral nova nem o resultado do Stop hook.
- Nesta revisão, somente os dois pontos de serialização foram selecionados
  novamente no Mutator, com dois workers e cópia privada idêntica aos fontes.
  O lint do novo arquivo de auditoria passou: [log](lint.log).

Os nove xfail são falhas esperadas efetivamente observadas, não testes ignorados.
F1 refere-se à confiança da promoção para Gold; F2 à avaliação/proveniência após
alteração de conteúdo/configuração; F6 à perda de regra tardia por compactação.
O teste de integração externa ignorado já estava fora da execução normal na
baseline. Não se conclui que o conjunto inteiro de defeitos F1–F16 foi corrigido.

## Cinco alertas antigos e impacto indireto

Os cinco corpos de função são iguais por AST ao HEAD de referência. A inspeção
de chamadas e os resultados por função estão em
[impactos_funcoes_antigas.json](impactos_funcoes_antigas.json).
Não se usou apenas a igualdade do código para descartar risco indireto.

| Função | Relação com a Fase 3 | Verificação e CRAP atual isolado |
|---|---|---|
| `terminal.main.run_interactive` | Chama `ChatSession.ask`, que mudou para a decisão central | Fluxo interativo com `ScopedAgent` real e agente interno simulado publica insuficiência, em vez de regra sem prova. CRAP **28,6411**, dívida antiga de complexidade/cobertura; demais comandos não foram todos exercitados |
| `terminal.main.normalize_content` | Não possui mais chamador em `src`; a sessão usa o consumidor central | Função antiga preservada, sem remoção fora do escopo. CRAP **112,9328**; o corpo continua sem cobertura de execução |
| `terminal.main.main` | Carrega o módulo alterado e chama a sessão alterada | Modos prompt/interativo e falha de carregamento testados. CRAP **12,2901**; caminhos antigos de exportação não foram todos exercitados |
| `terminal.main.load_agente_module` | Importa o módulo do agente alterado | Módulo atual, cache, arquivo ausente e erro de importação testados. CRAP **4**, cobertura **100%**; este alerta deixou de existir na medição atual isolada |
| `app.evidence._normalize_content` | Reutilizada pela identificação do turno/pergunta e processamento de respostas do modelo | Nove formas de conteúdo verificadas também por `ScopedAgent._content_text`. CRAP **11**, cobertura **100%**; CC 11 já impede CRAP < 10 mesmo com cobertura integral |

As percentagens calculadas pelo Crapper consideram suas próprias linhas/spans
e podem diferir ligeiramente das percentagens de statements do coverage.py.
Não houve refatoração dessas funções para reduzir o indicador. O Crapper de
arquivos inteiros continua com exit 2; os quatro alertas remanescentes são
explicitamente reconhecidos, sem classificá-los como regressões novas.

## Diagnóstico da infraestrutura

### Coverage e seleção do interpretador

O wrapper Windows seleciona `.venv/Scripts/python.exe` do projeto. É Python
3.13.13 e não contém `coverage`; o grupo `dev` do `pyproject.toml` também não o
declara. O ambiente das ferramentas usa Python 3.12.10 e já contém coverage
7.17.2. A instalação automática tentada pelo upstream é impedida pelo wrapper,
conforme a regra de não instalar dependências silenciosamente.

Portanto, não é indisponibilidade universal do pacote nem erro do agente RAG.
A medição manual usou o interpretador do projeto, o pacote já instalado nas
ferramentas e `COVERAGE_CORE=pytrace`, sem instalar nada. Não se injetou o ambiente
3.13 no processo nativo das ferramentas 3.12. Uma sondagem inicial entre versões
herdou `PYTHONHOME` do launcher e falhou; foi preservada e repetida com o ambiente
da sondagem corrigido. Isso não foi confundido com o diagnóstico do Stop.

### Colisão de relatórios LCOV

Há uma segunda limitação demonstrada: `crapper.coverage._merge_lcov` faz
`merged.update(parse_lcov(text))` para os vários LCOVs encontrados. Um relatório
posterior na enumeração substitui o mapa inteiro de linhas de um arquivo, sem
selecionar a medição mais recente. A leitura manual na raiz ainda mostrava os
cinco valores antigos, apesar da cobertura nova comprovada.

A confirmação foi feita em diretório temporário com os **mesmos seis fontes**,
mesmo limiar e apenas o LCOV combinado atual. Isso produziu as métricas da tabela
anterior: quatro violações antigas e nenhuma nas 67 funções novas/alteradas.
Veja [workspace e hashes](workspace_coverage.json), [log](crapper_isolado.log),
[EDN](crapper_isolado.edn) e [exit code](crapper_isolado_status.json).
Os LCOVs antigos não foram apagados nem sobrescritos para obter aprovação.

O diagnóstico e hashes dos componentes de infraestrutura lidos estão em
[infraestrutura.json](infraestrutura.json). Não se alteraram hooks globais ou
limiares. A correção permanente deve fixar explicitamente o ambiente e o LCOV
da execução; a configuração atual do Stop permanece pendente.

## Dryer: diferença entre duplicação e regra duplicada

Na seleção dos seis arquivos, o Dryer indica um par, com score 1,0: os wrappers
dos campos `content` e `message` no schema. São fronteiras de validação distintas
delegando à mesma função `_nonempty_text`. Antes da Fase 3, os dois validadores
duplicavam `strip`, teste de vazio e lançamento de erro. Essa regra passou a
existir em um lugar; a semelhança dos wrappers é aceita com ressalva documentada.
Não foi criada hierarquia adicional apenas para eliminar o alerta.

O Stop executa o Dryer no repositório inteiro e filtra pares que envolvem algum
arquivo selecionado. Por isso também reporta `_message_value` em `evidence`,
`query_planner` e `scope_guard`. Os três getters já existiam e seus corpos
permanecem iguais ao HEAD. O par do pipeline exibido no log global também é
preexistente e está fora do escopo. O exit 0 do CLI não significa ausência de
duplicações: o próprio hook marca seu resultado como não aprovado.

## Mutator: timeout, pontos não verificados e sobreviventes

O Stop dispõe de **50 segundos compartilhados** entre os três controles e
configura `--mutate-all --max-workers 2`. A execução de cobertura/regressão
atual consumiu cerca de 17 segundos, e cada mutante requer outra execução de
testes, além da preparação de workers. No Windows, o wrapper faz cópias privadas
em vez de symlinks, aumentando esse custo; a falha anterior de limpeza no
OneDrive já está documentada. A presente revisão não repete a limpeza problemática.

O relatório automático arquivado registra 75 eliminados, zero sobreviventes
e 160 pontos `uncovered`, com exit 124 e prazo esgotado. **Esses 160 pontos não
são 160 sobreviventes**, nem prova de que cada ponto foi executado. O hook lê
EDNs persistentes após o timeout, sem identificador que comprove conclusão de
cada resultado naquela rodada. Tampouco é correto atribuir os 75 eliminados
integralmente à última execução. O resumo automático não substitui os logs
manuais concluídos, e seu zero de sobreviventes não invalida os dois casos reais.

Na reexecução delimitada desta revisão foram selecionadas as linhas 105 e 278 de
`agente.py`. **Ambos os pontos sobreviveram**, sem timeout dessa execução.
O resumo de arquivo do CLI também exibe 43 eliminados carregados do histórico;
eles não foram contados como novas execuções. A seleção e o reaproveitamento
estão confirmados no código de `mutator.engine` e em
[mutacao_revisao.json](mutacao_revisao.json).

### O que significam os dois `ensure_ascii=False`

Um ponto está no novo verificador de afirmações; o outro, na serialização de
contexto para síntese, já utilizava essa opção antes da Fase 3. Alterar para
`True` mantém o JSON válido e todos os valores após decodificação, inclusive
acentos, quebras e caracteres fora do BMP. Os dois testes suplementares exercitam
os métodos reais e variantes isoladas, capturam a entrada enviada ao modelo e
confirmam **igualdade dos dados e diferença dos textos brutos**.

O LLM recebe esse texto diretamente, portanto não é correto declarar os mutantes
formalmente equivalentes para o sistema inteiro. Escapes podem afetar tokens,
latência ou decisões. Os testes existentes simulam o modelo; o ensaio real
anterior de 24 cenários não foi um experimento comparativo entre as duas formas.

Conclusão: não foi demonstrada perda de conteúdo, falha de transporte ou quebra
de contrato. Existe uma **lacuna experimental de sensibilidade do modelo**, não
uma regressão funcional comprovada. Os mutantes continuam sobreviventes; não se
adicionou teste que apenas espelhe a opção de serialização para eliminá-los.
Essa ressalva não bloqueia o início de desenvolvimento isolado da ingestão,
mas impede afirmar equivalência probabilística ou aprovação integral de mutação.

## Preservação conferida no estado atual

- Os **1.255 arquivos existentes** registrados no início desta revisão mantiveram
  os hashes, incluindo os relatórios antigos, fontes e testes de produção.
- Os 24 arquivos congelados da baseline, os 63 arquivos do pacote humano, os
  10 PDFs e os 40 hashes de fontes fora do escopo coincidem com seus manifests.
- Snapshot preservado:
  `ba555e70267df221683c429d7ab6c965d03b73e64e7d1d2e52dbe0d1ace9ba99`.
- Em transação PostgreSQL `REPEATABLE READ READ ONLY`, seguida de rollback,
  foram comparados os registros Gold e de índice ao snapshot: **13 variantes,
  10 ativas e 266 entradas de índice**, iguais nas projeções registradas. Os
  hashes documentais Bronze também coincidem. Esses números incluem registros
  inativos; não devem ser confundidos com 177 páginas físicas do corpus.
- O snapshot deliberadamente exclui `embedding` e `search_vector`. Confirmou-se
  a existência de 266 embeddings não nulos, mas não há digest histórico dos
  valores para provar invariância byte a byte. Não houve qualquer escrita ou
  solicitação de geração de embeddings nesta revisão.

Não foram reprocessados documentos ou extrações. A consulta leu dados existentes;
o pipeline de ingestão não foi executado. Os testes da baseline que reproduzem
F1/F2 usam fixtures locais e SQLite isolado, sem afetar o PostgreSQL produtivo.

## Encerramento e riscos para a próxima fase

Não foi encontrada falha nova bloqueante nos contratos da Fase 3. É tecnicamente
razoável encerrar esta entrega **com as ressalvas registradas** e iniciar o
planejamento e a reconstrução da ingestão em ambiente isolado. Esta recomendação
não inicia a Fase 4, não concede aprovação ao Stop e não autoriza ativação
produtiva de uma ingestão reconstruída.

F1/F2/F6 são defeitos reais preexistentes e devem constar dos critérios de
aceitação da reconstrução: confiança de promoção para Gold, invalidação e
proveniência de avaliações, e preservação das regras normativas na compactação.
A aplicação atual não deve ser considerada saneada nesses pontos. A publicação
de novos dados ativos precisará de validação própria, revisão documental,
preservação de versões e demonstração de que esses riscos foram tratados.

Permanecem pendentes a correção permanente da infraestrutura do Stop, as dívidas
de complexidade/cobertura antigas, a sensibilidade do modelo à representação
JSON e a avaliação humana/representativa do RAG completo. Nenhum teste
determinístico ou cenário sintético comprova fidelidade factual universal.

O mecanismo auxiliar Graphify não encontrou grafo no caminho solicitado nesta
revisão; as relações relevantes foram verificadas diretamente no código por AST
e busca de chamadores, sem criar índice adicional ou inferir cobertura do grafo.
Não se modificou a configuração de tooling nem se alegou economia de tokens.
