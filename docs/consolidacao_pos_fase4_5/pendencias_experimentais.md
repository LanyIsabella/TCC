# Pendências experimentais

## Referência documental

- O lote de revisão tem 12 páginas e permanece `pending_human_review`.
- A seleção preliminar de referência tem 40 páginas, também sem transcrição
  humana. Esses conjuntos são páginas de OCR, não perguntas do benchmark.
- Os três extratores têm saídas individuais preservadas; nenhuma saída foi
  promovida a ground truth.

## Desenvolvimento e holdout

- `retrieval_development.json`: 40/40 casos `blocked` por
  `ollama_unavailable`.
- `agent_development.json`: 40/40 casos `blocked` pelo mesmo motivo.
- `queries.json`: 40 perguntas de desenvolvimento e 80 reservadas.
- Os 80 casos reservados continuam intocados.

O bloqueio atual é operacional (preflight sem Ollama/modelos confirmados). A
indisponibilidade não deve ser confundida com métrica zero. Mesmo após liberar o
serviço, correção factual e suporte por afirmação continuarão indisponíveis até
que uma amostra humana seja adjudicada.

## O que pode ser medido antes da referência humana

Em uma rodada executada, podem ser registrados: disponibilidade dos serviços,
status de execução, latência, rastreabilidade de consulta/documento/página,
cobertura de localizadores e retenção literal quando o fragmento já existia
antes da compactação. Grounding determinístico pode ser exercitado com fixtures
de contrato.

## O que depende de amostra humana

Fidelidade de OCR, omissões/inclusões, erros numéricos e estruturais, correção
factual, suporte por afirmação, Recall@k/MRR/nDCG adjudicados, abstenção correta,
falsa recusa, continuidade temática e calibração de CER/WER/similaridade.

Não há estimativa válida desses indicadores neste estado. O piloto F4.4 cobriu
quatro páginas e demonstrou execução/variação, não superioridade de extrator.
O experimento GLM-OCR alternativo terminou em uma página, mas apresentou erros
visuais/textuais e não foi validado como fiel.

O protocolo de execução controlada e os critérios de início estão em
`protocolo_execucao_controlada.md`.
