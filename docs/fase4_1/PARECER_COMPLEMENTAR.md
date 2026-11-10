# Parecer complementar — encerramento técnico da Fase 4.1

## Conclusão

A verificação complementar não encontrou defeito novo comprovado na persistência
ou no snapshot original. Foi corrigida uma lacuna objetiva de teste: o contrato
explícito de `invalidate_evaluations(force=False)` agora é exercitado e mata a
mutação `False → True`. Nenhum código de produção foi alterado nesta etapa.

A recomendação é encerrar tecnicamente a Fase 4.1 **com ressalvas documentadas**.
A implementação F2 continua apta para revisão humana e decisão posterior de
implantação. Não é recomendável declarar aprovação integral dos gates ub-mode ou
iniciar a Fase 4.2 antes de revisar os sobreviventes de mutação e as limitações
abaixo.

## Resultados executados

- Testes unitários complementares: **21 passed**, incluindo concorrência entre
  processos, cópia interrompida, alteração do RAW durante a cópia, publicação
  deduplicada, destino corrompido e o default `force=False`.
  [JUnit](artifacts/complementary_unit_green.xml).
- Integração PostgreSQL isolada: **43 passed em 35,79 s**.
  [JUnit](artifacts/complementary_pg_green.xml).
- Suíte completa após os testes novos: **359 passed, 1 skipped, 5 xfailed**.
  O skip é o teste externo GEDWeb; os cinco xfail estritos continuam sendo os
  contratos conhecidos de F1/F6.
  [JUnit](artifacts/complementary_full_green.xml).
- Ruff e `git diff --check`: aprovados.

Nenhuma correção de produção foi necessária. O único arquivo de comportamento
alterado nesta verificação foi o teste
[`test_extraction_provenance.py`](../../tests/test_extraction_provenance.py).

## Snapshot original

`original_snapshot()` foi revisado nas dimensões solicitadas:

- quatro processos independentes publicando os mesmos bytes deixam um único PDF
  válido, com o mesmo digest e sem `.tmp` residual;
- falha durante `copyfileobj` remove o temporário próprio;
- se o RAW muda depois de os bytes serem lidos, o snapshot permanece consistente
  com os bytes copiados e seu digest, enquanto o caminho RAW pode já apontar para
  outra versão;
- versões anteriores continuam preservadas por nome SHA-256;
- destino existente idêntico é reutilizado; destino existente corrompido gera
  `ValueError` e não é sobrescrito;
- `rename()` permanece a publicação final atômica, com corrida equivalente coberta
  por teste e por processos separados.

Os casos estão no arquivo unitário complementar e foram executados de fato.
Não foi implementado lock ou cópia transacional do arquivo RAW. A função não pode
detectar uma edição arbitrária no meio da leitura apenas comparando o caminho; a
garantia entregue é a identidade dos bytes efetivamente copiados. O pipeline
captura o snapshot antes de preparar as páginas e usa a mesma cópia para ambos.

## Mutantes sobreviventes

O default `force=False` recebeu teste determinístico que inspeciona o parâmetro
SQL enviado quando o argumento é omitido. Em workspace local, a mutação foi morta:
[log](artifacts/mutator_force_default.log),
[status](artifacts/mutator_force_default_status.json).

A mutação `delete=False → True` também foi executada em cópia temporária. Os 21
testes passaram sob Windows porque `NamedTemporaryFile(delete=True)` remove o nome
ao sair do contexto, e `temporary.open("wb")` recria o arquivo antes da cópia.
Assim, não houve falha observável nos contratos atuais. O resultado é uma lacuna
de reserva contra interposição entre a remoção e a reabertura do nome, não um
defeito funcional reproduzido. `delete=False` foi mantido para conservar a reserva
do nome temporário até a escrita; não foi alterado para satisfazer o Mutator.
[Log](artifacts/mutator_snapshot_delete_false.log).

## Mutação do pipeline

Os 45 pontos selecionados foram executados em grupos menores, com um worker,
`--no-coverage`, PostgreSQL sintético e workspace fora do OneDrive:
`C:\Users\lany_\AppData\Local\Temp\tcc-f41-pipeline-groups-1996cd5077fd434db506da0ef9c06533`.
O resultado consolidado está em
[pipeline_mutation_groups.json](artifacts/pipeline_mutation_groups.json).

| Escopo | Sites | Mortos | Sobreviventes |
|---|---:|---:|---:|
| Identidade/lease de página | 7 | 7 | 0 |
| Processamento de página | 9 | 2 | 7 |
| Loop de retomada | 8 | 5 | 3 |
| Avaliação | 9 | 4 | 5 |
| Seleção/promoção Gold | 12 | 9 | 3 |
| **Total** | **45** | **27** | **18** |

Não houve sites uncovered nos grupos. Os 18 sobreviventes não foram transformados
em alterações especulativas: os testes escolhidos não distinguem todos os efeitos
de aritmética, condições de fronteira e caminhos de erro. O gate de mutação fica
pendente; esse resultado não é uma aprovação da qualidade global.

A execução anterior do Stop hook que falhou por `WinError 32` permanece registrada
em [QUALITY.md](QUALITY.md). Os grupos complementares conseguiram executar todos
os 45 pontos, mas confirmaram sobreviventes. Não foram alterados limiares, hooks
globais ou a ferramenta.

## PostgreSQL, migração e reversão

Os 43 testes isolados reconfirmaram invalidação de notas antigas, retomada
idempotente, nova execução por `force`, histórico append-only, rollback em falhas,
rejeição de avaliações tardias, migração explícita e recusa de downgrade destrutivo.
O cluster criado para cada sessão usa diretório e identificador próprios; todos os
58 recibos acumulados estão parados, sem pidfile ativo. O serviço original
`postgresql-x64-18` permaneceu em execução.

O `up` não foi aplicado no banco produtivo. O `down` continua recusando apagar
histórico usado; depois de uso, a reversão é restauração de backup pré-migração em
outro banco, mantendo o arquivo versionado.

## Integridade dos dados originais

Uma nova transação `REPEATABLE READ READ ONLY` confirmou novamente o mesmo cluster,
as mesmas contagens e os mesmos SHA-256 das seis tabelas, incluindo vetores:
[production_recheck.json](artifacts/production_recheck.json).
O manifesto da entrega e os hashes dos fontes permanecem válidos. Não houve escrita
no banco produtivo, alteração de PDF, Gold ativa, embeddings, RRF, agente ou UI.
Os arquivos acrescentados ou alterados neste suplemento têm hashes em
[complementary_manifest.json](artifacts/complementary_manifest.json); o manifesto
anterior permanece preservado como referência da baseline.

## Lacunas e recomendação

Persistem as limitações já conhecidas: os dados sintéticos não comprovam fidelidade
de OCR nem factualidade do LLM; configurações históricas ausentes continuam
`unknown`; a análise de mutação SQL não é coberta pelo Mutator Python; a cobertura
global e os gates automáticos ainda têm pendências de ambiente/LCOV; e a proteção
contra administrador que desabilite DDL não é garantida por triggers.

Recomendo registrar a Fase 4.1 como tecnicamente concluída para revisão, com os
18 sobreviventes e as ressalvas de qualidade anexados ao parecer. A próxima ação,
se aprovada separadamente, é revisão humana e decisão de implantação/migração.
Não iniciar a Fase 4.2 automaticamente.
