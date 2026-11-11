# Inventário dos conjuntos experimentais

## Referências documentais

| Artefato | Quantidade | Significado | Estado |
|---|---:|---|---|
| `rag_eval/baseline/artifacts/initial_state.json` | 177 páginas / 531 extrações | Snapshot estrutural do corpus, Gold e extrações existentes | Preservado; não é transcrição humana |
| `rag_eval/baseline/artifacts/human_reference.json` | 40 páginas | Seleção preliminar para revisão humana: três páginas por norma (início/meio/fim) mais páginas de risco/estrutura | `pending_human_review`; nenhuma transcrição preenchida |
| `rag_eval/baseline/human_review/lote_2026-11-10/reviews.json` | 12 páginas | Lote documental solicitado para comparação visual dos três extratores | `pending_human_review`; campos humanos vazios |
| `rag_eval/baseline/artifacts/all_pages_review.json` | 177 páginas | Formulário vazio para eventual revisão de todo o corpus | `pending_human_review` |
| `rag_eval/baseline/artifacts/extraction_evaluation.json` | 531 linhas | Avaliação derivada das extrações usando referências humanas declaradas | `experimental_validation_complete=false`; CER/WER permanecem nulos sem revisão |

Os 40 itens de `human_reference.json` não são “40 respostas” nem o lote de 12
páginas. São uma seleção preliminar de páginas físicas para anotação humana.
O lote de 12 contém exatamente as páginas do pacote documental da revisão e
preserva os mesmos hashes do snapshot. Saídas `pdf_reader`, `docling` e
`glm_ocr` são três registros independentes por página; nenhuma delas é uma
transcrição humana ou ground truth.

## Consultas da aplicação

`rag_eval/baseline/queries.json` contém **120 perguntas propostas**:

- **40 `development`**: seis específicas para cada uma das dez normas,
  complementadas por perguntas amplas, conversacionais, negativas e ambíguas;
- **80 `reserved`**: holdout reservado, não utilizado para ajustes ou nesta
  preparação.

Os arquivos `retrieval_development.json` e `agent_development.json` contêm os
mesmos 40 IDs do split de desenvolvimento, em estágios separados. Eles não
representam as 40 páginas de revisão humana.

## Estado observado dos 40 casos

| Estágio | Casos | Estado | Motivo | Métricas |
|---|---:|---|---|---|
| retrieval | 40 | `blocked` | `readiness.ready=false`, `reason=ollama_unavailable` | `null` |
| agent | 40 | `blocked` | `readiness.ready=false`, `reason=ollama_unavailable` | `null` |

O bloqueio é de serviço/configuração: o preflight não conseguiu consultar
`OLLAMA_HOST/api/tags` e, portanto, não confirmou `gemma4:e2b` e
`nomic-embed-text`. Não é falta de perguntas nem falta de transcrições para
executar a chamada, embora a ausência de referências humanas impeça pontuar
correção factual mesmo depois que o serviço esteja disponível.

Assim, há três estados diferentes:

1. **Bloqueio real de execução:** Ollama indisponível nos dois estágios;
2. **Métrica não calculável por método:** correção factual, suporte por
   afirmação e Recall/MRR/nDCG exigem referências revisadas;
3. **Holdout preservado:** os 80 casos `reserved` não foram executados.

