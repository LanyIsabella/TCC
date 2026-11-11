# Parecer técnico — Fase 4.3

## Resultado

F5 foi implementado como contrato de metadados estruturados, versionados e com proveniência por campo. O pacote não declara que os valores registrados são ground truth documental.

## Alterações

- `data/normative_metadata.py`: normalização determinística, datas separadas, valores desconhecidos explícitos e detecção de conflitos.
- `data/migrations/0003_normative_metadata.up.sql` e `.down.sql`: colunas nullable nas camadas Bronze, Silver e Gold; rollback protege dados preenchidos.
- `data/rag_schema.sql`: declara as colunas no schema base.
- `data/bronze_postgres.py`: registra o objeto estruturado junto ao manifesto, sem remover o JSON legado.
- `data/rag_pipeline.py`: propaga o objeto para Silver/Gold na ativação, preservando campos e histórico existentes.
- testes unitários e de PostgreSQL isolado para identidade, datas, conflitos e migração.

## Testes e evidências

- `uv run --no-sync python -m pytest tests -q`: **377 passed, 1 skipped, 2 xfailed** (F6 conhecidos), sem falhas inesperadas.
- Os dois `PytestUnknownMarkWarning` foram corrigidos registrando o marcador `integration` em `pyproject.toml`; a execução final não emitiu warnings.
- `uv run --no-sync ruff check .`: **All checks passed**.
- `git diff --check`: aprovado.
- Não houve execução de ingestão/OCR/embeddings nem alteração de dados ativos.

## Limitações e pendências

- A confirmação da edição 2004 da NBR6034 e da validade em 2005 requer inspeção documental/humana; o código não inventa essa confirmação.
- Dados históricos não foram retroativamente preenchidos: a coluna é nullable e a divergência legada permanece auditável.
- A suíte automatizada não substitui a verificação da exatidão dos metadados do corpus original.
- Crapper, Dryer e Mutator não foram repetidos nesta etapa; suas limitações anteriores permanecem documentadas.

## Organização e encerramento

- Branch definitiva: `fix/fase4-3-metadados-normativos-20261110`.
- Commit local: `feat(fase4.3): add versioned normative metadata`.
- Nenhum backfill histórico foi executado.
- A edição/validade da NBR 6034 permanece não confirmada; não foi classificada como vigente ou revogada.
- Pendências transferidas à Fase 4.4: revisão humana dos metadados conflitantes, eventual backfill controlado e calibração metodológica, mediante autorização explícita.
- Não foram definidos limiares de confiança nem seleção adaptativa por página.

## Recomendação

Encerrar tecnicamente a Fase 4.3 com ressalvas: o contrato impede colapsar edição/publicação/vigência e preserva proveniência, mas a conciliação jurídica de NBR6034 e o backfill controlado dependem de revisão humana e de uma fase posterior autorizada.
