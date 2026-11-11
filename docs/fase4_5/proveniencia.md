# Garantias de proveniência

- O texto de uma evidência é obtido diretamente de `page_text` ou de uma
  seção delimitada por marcador já armazenada em `full_text`.
- O código não pede ao LLM para reescrever ou completar citações.
- Cada evidência carrega `document_id`/`rag_document_id`, título, versão,
  página, origem e `evidence_id` estável.
- Páginas distintas nunca são concatenadas para formar um único item de
  evidência.
- `matched_text` é apenas um recorte auxiliar para localização; não é tratado
  como prova independente.
- `omitted_content` torna visível a redução do contexto, permitindo que a
  política de grounding não trate a ausência como cobertura completa. O campo
  é preservado no registro de evidência; se uma afirmação normativa for
  sustentada por uma evidência com omissões, a resposta recebe status parcial
  e a limitação padrão, em vez de ser publicada como completa.

Nenhum PDF, dado Gold, embedding, banco produtivo ou holdout foi alterado.
