# Exemplos

Exemplo resumido de API apoiada:

```json
{
  "answer": "A margem direita mede 2 cm.",
  "messages": [],
  "grounding_status": "supported",
  "limitations": [],
  "evidences": [{
    "evidence_id": "document:99:page:14",
    "standard_id": "abnt_nbr_14724",
    "version": "2024",
    "page_number": 14,
    "text": "A margem direita mede 2 cm.",
    "turn_id": "turn-current",
    "tool_call_id": "call-current"
  }]
}
```

No terminal, o texto é seguido por `Fundamentação: apoiada`, `parcial` ou
`não fundamentada`, pelas limitações e pelas linhas de evidência. Uma resposta
parcial nunca é rotulada como fundamentação completa.
