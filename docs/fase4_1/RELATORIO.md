# Fase 4.1 — integridade, proveniência e versionamento

Entrega de F2 para revisão humana, sem migração produtiva. Base: commit local da
Fase 3 `27551cef7d033061dc740f455a3c28f5b3966f22`; branch
`fix/fase4-1-proveniencia-ingestao-20261110`. As alterações desta subfase ainda
não foram commitadas. Não foi iniciada a Fase 4.2.

## Resultado e preservação

Os quatro contratos F2 passaram com PostgreSQL real isolado. A regressão registrou
**355 passed, 1 skipped, 5 xfailed** em 50,71 s:
[log](artifacts/full_verified.log), [JUnit](artifacts/full_verified.xml).
Os cinco xfail estritos restantes são F1 (3) e F6 (2). O skip é o acesso externo
GEDWeb, desabilitado por configuração; nenhuma integração PostgreSQL foi ignorada.
Os seis contratos F10–F13 passaram, incluídos na regressão e também
[executados separadamente](artifacts/agent_contracts_green.xml).

As seis tabelas originais, inclusive valores dos vetores, colunas e restrições,
permaneceram iguais nas capturas somente leitura:
[antes](artifacts/production_before.json), [depois](artifacts/production_after.json).
Foram preservados os 301 arquivos do corpus e artefatos congelados das fases
anteriores, incluindo baseline, revisão humana e evidências da Fase 3:
[auditoria de preservação](artifacts/preservation.json).

Não houve OCR real, ingestão dos dez PDFs, geração de embeddings, uso dos 80 casos
reservados para ajuste, alteração da UI/agente/RRF ou instalação de dependências.
Implementações e parâmetros reais dos extratores e avaliador foram preservados.
As fixtures usam resultados sintéticos e bloqueiam rede e motores OCR; os testes
exercitam SQL, transações, locks, triggers, vetores, backup e restauração reais.

## Diagnóstico e arquitetura

Antes, a chave `(document_id, extractor, extractor_version)` não distinguia PDF
alterado, parâmetros ou modelo. `force` reutilizava a execução, substituindo o
texto e conservando nota/status. A avaliação ignorava esse texto já marcado como
avaliado. Faltava uma cadeia explícita entre resultado, avaliação e derivado.
O cache de páginas já usava SHA-256 truncado a 16 caracteres e foi preservado;
o defeito estava na identidade persistida e na falta de vínculo com os bytes
efetivamente processados.

As camadas existentes foram mantidas. O novo
[`extraction_provenance.py`](../../data/extraction_provenance.py) concentra identidade,
snapshot e persistência versionada. Os pontos de processamento, avaliação e
promoção do [`rag_pipeline.py`](../../data/rag_pipeline.py) o utilizam.

| Identidade | Composição e registro |
|---|---|
| Original | SHA-256 completo dos bytes da cópia imutável, nome `<sha256>.pdf`, número de páginas físicas e referência Bronze |
| Insumos | Original + páginas + extrator/versão/receita + configuração tipada, modelo/digest observado e parâmetros efetivos aplicáveis |
| Execução | UUID independente dos insumos; cada `force` cria uma execução distinta |
| Resultado | Execução + insumos + página física + texto, Markdown e saída estruturada; hash textual também preservado |
| Avaliação | UUID da solicitação/avaliação + resultado-alvo + mecanismo/receita/versão/modelo/digest/configuração |
| Derivados | Gold: execução, insumos, hash integral e mapa página→resultado; eventos ligam publicação às avaliações utilizadas. Índice: resultado, texto/modelo/dimensão/digest e hash do texto embutido |

O perfil registra implementação e dependências aplicáveis. YAML é configuração
tipada; o hash bruto é observação, excluída da identidade para que formatação
cosmética não crie outra versão. Digest de modelo é validado como SHA-256 e
observado no ambiente ou `/api/tags`; ausente/inválido permanece desconhecido.

Fingerprints Python são SHA-256 do UTF-8 de
`json.dumps({"scheme": scheme, "value": value}, ensure_ascii=False,
sort_keys=True, separators=(",", ":"), allow_nan=False)`.
Domínios: `extraction-input-v1`, `evaluation-config-v1`, `gold-derivation-v1`.
Não há normalização do texto/Unicode/quebras. Vetor de referência:
`fingerprint("v1", "ação\n")` =
`7c6385edfa2cf7f947506207b5baff27bc1eac5e9a36f7b6dd2646ca81dfff1b`.

SQL usa SHA-256 do UTF-8 de `jsonb_build_object(...)::text`, domínios
`page-result-v1` e `embedding-derivation-v1`, conforme a migração. Essa é a
convenção JSONB do PostgreSQL 18 testado, diferente da serialização Python.
Consumidores devem reproduzir o algoritmo correspondente e versionar mudanças
de convenção; os dois algoritmos não são intercambiáveis.

