# Testes mínimos de funcionamento

Os testes abaixo não são o benchmark; foram executados uma vez apenas para
confirmar conectividade e o caminho de leitura.

| Teste | Resultado |
|---|---|
| Ollama `/api/version` e `/api/tags` | passou; servidor 0.30.11 e modelos presentes |
| `POST /api/embed` com entrada sintética | passou; vetor com 768 dimensões |
| `POST /api/chat` com `gemma4:e2b` | passou; resposta curta de 2 caracteres |
| PostgreSQL | passou; transação `READ ONLY`, PostgreSQL 18.0 |
| Recuperação conhecida | passou; caso `specific_10520_01`, status `success`, evidência encontrada, 1 documento e 2 traces |

Na recuperação conhecida, `document_locator_coverage` e
`page_locator_coverage` foram 1.0; `factual_correctness` permanece `null`
porque a referência humana está pendente.
