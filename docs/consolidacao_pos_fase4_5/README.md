# Consolidação técnica pós-Fase 4.5

Esta auditoria consolida o estado observável do RAG no commit
`9177c7f6a342bbe3bbade928504eaf9dbf5dfd96`, sem alterar código funcional,
corpus, Gold, embeddings, banco produtivo ou benchmark reservado.

Fontes principais:

- `AGENTS.md` e a baseline em `docs/baseline_fase2.md`;
- contratos em `tests/baseline/test_defect_pipeline.py` e
  `tests/baseline/test_defect_agent.py`;
- relatórios `docs/fase3_contratos/`, `docs/fase4_1/`, `docs/fase4_2/`,
  `docs/fase4_3/`, `docs/fase4_4/` e `docs/fase4_5/`;
- código atual de extração, Silver/Gold, busca, evidência e grounding.

Complementos desta revisão:

- `inventario_conjuntos_experimentais.md` separa as 40 páginas de revisão, o
  lote de 12 páginas, as 40 perguntas de desenvolvimento e o holdout de 80;
- `protocolo_execucao_controlada.md` separa experimentos executáveis sem
  referência humana completa daqueles dependentes de adjudicação amostral;
- `matriz_f1_f16.md` registra as definições de F7–F9/F14–F16 com o grau de
  confirmação da fonte histórica, sem converter lacunas em correções.

Documentos do pacote:

- [matriz F1–F16](matriz_f1_f16.md)
- [mapa de commits](mapa_correcoes_commits.md)
- [inventário dos conjuntos](inventario_conjuntos_experimentais.md)
- [pendências funcionais](pendencias_funcionais.md)
- [pendências experimentais](pendencias_experimentais.md)
- [limitações operacionais](limitacoes_operacionais.md)
- [protocolo controlado](protocolo_execucao_controlada.md)
- [parecer de prontidão](parecer_prontidao.md)
