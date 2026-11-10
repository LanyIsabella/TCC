# Verificação de qualidade — Fase 4.1

Não há declaração de aprovação integral dos gates globais. Os resultados abaixo
separam o escopo alterado, a dívida anterior e verificações incompletas.

## Fonte e ambiente

[Hashes/escopo](artifacts/quality_workspace_verified.json) identificam a cópia
privada usada. Ela contém fontes, testes, configurações necessárias e dados
sintéticos, sem `.env`, credenciais ou corpus. Nenhuma mutação foi aplicada nos
fontes de trabalho. A comparação posterior confirmou bytes iguais ao workspace.
As ferramentas usam o Python 3.12 isolado já instalado, enquanto os testes usam
o `.venv` existente. Não houve instalação ou mudança de configuração global.

Foi usado somente um LCOV atual, evitando sobreposição por resultados antigos
no loader. O prazo manual é explícito e os workers de mutação são limitados a 2.
As fixtures de integração vedam chamadas de rede e construção de motores OCR.

## Crapper e Dryer

As 24 funções novas/alteradas ficaram abaixo de CRAP 10, máximo 9,0021:
[detalhamento](artifacts/quality_scope_verified.json),
[log](artifacts/crapper_verified.log), [status](artifacts/crapper_verified_status.json).
O gate de arquivo inteiro continua reprovado por rotinas preexistentes fora do
escopo. A lista das funções antigas preservadas por AST está no detalhamento.

Dryer identificou a dupla de consultas de status preexistentes com similaridade
0,93: [log](artifacts/dryer.log), [EDN](artifacts/dryer.edn).
Não foi encontrada necessidade de modificar essas consultas para corrigir F2;
não se afirma ausência de duplicação em todo o repositório.

Ruff passou, e `git diff --check` não acusou erro de whitespace. Os avisos Git de
LF→CRLF são do `core.autocrlf` existente; corpus e snapshots não foram normalizados.
Cobertura da regressão: módulo novo 100%/115 statements, pipeline completo 65%,
agregado dos dois 69%. Cobertura de statements não garante cobertura dos
operadores, defaults ou condições continuadas que o Mutator identifica.

## Mutator

Comando-base: `mutator --use-existing-coverage --mutate-all --max-workers 2`,
testando `tests/test_extraction_provenance.py` e
`tests/integration/test_postgres_provenance.py` por pytest no `.venv` do projeto.
Somente as funções alteradas do pipeline entram no segundo escopo; rotinas antigas
de OCR/embeddings/recuperação não foram artificialmente incluídas como corrigidas.

O primeiro escopo foi `data/extraction_provenance.py`, 37 sites:
[scan](artifacts/mutator_provenance_scan.log),
[execução](artifacts/mutator_provenance.log),
[status](artifacts/mutator_provenance_status.json).
Resultado inicial: 28 killed, 1 survived, 8 uncovered (exit 3, sem timeout).
Os 8 sites marcados uncovered pelo mapeamento de LCOV foram executados no suplemento
com `--no-coverage --lines 22,23,25,159,190,239,240,298`, mantendo todos os testes.
Esse suplemento amplia a execução; não reduz limiar nem torna o teste permissivo.

O sobrevivente inicial troca `delete=False` por `True` na reserva de arquivo
temporário. Os testes observam o snapshot final, e a abertura seguinte recria o
arquivo nessa plataforma; não distinguem a duração da reserva do nome entre
fechamento e reabertura. É uma limitação da análise, não prova de equivalência
universal nem motivo para enfraquecer o manejo dos temporários.

O suplemento terminou com **35 killed, 2 survived, 0 uncovered / 37 sites**, exit 3:
[log](artifacts/mutator_provenance_supplement.log),
[status](artifacts/mutator_provenance_supplement_status.json).
O resumo incorpora os 29 resultados anteriores inalterados; o suplemento executou
8 sites novos, dos quais 7 foram eliminados. Não são 37 novos testes de mutação.
O segundo sobrevivente troca o default `force=False` de `invalidate_evaluations`.
O pipeline e as integrações sempre passam esse argumento explicitamente; o
comportamento da chamada omitindo-o não é coberto. Isso permanece uma lacuna do
helper, sem evidência de regressão no fluxo exercitado, e o gate não é aprovado.

O [scan do pipeline](artifacts/mutator_pipeline_scan.log) selecionou 45 sites nas
11 funções alteradas. A execução usa `--no-coverage --lines <linhas dessas funções>`
para incluir inclusive o default não marcado pelo LCOV, com orçamento de 900 s e
dois workers. A execução encerrou com **exit 1**, `PermissionError: WinError 32`
ao tentar remover `worker-0` na limpeza interna da ferramenta:
[log](artifacts/mutator_pipeline.log), [status](artifacts/mutator_pipeline_status.json).
Não foi publicado um resumo confiável de resultados. Os 45 sites selecionados
permanecem **sem contagem validada de killed/survived**; não se afirma que todos
foram executados nem que nenhum foi executado. Contadores intermediários e a
ausência de EDN final não substituem esse resultado.

