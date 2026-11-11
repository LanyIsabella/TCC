# Parecer técnico F4.5

## Conclusão

O defeito F6 foi reproduzido e corrigido no ponto de composição das evidências.
A solução preserva páginas como unidade de recuperação, evita o truncamento
cego do prefixo, mantém a proveniência e registra omissões. A revisão final
também reproduziu o risco de uma condição omitida ser tratada como cobertura
completa; a correção propaga `omitted_content` ao grounding e transforma esse
caso em resposta parcial com limitação explícita. Os contratos F6 antes
`xfail(strict=True)` agora passam.

## Escopo e segurança

Foram alterados `src/app/tools/rag_search.py`, `src/app/evidence.py`,
`src/app/grounding.py`, os testes de evidência/grounding e a documentação.
Não houve alteração de OCR, ingestão, embeddings, RRF, Gold,
metadados normativos, UI, banco produtivo ou documentos originais. O holdout de
80 casos foi preservado.

## Limitações

O orçamento de 1.200 tokens é uma salvaguarda operacional baseada em estimador
lexical, não uma contagem exata do tokenizer do modelo. A relevância interna
da janela usa heurística textual e não substitui avaliação factual humana ou
experimental. Tabelas que atravessam páginas continuam sendo avaliadas por
página.

## Recomendação

Com base nos testes direcionados, integração de proveniência, regressão e lint,
a implementação está pronta para encerramento técnico da Fase 4.5, mantendo
as limitações acima registradas. Não foi criado commit automático.

O relatório global anterior do ub-mode permanece reprovado/incompleto (CRAP
acima do limiar, duplicações e mutações não executadas sob o orçamento
compartilhado). Ele cobre outros arquivos e não foi reexecutado nesta fase,
conforme solicitado; portanto este parecer não declara aprovação desses gates.
