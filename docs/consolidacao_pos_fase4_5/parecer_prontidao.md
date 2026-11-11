# Parecer de prontidão experimental

## Estado atual

Os contratos funcionais conhecidos F1, F2, F5, F6, F7 e F10–F13 possuem
implementação e testes determinísticos. F3, F4, F8 e F9 têm controles técnicos
parciais. F14 permanece pendente como contrato de exposição de evidências nos
canais API/terminal. F15 é uma pendência metodológica; F16 está coberto no
backend, com a ressalva de F14.

## Bloqueios dos 40 casos

Os arquivos de desenvolvimento registram 40 casos bloqueados em cada estágio
(`retrieval` e `agent`) porque o preflight retornou `ollama_unavailable`.
Isso é indisponibilidade de serviço/configuração, não ausência de perguntas nem
resultado negativo. As referências humanas pendentes não causaram o bloqueio
de execução, mas impedem pontuar correção factual depois que o serviço estiver
disponível.

## Decisão

**Pronto para uma avaliação controlada em duas camadas, quando os critérios de
início forem satisfeitos; não pronto para declarar qualidade factual, promover
automaticamente à Gold ou usar produção.**

### Camada A — pode iniciar sem referência humana completa

Recuperação no desenvolvimento, rastreabilidade, latência, disponibilidade de
serviços, cobertura de localizadores, retenção literal pré/pós-compactação e
contratos determinísticos de grounding.

### Camada B — requer avaliação humana amostral

Fidelidade textual/OCR, erros numéricos e estruturais, correção factual,
suporte por afirmação, métricas de recuperação adjudicadas, abstenção/falsa
recusa e calibração de CER/WER/similaridade. A amostra humana não precisa cobrir
as 177 páginas; o lote de 12 e a seleção de 40 devem ser tratados como conjuntos
separados e versionados.

## Critérios de início

1. Ollama responde ao preflight e os digests de `gemma4:e2b` e
   `nomic-embed-text` são registrados.
2. Snapshot, dataset, commit e hashes de implementação estão congelados.
3. PostgreSQL de avaliação é somente leitura e os resultados serão gravados em
   novos arquivos por estágio.
4. Os 80 casos `reserved` continuam intocados.
5. O protocolo separa execução/rastreabilidade de fidelidade/correção factual.
6. A amostra documental e os critérios de adjudicação são definidos antes da
   pontuação; texto nativo e concordância entre extratores não são ground truth.

O protocolo detalhado está em
`docs/consolidacao_pos_fase4_5/protocolo_execucao_controlada.md`.

## Recomendação

Fechar primeiro o contrato F14 e a matriz histórica dos defeitos em qualquer
fase funcional futura. Para a avaliação, liberar apenas o split de
desenvolvimento e registrar bloqueios/`null` sem convertê-los em aprovação ou
reprovação artificial.