Foi encontrado um servidor PostgreSQL sintético restante. Antes de pará-lo,
foram conferidos caminho absoluto sob Temp, marcador, role/host de teste e
identificador físico distinto do original. Ele foi parado com `pg_ctl`; nenhum
cluster de teste ficou com pidfile ativo. O serviço PostgreSQL original continuou
Running e os fontes originais/private principais mantiveram seus hashes:
[registro](artifacts/mutation_cleanup.json). Não se apagou recursivamente a árvore
parcial de workers nem se alterou o tooling global. Essa falha nova da execução
manual fica pendente, além das ressalvas preexistentes do Stop hook.

## Stop hook preexistente

Foi lido o relatório solicitado em
`~/.codex/tooling/projects/6f7ccb0801228aee/ub-mode/6d55bcec9bbdadbe6d16/report.json`
e os logs Crapper/Dryer/Mutator referenciados. `ok=false`, Crapper exit 2 e Mutator
exit 124. A cobertura automática falhou e o prazo compartilhado expirou.
O resumo 75 killed/160 uncovered nesse relatório não comprova a execução dos 235
sites nem transforma timeout em kill. Seus arquivos de agente são anteriores e
ficaram intactos nesta fase. Os relatórios manuais atuais não substituem nem
reescrevem a pendência desse hook.

As limitações incluem coverage ausente no Python 3.13 do projeto, loader que pode
sobrescrever LCOV atual com antigo e orçamento automático de 50 s. Foram contornadas
na execução manual por ferramentas instaladas/cópia privada/LCOV único, sem alegar
correção do tooling global. SQL não é mutado por esta ferramenta Python; os testes
PostgreSQL reais são evidência de cenários, não demonstração formal de integridade
em todos os estados possíveis.

## Verificação complementar de encerramento

Após o relatório acima, foi executado um suplemento dirigido, sem alteração do
Stop hook global. O contrato omitido de `invalidate_evaluations(force=False)` foi
testado deterministicamente: a mutação `False → True` foi morta. A mutação
`delete=False → True` sobre o temporário do snapshot sobreviveu em Windows; os
testes não observam a janela de reserva do nome entre o fechamento e a reabertura,
e não houve defeito funcional reproduzido. O código de produção permaneceu
inalterado.

Os 45 pontos selecionados de `rag_pipeline.py` foram executados em grupos menores,
com workspace fora do OneDrive: **27 killed, 18 survived, 0 uncovered**. O gate
continua pendente; os sobreviventes não foram convertidos em correções especulativas.
O detalhamento e os testes por grupo estão em
[`pipeline_mutation_groups.json`](artifacts/pipeline_mutation_groups.json) e no
parecer [complementar](PARECER_COMPLEMENTAR.md).

Os resultados complementares foram **21 testes unitários**, **43 testes PostgreSQL
isolados** e a suíte completa com **359 passed, 1 skipped e 5 xfailed**. Esses
resultados demonstram os cenários exercitados, mas não aprovam os gates globais
ub-mode nem comprovam fidelidade factual de OCR/LLM.

## Stop atualizado após a entrega

O relatório de **2026-11-10 20:14:29 UTC** foi lido integralmente, junto com os
três logs: [registro e hashes](artifacts/stop_latest_review.json). Ele continua
com `ok=false`. Crapper saiu com 2: `No module named 'coverage'` no Python do
projeto, seguido de resultados globais acima do limiar. As 24 funções alteradas
da Fase 4.1 continuam com máximo 9,0021; isso não aprova o gate global.

Dryer saiu com 0, porém `ok=false`, pelos candidatos preexistentes de schema,
normalização de mensagens e consultas de status. Essas rotinas não foram
refatoradas fora do escopo. Mutator saiu agora com **2**, não 124: o relatório
registra expiração do prazo compartilhado e baseline inválida para a ferramenta,
embora a saída capturada do pytest mostre 355 passed, 1 skipped e 5 xfailed em
46,67 s. Essa saída não demonstra conclusão da mutação. Os contadores 75/0/160
persistidos não foram tratados como resultados novos ou completos.

O manifesto anterior foi conferido sem divergências e o hook marcou
`source_preserved=true`. Esta revisão altera somente documentação/evidência;
não reinstala coverage, modifica hooks nem reabre refatorações de agente,
recuperação ou embeddings. Permanecem as ressalvas manuais descritas acima.
