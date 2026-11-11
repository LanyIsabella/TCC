# Modelo `normative-metadata-v1`

O objeto é nullable para preservar registros históricos sem metadados estruturados. Quando presente, contém:

```json
{
  "schema_version": "normative-metadata-v1",
  "identity": {"issuer": "ABNT", "code": "NBR 6034", "edition": null, "canonical": "ABNT NBR 6034"},
  "title": null,
  "edition": "2005",
  "issuer": "ABNT",
  "document_type": "norma",
  "status": "vigente",
  "dates": {"publication": "2004-12-01", "effective": "2005-01-01"},
  "provenance": {"title": {"status": "unknown", "source_layer": "bronze", "source_field": "title"}}
}
```

`direct`, `normalized`, `inferred` e `unknown` são estados de proveniência; a implementação atual produz `direct` ou `unknown`, e não promove inferências de nome de arquivo. Edição, data de publicação e data de vigência são campos independentes.

Identificadores ABNT (`NBR 6023`, `ABNT NBR 6023`, `NBR 6023:2018`) convergem para a mesma identidade canônica, mantendo a edição separada. Identificadores ISO/IEC sem prefixo ABNT permanecem ISO/IEC.
