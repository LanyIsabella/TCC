# Limitações remanescentes

- O run existente continua observacional e não foi reprocessado com o novo
  formato; portanto, não há números `before/after` de 40 casos nesta etapa.
- A taxa de chamadas `AgentAnswer` e a qualidade factual das respostas não foram
  reavaliadas experimentalmente após a correção; o novo trace apenas permite
  medi-las corretamente em uma execução futura.
- A presença de `structured_response` no trace não prova fidelidade factual do
  modelo. A decisão continua dependente de trechos recuperados e da política de
  grounding.
- `available_evidence_ids` representa o payload entregue ao encerramento;
  `published_evidence_ids` representa somente evidência validada pela decisão.
  Nenhum dos dois substitui revisão humana das referências do dataset.
- A classificação `textual_after_retrieval` registra uma falha de conformidade
  do encerramento original, mas não adiciona chamadas ilimitadas nem tenta
  reescrever a resposta do modelo.
- A execução completa de testes e os gates automáticos do ambiente devem ser
  reportados sem reivindicar aprovação quando houver falha de infraestrutura.
- O último relatório ub-mode disponível não é um gate verde: Crapper e Mutator
  foram interrompidos/expiraram e Dryer registrou duplicações. Esses resultados
  ficam como limitação conhecida; esta fase não executou novamente os gates por
  restrição explícita.
