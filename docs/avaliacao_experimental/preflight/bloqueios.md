# Bloqueios e ressalvas

## Não bloqueiam a execução operacional

- Ollama e os dois modelos requeridos estão disponíveis.
- PostgreSQL aceita leitura repetível e somente leitura.
- O índice Gold possui documentos e páginas recuperáveis.

## Bloqueiam conclusões específicas

- A ausência de revisão humana impede afirmar correção factual, suporte por
  afirmação, CER/WER calibrados, Recall/MRR/nDCG ou promoção Gold.
- Casos sem referências documentais não podem receber pontuação factual por
  referência.
- A tabela `silver.page_extraction_selections` não está instalada; análises que
  dependam dessa seleção devem permanecer pendentes.

O estado anterior `ollama_unavailable` dos artefatos congelados não foi
reescrito. Este preflight é uma observação nova, separada dos resultados
históricos.
