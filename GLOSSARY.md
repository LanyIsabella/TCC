# Consulta documental e ingestão do TCC

Vocabulário para distinguir fontes, processamento e evidências documentais.

## Linguagem

**Documento original**:
Sequência de bytes do PDF recebido. Uma alteração desses bytes constitui outra
identidade documental, ainda que nome e quantidade de páginas permaneçam iguais.
_Evitar_: Nome do arquivo como identidade.

**Execução de extração**:
Tentativa identificada de processar um documento com método e configuração
determinados. Retomar uma tentativa e solicitar outra execução são ações distintas.
_Evitar_: Confundir versão do extrator com execução.

**Resultado extraído**:
Conteúdo produzido para uma página física por uma execução de extração.
_Evitar_: Tratar o registro mutável da página como histórico completo.

**Avaliação documental**:
Julgamento identificado de um resultado extraído, sob um método e contexto
de avaliação determinados.
_Evitar_: Considerar uma nota isolada válida para qualquer versão do texto.

**Derivado documental**:
Texto ou representação construída a partir de resultados identificados, como
uma variante Gold ou seu índice. Sua origem pode deixar de corresponder à versão corrente.
_Evitar_: Confundir disponível com atualizado.

**Proveniência desconhecida**:
Informação histórica não registrada e que não pode ser recuperada com segurança.
_Evitar_: Preencher configurações antigas com valores observados atualmente.
