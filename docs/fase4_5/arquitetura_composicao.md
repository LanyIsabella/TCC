# Arquitetura da composição

`_compact_document()` continua sendo o único ponto de composição pós-
recuperação. A página permanece a unidade natural de recuperação; a função
apenas escolhe uma janela contígua dentro da página para o contexto do agente.

Cada janela é formada por unidades delimitadas por parágrafo, quebra de linha
ou fim de sentença. A unidade que contém o primeiro match textual da pergunta
é selecionada e unidades vizinhas são adicionadas somente quando o intervalo
contíguo cabe no limite. O texto nunca é reconstruído: `evidence["text"]` é um
recorte do texto persistido.

Páginas diferentes geram itens `evidence` diferentes e IDs estáveis
`document:<id>:page:<página>`. O payload também expõe `omitted_content` com
`characters` e `pages`, permitindo que uma camada superior saiba que a fonte
foi reduzida.

Esse campo é propagado por `src/app/evidence.py` até os registros usados pelo
grounding. Quando uma afirmação normativa depende de uma evidência que possui
conteúdo omitido, `src/app/grounding.py` preserva a afirmação sustentada, mas
classifica a resposta como parcial e acrescenta a limitação documental.

Quando o texto integral cabe, ele continua sendo usado. Quando não cabe, o
fallback usa `page_context` já recuperado ou separa marcadores de página
existentes; não há chunking fixo, reindexação ou mudança da recuperação.