## Reprocessamento, invalidação e recuperação

1. Insumos equivalentes e verificáveis retomam a execução; `force` cria outra.
   PDF/versão/configuração/modelo/digest diferente muda os insumos. Digest OCR
   desconhecido não autoriza reutilização automática.
2. A origem é copiada antes de preparar páginas. Páginas e identidade usam essa
   mesma cópia mesmo se RAW mudar durante o trabalho. Snapshot com hash incorreto
   provoca erro e é preservado para diagnóstico.
3. Execução e todas as páginas são criadas atomicamente. Lock transacional por
   documento/extrator serializa criações; lock de sessão por página e releitura do
   status impedem processamento simultâneo da mesma página. A retomada conserva
   páginas concluídas e reprocessa apenas as elegíveis.
4. Mudar resultado limpa a projeção da avaliação. Triggers acrescentam snapshots
   completos a histórico sem UPDATE/DELETE. Notas antigas continuam rastreáveis.
5. Avaliação reserva UUID e publica comparando resultado e solicitação vigentes.
   Trabalho selecionado antes da mudança pode ser descartado antes da inferência;
   resposta tardia vira evento histórico e não aprova o resultado/configuração atual.
6. Reavaliação usa a última execução de cada extrator; mudar configuração invalida
   sua projeção. Digest desconhecido do avaliador exige reavaliação em cada
   invocação explícita e não autoriza promoção normal como contexto verificável.
7. Gold e proveniência são gravadas em transação única. Falha não deixa troca
   parcial. Resultado alterado de uma execução já publicada exige outra execução
   para não sobrescrever o derivado imutável. Execução nova incompleta não
   substitui a Gold ativa anterior.
8. `activate_gold(..., extraction_id=...)` permite escolher execução anterior,
   preservando versões e vetores. A CLI continua sem novo parâmetro. O teste usa
   conexão explicitamente isolada; a operação não foi feita no banco original.

`is_gold_ready` e `comparison_is_ready` não foram alteradas. A comparação considera
execuções atuais ou a versão anterior explicitamente selecionada. Os novos
critérios qualitativos F1/Fase 4.2 não foram implementados.

## Schema, compatibilidade e reversão

Migração explícita [up](../../data/migrations/0001_extraction_provenance.up.sql) e
[down](../../data/migrations/0001_extraction_provenance.down.sql), aplicada somente
em bancos sintéticos. `data/rag_schema.sql` ficou intacto. O runtime novo exige
a migração com erro orientativo; não altera schema legado automaticamente.

| Camada | Efeito |
|---|---|
| Bronze/RAW | Tabelas/dados intactos; snapshot prospectivo conserva bytes da versão |
| Silver execução | UUID/fingerprint/JSON; retirada da antiga chave tripla; índice por insumos |
| Silver página | Resultado/alvo/configuração e IDs de avaliação/solicitação; triggers de vínculo/invalidação |
| Histórico | `silver.page_extraction_history`, append-only, evento e snapshot JSONB |
| Gold | `gold.document_derivations` imutável e eventos das avaliações usadas na publicação |
| Índice | Views de obsolescência/proveniência e compatibilidade embedding/texto; nenhum vetor refeito |

A importação legada mantém IDs, textos, notas e metadados; marca configurações
não registradas como `historical_configuration=unknown`, sem fingerprint de
insumos. UUIDs atribuídos na migração são referências novas, não IDs originais
de jobs recuperados. Conteúdo sobrescrito anteriormente continua irrecuperável.
Reaplicação da migração e preservação dos campos legados foram testadas.

Para implantação futura autorizada: verificar destino/cluster, produzir `pg_dump`
anterior e backup dos originais, testar restauração em outro banco e aplicar `up`
explicitamente. Runtime antigo não deve ser executado supondo a antiga chave única.

O `down` só admite reversão antes de trabalho versionado novo. Após uso, recusa
apagar histórico. A reversão operacional passa a restaurar o backup pré-migração
**em outro banco**, manter o banco versionado como arquivo e selecionar o destino
restaurado numa implantação revisada. `pg_dump`/`pg_restore` reais foram testados
em dois bancos isolados, preservando o arquivo novo. Não se promete downgrade
destrutivo de histórico utilizado.

`PAGE_CACHE/originals` é agora um **arquivo durável de versões de origem**, apesar
do nome do pai. Excluir esse subdiretório da limpeza de cache de páginas/imagens e
incluí-lo no backup junto com RAW e PostgreSQL. Só foram criadas cópias sintéticas
nesta entrega. Referência no banco não substitui backup dos bytes. Views sinalizam
derivados obsoletos sem desativar ou recalcular Gold/vetores; recuperação intacta.

## Evidências Red–Green–Refactor

