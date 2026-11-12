# Agente Acadêmico V2

Implementação independente do agente conversacional em `src/app/agente_v2/`. A V2 preserva o V1 (`src/app/agente.py`) e usa o mesmo RAG documental, sem duplicar SQL, ranking ou acesso ao banco.

## Execução

```powershell
uv run --locked streamlit run src/app/agente_v2/streamlit_app.py
```

O ambiente precisa fornecer `OLLAMA_HOST`, `OLLAMA_MODEL` e a configuração de acesso ao PostgreSQL usada pelo RAG existente. A interface possui o botão **Nova conversa** e não compartilha o estado do V1.

## Fluxo

1. `Planner` interpreta a mensagem em contrato estruturado.
2. `ToolRegistry` executa somente `rag_document_search`.
3. `Synthesizer` gera `SynthesisResponse` independente de `AgentAnswer` tool calling.
4. O adaptador usa `finalize_grounding`/`extract_agent_result` existentes.
5. Apenas evidências verificadas são publicadas.

## Verificação

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
git diff --check
```

Resultado desta implementação: `446 passed, 1 skipped`; `ruff check .` e `git diff --check` também passaram. Teste real curto com `gemma4:e2b` e RAG ativo retornou uma resposta normativa em estado `partial`, publicou a evidência `document:1:page:16` e preservou a limitação documental.

## Limitações

- A síntese depende da saída estruturada suportada pelo modelo local.
- A V2 não transforma paráfrases não verificáveis em fatos; pode retornar `unsupported` ou `partial`.
- O histórico é efêmero em memória; não há persistência de conversas.
- Não foram executados reprocessamento, OCR, embeddings, mutação, Dryer, Crapper ou avaliações de 40/holdout.
