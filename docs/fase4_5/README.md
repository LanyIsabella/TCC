# Fase 4.5 — Compactação de evidências (F6)

Esta fase corrige a perda de conteúdo relevante após a recuperação híbrida, na
composição do payload entregue ao agente. O ranking, o RRF, os embeddings, a
ingestão, o corpus, o banco produtivo e a interface não foram modificados.

Escopo implementado:

- seleção de unidades contíguas próximas ao match da pergunta;
- prioridade para páginas recuperadas diretamente e com match textual;
- limite conservador de caracteres e de tokens estimados;
- preservação de página, edição, identificadores e texto-fonte;
- registro explícito de conteúdo omitido;
- conversão dos dois contratos F6 anteriormente marcados como `xfail`.

Não houve commit automático. A branch de trabalho é
`fix/fase4-5-compactacao-evidencias-20261111`.

Consulte `parecer_tecnico.md` para a decisão de encerramento.