| Comportamento | Red real | Green posterior |
|---|---|---|
| Contratos F2 originais | [4 falhas antes da implementação](artifacts/f2_baseline_red.xml), sem xfail | [4 aprovados em PG](artifacts/f2_contracts_current_green.xml) |
| Mesmo defeito em PG real | [4 falhas](artifacts/postgres_red.xml) | [4 aprovados](artifacts/postgres_core_green.xml) |
| Repetição/histórico/falha/concorrência | [4 falhas/17](artifacts/postgres_edges_red.xml) | [17 aprovados](artifacts/postgres_edges_green.xml) |
| Insumos/configuração desconhecida/hash | [5 falhas/26](artifacts/postgres_identity_edges_red.xml) | [26 aprovados](artifacts/postgres_identity_edges_green.xml) |
| Hash persistido | [1 falha/22](artifacts/postgres_persistence_red.xml) | Incluído na regressão atual |
| Promoção/comparação de versões | [1 falha/28](artifacts/postgres_promotion_red.xml) | [28 aprovados](artifacts/postgres_promotion_green.xml) |
| Avaliação antiga sobre configuração nova | [1 falha](artifacts/evaluation_race_red.xml) | [29 aprovados](artifacts/postgres_concurrency_green.xml) |
| Legado/Gold obsoleta antes do resumo | [2 falhas](artifacts/lineage_legacy_red.xml) | [31 aprovados](artifacts/postgres_lineage_green.xml) |
| Avaliações utilizadas na publicação | [1 falha](artifacts/assessment_lineage_red.xml) | [1 aprovado](artifacts/assessment_lineage_green.xml) |
| RAW muda durante preparo | [1 falha](artifacts/original_snapshot_red.xml) | [3 aprovados](artifacts/original_snapshot_green.xml) |
| Validação/estabilidade de identidade | [5 falhas/11](artifacts/fingerprints_red.xml) | [11 aprovados](artifacts/fingerprints_green.xml); [17 unitários atuais](artifacts/unit_final.xml) |

Refatoração separou processamento de página, reserva/publicação e seleção Gold.
AST das funções antigas de OCR/avaliação/embeddings/RRF/cache/`main` foi comparada
com a Fase 3 e preservada: [escopo e hashes](artifacts/quality_scope_verified.json).
Somente três decorators F2 (quatro casos) foram retirados após Green. F1/F6
permanecem estritos. Caracterizações inseguras viraram regressões de preservação
da execução anterior e ausência de nota herdada.

Erros iniciais de infraestrutura foram mantidos: quatro erros por pipes herdados
pelo `pg_ctl` no Windows, resolvidos capturando saída em arquivo temporário; uma
colisão de nomes na coleta, resolvida renomeando o arquivo de integração. Esses
registros (`postgres_infrastructure_failure`, `f2_contracts_first_green`,
`full_first_green`) não contam como Red funcional. Ajustou-se a fixture que tentava
gravar conteúdo e nota anterior na mesma mudança. O bootstrap preexistente de
`tests/conftest.py` foi restaurado antes da regressão final. Logs intermediários
não são somados como testes distintos nem substituem a execução final.

## Testes e ambiente isolado

A regressão inclui 43 casos no novo arquivo de integração PG, 17 unitários de
proveniência e 4 contratos F2 migrados para PG. Cobre todos os cenários solicitados,
incluindo falha/interrupção, concorrência, notas tardias, rollback e versões antigas.
O teste do índice usa vetor sintético 768, sem inferência de embedding.

Os binários PostgreSQL 18/pgvector já estavam instalados. A fixture cria outro
cluster no Temp (`tcc-f41-pg-*`), role `tcc_f41`, trust somente no loopback e porta
livre. Confere diretório físico e identificador do cluster, diferentes do original;
cada teste usa banco aleatório próprio. Não copia `.env`/credenciais produtivas.
Só esses bancos são removidos; o servidor próprio é parado ao terminar. Recibos:
[`postgres_runs`](artifacts/postgres_runs/). Dados temporários ficam fora do repo.

```powershell
$env:TCC_PG_BIN='C:\Program Files\PostgreSQL\18\bin'
$env:TCC_REQUIRE_PG='1'
$env:TCC_PG_REPORT_DIR='docs/fase4_1/artifacts/postgres_runs'
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
```

Cada sessão recria um cluster limpo. Para integração apenas, selecionar
`tests/integration`. `TCC_REQUIRE_PG=1` faz ausência dos binários falhar; skip não
é evidência PostgreSQL. GEDWeb exige opção própria e não foi habilitado.

Descarte posterior: obter basename exato do recibo, resolver caminho sob Temp e
conferir prefixo `tcc-f41-pg-` e pai exato. Ler `isolation.json`, conferir seu
identificador e que `data_directory` resolve para o filho `cluster`. Executar
`pg_ctl status` nesse destino; somente após confirmar servidor parado, remover
com PowerShell `Remove-Item -LiteralPath` no caminho absoluto verificado. Não
aplicar ao diretório do serviço original. Nenhum descarte recursivo foi executado.

