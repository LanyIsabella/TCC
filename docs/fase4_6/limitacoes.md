# Limitações

- A exposição torna a proveniência observável, mas não prova por si só a
  fidelidade factual de uma resposta de LLM.
- Somente evidências selecionadas pela política do turno atual são publicadas;
  evidências internas de ranking permanecem fora do contrato.
- `question_sha256` e caminhos locais não são expostos; IDs de turno/tool são
  opacos e servem apenas para rastreabilidade.
- A UI não foi alterada. Clientes antigos não recebem os campos aditivos se o
  serviço não os preencher.
