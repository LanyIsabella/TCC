# Decisões e limitações

- O orçamento operacional adotado é 5.000 caracteres e 1.200 tokens estimados
  para o conjunto de evidências. O projeto não expõe tokenizer confiável do
  modelo no caminho da ferramenta; a contagem usa `estimated_token_count()`
  (palavras e pontuação). Esse valor é conservador e não é uma medição
  científica do consumo do modelo.
- O corte final só ocorre em limite de orçamento. A seleção tenta terminar em
  fronteira semântica, mas uma unidade individual maior que o limite pode ser
  reduzida; nesse caso o conteúdo omitido é registrado.
- O primeiro match textual é uma heurística de composição, não prova de
  relevância factual nem alteração do ranking híbrido.
- Não foi criado mecanismo para recompor tabelas fragmentadas entre páginas;
  cada página continua isolada para evitar falsa continuidade.
- Os 80 casos reservados do benchmark não foram usados para desenvolvimento,
  calibração ou seleção de limiar.
