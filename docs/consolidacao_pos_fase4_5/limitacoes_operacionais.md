# Limitações operacionais

- O PostgreSQL produtivo não foi migrado nem escrito durante as fases; os
  testes de persistência usam clusters sintéticos/isolados.
- PDFs, Bronze, Silver/Gold ativos, embeddings, RRF e UI foram preservados.
- O relatório global do ub-mode continua sem aprovação: o Crapper registrou
  CRAP agregado `3906.0 > 10.0`, o Dryer encontrou duplicações (inclusive em
  `data/rag_pipeline.py`) e o Mutator matou 75 mutações, mas deixou 565 pontos
  sem cobertura; o relatório marca a execução como incompleta por expiração do
  orçamento compartilhado. Esses gates não foram repetidos nesta consolidação.
- Uma falha transitória de permissão em concorrência do Windows/OneDrive foi
  observada na regressão e passou em reexecuções isoladas; ela não foi tratada
  como defeito F2 nesta auditoria.
- Tags e serviços Ollama são estado externo mutável; digests e configuração
  precisam ser registrados para cada experimento.
- Os indicadores determinísticos selecionam integridade técnica, não garantem
  que uma transcrição esteja visualmente ou semanticamente correta.
- F7–F9/F14–F16 foram reconciliados com correspondências verificáveis em
  relatórios e código, mas não aparecem como linhas numeradas na baseline
  original; a confirmação histórica permanece parcial onde indicado na matriz.
