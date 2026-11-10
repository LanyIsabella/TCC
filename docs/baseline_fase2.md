# Preparação da baseline experimental do TCC

## Resultado e escopo

Foi preparada a infraestrutura de caracterização e avaliação, sem alterar módulos
de produção, prompts, interface, originais, textos/embeddings ativos ou registros
do banco. Não houve migração, reprocessamento, commit ou push.

Estado inicial observado: branch `devb`, commit
`3a279ab5bfe1215521e0fd476faaec8eab563baa`, somente `?? AGENTS.md` preexistente.
Trabalho na branch `baseline/fase2-caracterizacao-20261109`, preservando esse arquivo.
O snapshot guarda a observação inicial e o estado Git no momento da captura como
informações distintas. Seus 46 hashes permitem comparar as fontes e configurações.
Os módulos de produção permanecem iguais. Depois da captura, foram alteradas apenas
configurações de avaliação: `testpaths=["tests"]` no pytest para impedir coleta dos
workers gerados, e exclusões `.metrics/`/`target/` no `.gitignore`. Essas mudanças
não alteram parâmetros ou dependências da aplicação; explicam a diferença do hash
de `pyproject.toml` em relação ao estado inicial congelado.

## Inventário e reprodução

| Artefato | Conteúdo e estado |
|---|---|
| `rag_eval/baseline/artifacts/initial_state.json` | 10 PDFs/177 páginas/531 extrações, textos e hashes, avaliações, 30 execuções e versões Gold; observação somente leitura |
| `rag_eval/baseline/artifacts/integrity_report.json` | Enumeração das 28 páginas ativas com revisão manual e 131 com conclusão não confirmada; nenhum desses indicadores prova perda textual |
| `rag_eval/baseline/artifacts/human_reference.json` | Seleção preliminar de 40 páginas, todas pendentes de conferência e transcrição humana |
| `rag_eval/baseline/artifacts/all_pages_review.json` | Formulário vazio para as 177 páginas |
| `rag_eval/baseline/artifacts/extraction_evaluation.json` | 531 extrações sem CER/WER fabricados; aguardam referências humanas |
| `rag_eval/baseline/queries.json` | 120 propostas de consulta, 40 desenvolvimento/80 reservadas; localizadores verificados automaticamente |
| `rag_eval/baseline/artifacts/retrieval_development.json` | Tentativa real de pré-verificação: 40 casos bloqueados, sem inferência |
| `rag_eval/baseline/artifacts/agent_development.json` | Tentativa real de pré-verificação: 40 casos bloqueados, sem inferência |
| `rag_eval/baseline/artifacts/tests_full.xml` e `.log` | Evidência da suíte completa |
| `rag_eval/baseline/artifacts/contracts_red.xml` e `.log` | Evidência das falhas de comportamento com `--runxfail` |

Captura inicial SHA-256:
`ba555e70267df221683c429d7ab6c965d03b73e64e7d1d2e52dbe0d1ace9ba99`.
Seleção humana SHA-256:
`5645653d557f3712f2026ba8ac1ddbf49f2c2b9b5b9a0558f61304a70624fba9`.
O hash de cada original, as versões ativas e as condições observadas estão no
snapshot. Os dez hashes originais coincidem com os da Bronze. Não foram exportados
vetores, credenciais nem supostas configurações históricas desconhecidas.

O protocolo operacional e os comandos completos estão em
`rag_eval/baseline/README.md`. Os parâmetros foram observados, sem ajuste: recuperação
por página, RRF k=60 e pesos 1/1,3/1,5/4; tool 6 páginas candidatas/1 documento por
padrão, expansão conforme código, três páginas diretas/documento, compactação
1.800 caracteres/página e 5.000/documento; `nomic-embed-text`/768;
`gemma4:e2b`/temperatura 0,7; GLM direto conforme configuração atual.

## Matriz dos problemas críticos

Os testes `test_defect_pipeline.py` e `test_defect_agent.py` ficam em
`tests/baseline`. Cada caso possui caracterização atual e contrato corrigido
marcado `xfail(strict=True)`. A execução explícita `--runxfail` demonstra o Red.

| Problema | Comportamento atual reproduzido | Contrato esperado | Casos Red |
|---|---|---|---:|
| F1 | Gate aceita status success legado sem considerar revisão, nota ausente ou método fallback | Avaliação não confiável impede promoção | 3 |
| F2 | Force conserva nota/status; avaliação pula texto alterado; mudança de original/configuração reutiliza identidade | Invalidar derivados e identificar execução pelo conteúdo/configuração | 4 |
| F6 | Regra tardia desaparece no orçamento da página/documento | Preservar regra necessária ou indicar insuficiência do contexto | 2 |
| F10 | Recovery sem evidência mantém resposta normativa | Abster/sinalizar insuficiência em vez de apresentar regra sem suporte | 1 |
| F11 | matched_text legitima número contraditório; texto sem evidências é preservado | Identidade não substitui sustentação factual | 2 |
| F12 | Tool antiga suprime recuperação da nova pergunta | Vincular busca/evidência ao turno correspondente | 1 |
| F13 | API aceita system/tool fornecidos pelo cliente | Fronteira externa rejeita papéis privilegiados | 2 |