## Qualidade, integridade e limitações

Ruff passou: [log](artifacts/ruff_verified.log). Cobertura: módulo novo 100% dos
115 statements, pipeline completo 65%, agregado dos dois 69%:
[log](artifacts/coverage_verified.log), [JSON](artifacts/coverage_verified.json).
Não é cobertura integral do repositório nem validação dos motores reais.

Com LCOV atual único e fontes em cópia privada, as 24 funções novas/alteradas têm
CRAP <10, máximo 9,0021: [escopo](artifacts/quality_scope_verified.json),
[Crapper](artifacts/crapper_verified.log). O gate de arquivo inteiro ainda falha
em rotinas antigas, preservadas por AST. Dryer apontou duplicação 0,93 entre duas
consultas de status antigas, sem alteração nesta fase: [log](artifacts/dryer.log).
Mutação e abrangência estão documentadas em [QUALITY.md](QUALITY.md).
No módulo novo, o Mutator contabilizou 35 killed e 2 survived de 37 sites. No
pipeline, os 45 sites selecionados ficaram sem resumo confiável porque a
ferramenta falhou na limpeza de worker com `WinError 32` (exit 1). Essa análise
permanece incompleta; não há aprovação integral dos gates. O cluster sintético
restante foi identificado e parado com verificação de isolamento, sem tocar o
serviço original. Os resultados funcionais anteriores não foram substituídos.

O Stop hook preexistente permanece incompleto: relatório
`~/.codex/tooling/projects/6f7ccb0801228aee/ub-mode/6d55bcec9bbdadbe6d16/report.json`
com `ok=false`, Crapper exit 2 e Mutator exit 124. O Python 3.13 do projeto não tem
coverage; ferramentas isoladas 3.12 têm. Há sobreposição de LCOV antigo no loader
e prazo compartilhado de 50 s, menor que a regressão. Não foram alterados hooks
globais nem instalados pacotes. Contadores persistidos após timeout não comprovam
execução completa e não foram classificados artificialmente como aprovação.

A comparação do banco usou transações somente leitura, hashes de linhas completas
ordenadas nas seis tabelas (incluindo vetores), schema e restrições. Confirmou
10 registros Bronze, 10 resumos Silver, 30 execuções, 531 páginas extraídas,
13 variantes Gold e 266 linhas de índice, sem mudança. Agente Fase 3 e schema
original continuam iguais. A evidência atesta o estado observado nesses momentos,
não impede alterações externas futuras.

Dados sintéticos não medem fidelidade OCR, qualidade factual do LLM ou desempenho
em carga. Digest observado não atesta checkpoint efetivamente servido por terceiros.
Histórico já perdido não é recuperável. Triggers não protegem contra administrador
que desabilite DDL. Backup dos bytes é necessário. As views são diagnósticas e
não modificam a seleção de evidências do agente. Mutator Python não cobre SQL.

## Arquivos e pendências

Produção: `data/rag_pipeline.py`, `data/extraction_provenance.py`, dois SQL em
`data/migrations`. Testes: `tests/conftest.py`,
`tests/baseline/test_defect_pipeline.py`, `tests/test_extraction_provenance.py`,
`tests/integration/test_postgres_provenance.py`. Documentação: `GLOSSARY.md` e este
diretório. Fontes/testes de produção F10–F13 ficaram intactos.

Pendente: revisão e decisão separada de implantação/migração, com backup e validação
no destino autorizado. F1/F3/F4/F5/F6 e Fase 4.2 ficam fora do escopo. Não houve
commit da Fase 4.1, push ou migração produtiva.
Também fica pendente a conclusão da mutação do pipeline e a revisão das duas
lacunas de mutação do helper; não foram escondidas como sucesso de ferramenta.

Impacto metodológico a levar ao TCC: o estado anterior identificado apenas por
versão do extrator passa a distinguir insumos, tentativa, resultado, avaliação e
derivado; `force` cria versão, em vez de sobrescrever a anterior. Essa mudança
deve constar da descrição de reprodutibilidade e do protocolo de novos experimentos.
Não foi alterada a monografia nem reinterpretada a baseline congelada como se
ela já tivesse esse histórico. Esta entrega não compara texto acadêmico e código
nem modifica o protocolo/resultados da revisão humana.

## Verificação complementar

O parecer final da verificação complementar da Fase 4.1 está em
[PARECER_COMPLEMENTAR.md](PARECER_COMPLEMENTAR.md). Ele registra os testes adicionais
do snapshot, a análise dos mutantes sobreviventes, a mutação agrupada do pipeline,
as reconfirmações PostgreSQL e as ressalvas para o encerramento técnico.
