# Critérios e limitações

## Indicadores

- `technical_failure`: processamento diferente de `success`.
- `empty_text`: texto vazio sem marcação explícita de página vazia.
- `truncated_output`: `completion_unconfirmed`.
- `suspicious_unicode_density`: PUA acima de 1% dos caracteres; é um guarda
  operacional de corrupção, não um limiar científico de qualidade.
- avisos independentes registram PUA, substituição, controles, estrutura e
  referências normativas.
- `numeric_token_count` e `normative_reference_count` registram a presença de
  números/referências; não provam que os valores estão corretos.
- A decisão registra similaridade pareada entre candidatos como divergência
  descritiva. Ela não é usada como ground truth nem como limiar científico.

Quando todos os candidatos falham tecnicamente ou por truncamento, o estado é
`retry_required`; falhas de conteúdo ou ausência de evidência permanecem
`quarantined`.

O texto nativo do leitor PDF pode ser usado apenas como referência diagnóstica.
Ele não é ground truth. Na ausência de referência independente, a decisão não
converte similaridade entre pares em evidência de correção.

## Limitações

Os indicadores não detectam todos os erros semânticos, omissões discretas ou
alterações numéricas sem uma referência humana/independente. A calibração dos
indicadores e limiares permanece pendente para a Fase 4.4/4.5 experimental,
sem alterar a regra conservadora atual.