F1 testa o limite de `is_gold_ready`, sem executar promoção completa. F2 executa
SQL real adaptado em SQLite em memória, sem comprovar o dialeto ou concorrência
PostgreSQL. Ferramentas/modelos simulados existem somente nos testes determinísticos
e não aparecem como resultados experimentais nos relatórios de consultas.

## Observações adicionais dos metadados

O relatório encontra seis divergências de campos (título e versão de três Gold
ativas) entre colunas e JSON. A tool atual usa fallback do JSON em alguns caminhos;
a divergência não significa falha em toda consulta.

O PDF da NBR 6034 identifica a edição como 2004 e a vigência a partir de 2005.
Manifesto/Bronze/Gold registram versão 2005. Os localizadores do dataset preservam
o identificador 2004 lido na capa, também conferida visualmente nesta fase. Esta é
uma divergência adicional de F5, não corrigida. A hipótese de confusão entre edição
e vigência precisa de investigação antes da futura atualização dos metadados.

## Resultados e limitações

Suíte original antes das adições: **83 passed, 1 skipped** (19,82 s).
Os testes de caracterização/contrato dos defeitos produziram **15 passed e 15
xfailed**; com `--runxfail`, **15 passed e 15 failed**, sem erro de coleta/infraestrutura.
As falhas são preservadas de propósito. O teste externo GEDWeb não foi habilitado.

A execução anterior à configuração `testpaths` teve 55 erros de coleta devido a
cópias residuais de workers em `target/`; não eram regressões do produto.
A descoberta foi corrigida sem apagar essas cópias. Os resultados finais ficam em
`artifacts/tests_full.xml` e em `artifacts/verification.json`.
Resultado final: **139 passed, 1 skipped, 15 xfailed** (6,36 s), sem regressões
na suíte original; Ruff aprovado. Em modo Red explícito permanecem 15 falhas
comportamentais e 15 caracterizações aprovadas.

Crapper passou com CRAP máximo 9,2 (limite estrito inferior a 10) e Dryer não
encontrou candidatos com similaridade >=0,8. A primeira tentativa de cobertura
não encontrou o pacote no ambiente escolhido automaticamente; foi reutilizado
o pacote já instalado no tooling isolado, sem instalação ou alteração de dependências.

Mutator permanece incompleto. Uma execução ampla encontrou falha de limpeza
`WinError 32` em worker privado. Após reforçar um caso que havia sobrevivido, a
execução focalizada de `audit.py` registrou 8 mutantes eliminados, 0 sobreviventes e
7 pontos sem cobertura; os demais módulos não tiveram validação completa de mutação.
O score dos pontos executados não deve ser apresentado como aprovação global.
Evidências em `artifacts/mutator_targeted.log` e `.metrics/mutate/`.

Ollama indisponível: ambos os estágios retornaram código 2 e `blocked` nos 40 casos
de desenvolvimento. As métricas são `null`; zero respostas foram inventadas e os
80 casos reservados não foram executados. Checkpoints/digests de geração e OCR não
puderam ser confirmados. É necessário disponibilizar o serviço e os modelos
configurados e então executar novamente em novos arquivos de resultados.

As 40 páginas são uma proposta de amostra, não gold humano concluído. Os 120 casos
têm expectativas propostas e localizadores existentes; relevância semântica,
respostas esperadas completas e adequação dos casos ambíguos exigem revisão.
Diálogos usam histórico controlado de perguntas, sem respostas normativas fabricadas;
rodadas encadeadas com respostas reais continuam pendentes.

## Critérios para iniciar a reconstrução da ingestão

1. Aprovação do usuário para alterar produção, mantendo esta baseline preservada.
2. Originais e captura identificados por hash, com cobertura das 177 páginas e
   rastreabilidade das 531 extrações, inclusive flags e variantes ativas.
3. Suíte anterior sem regressões e falhas conhecidas reproduzidas separadamente.
4. Testes de correção e banco PostgreSQL isolado para mudanças de persistência;
   nenhuma migração ou escrita experimental no banco atual.
5. Revisar o protocolo/amostra com responsáveis humanos antes de decidir o melhor
   extrator ou anunciar ganhos. Toda omissão crítica deverá ter tratamento explícito.
6. Resolver/registrar limitações dos gates de engenharia e completar execuções
   experimentais bloqueadas antes de declarar qualidade validada.

Correções determinísticas podem começar após autorização e isolamento, mantendo
Red–Green–Refactor. Escolhas de extrator/modelo/ranking aguardam evidência comparativa.

## Sequência recomendada após autorização

1. F2: identidade de versões e invalidação de avaliação/derivados, com reversão.
2. F1: critérios de promoção e reconciliação explícita do legado, sem apagar histórico.
3. F5: identidade normativa, edição/vigência e consistência de metadados.
4. F3/F4: validar extração/fallback e calibrar avaliação contra referências humanas.
5. F6: corrigir perda de contexto preservando a unidade de indexação por página.
6. F10/F11: pós-condição central de fundamentação, com testes de falsa recusa.
7. F12/F13: proveniência por turno e fronteira HTTP; priorizar F13 antes de exposição externa.
8. Contratos entre canais, observabilidade e orçamento global de contexto.
9. Ablações de recuperação/expansão e refinamento de prompts, um fator por vez.

Separar responsabilidades do módulo de pipeline somente com os contratos protegidos.
Não há justificativa nesta fase para trocar banco, framework, modelo ou estratégia
de indexação. Nenhuma correção definitiva foi aplicada.
