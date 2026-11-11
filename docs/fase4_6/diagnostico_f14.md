# Diagnóstico

O pipeline já construía registros por turno em `src/app/evidence.py`, com
identificador, documento, página, texto e metadados de execução. A perda
ocorria depois da validação: `AgentService.chat()` devolvia apenas `answer` e
`messages`; `ChatSession.ask()` guardava somente o texto e `print_answer()`
renderizava somente esse texto. A UI consumia o objeto interno, mas os canais
públicos não.

A correção centraliza a projeção pública em `public_evidence()`, mapeia
`insufficient` para `unsupported` e transporta `grounding_status` e
`limitations` junto do resultado validado. O terminal mantém o resultado da
última pergunta e o exporta somente com campos sanitizados.
