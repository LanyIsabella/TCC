# Fase 4.1 — proveniência e versionamento da ingestão

Estado: entrega técnica para revisão. Veja o [relatório final](RELATORIO.md) e
os [resultados de qualidade](QUALITY.md) e o [parecer complementar](PARECER_COMPLEMENTAR.md).
O texto abaixo registra a preparação
e o plano executado, não uma lista de atividades ainda pendentes.

Base local: `27551cef7d033061dc740f455a3c28f5b3966f22`.
Branch: `fix/fase4-1-proveniencia-ingestao-20261110`.

## Preparação executada

Foram lidos AGENTS.md, o relatório da baseline, seu protocolo, a auditoria
materializada em `rag_eval/baseline/audit.py`, os contratos de defeitos e o parecer
de encerramento da Fase 3. Não foi localizado outro relatório autônomo da auditoria
inicial no repositório; os testemunhos F2 estão preservados na baseline.

Os hashes dos arquivos anteriores e a inspeção somente leitura do PostgreSQL
estão em `artifacts/before.json` e `artifacts/production_before.json`.
A captura do banco inclui fingerprints de todas as colunas, inclusive vetores,
para possibilitar uma comparação final sem exportar seus valores.

Antes da mudança, a suíte registrou 291 aprovações, 1 skip e 9 xfail. Os quatro
contratos F2 foram executados sem xfail para reproduzir o defeito original.

## Diagnóstico e plano incremental

A restrição antiga identifica a extração apenas por documento, extrator e versão.
`force` reutiliza esse registro, substitui o texto e conserva nota/status anteriores.
A avaliação só seleciona pendências/erros; por isso não reavalia o texto substituído.
O cache de páginas já contém um prefixo de SHA-256 do original e será preservado;
a identidade persistida da execução ainda precisa registrar o SHA-256 completo.

1. Estabelecer cluster PostgreSQL temporário independente; reproduzir os contratos
   com SQL real e dados sintéticos.
2. Separar o fingerprint dos insumos da identidade de cada execução. Repetição
   normal equivalente retoma a execução; `force` solicita outra execução preservando a anterior.
3. Acrescentar histórico imutável de resultados e avaliações, mantendo as colunas
   atuais como projeção compatível para os consumidores existentes.
4. Vincular avaliação ao resultado e à configuração efetiva; impedir publicação
   tardia de uma avaliação se o texto tiver mudado durante sua execução.
5. Identificar derivados obsoletos por proveniência, sem regenerar embeddings,
   mudar recuperação ou implementar critérios da Fase 4.2.
6. Verificar concorrência, retomada, rollback, migração/compatibilidade legada e
   restauração de versões. Reexecutar regressão e F10–F13; retirar apenas os xfail F2 corrigidos.

## Isolamento

`tests/conftest.py` usa os binários PostgreSQL 18 já instalados, inicia outro
cluster em diretório temporário, escolhe porta local livre, cria role de teste
sem senha e escuta somente em `127.0.0.1`. Nenhuma credencial do `.env` é copiada.
São conferidos diretório físico e identificador do cluster, distintos do original.
Cada teste recebe um banco vazio próprio; somente esses bancos são criados/removidos.
O cluster é parado ao encerrar a sessão. Logs e dados sintéticos ficam no diretório
temporário para diagnóstico, sem entrar no versionamento.

Execução obrigatória das integrações em PowerShell:

```powershell
$env:TCC_PG_BIN='C:\Program Files\PostgreSQL\18\bin'
$env:TCC_REQUIRE_PG='1'
.\.venv\Scripts\python.exe -B -m pytest tests/integration -q -p no:cacheprovider
```

Cada nova sessão recria um cluster limpo, sem reutilizar o banco produtivo.
Instruções de descarte verificado e reversão estão no relatório final.
Nenhuma migração foi aplicada no banco original. Fase 4.2 permanece fora do escopo.
