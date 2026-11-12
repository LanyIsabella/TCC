# Interface e operação

A UI independente está em `src/app/agente_v2/streamlit_app.py`. Ela reproduz a
identidade visual da V1, inicializa o modelo sob demanda e mantém a associação
visual por turno. Mostra limitações e somente evidências publicadas pelo
grounding em um bloco compacto. Não importa nem altera `src/app/agente.py` ou
`src/ui/app.py`. A comparação detalhada está em
[`comparacao_interface_v1_v2.md`](comparacao_interface_v1_v2.md).

Para executar:

```powershell
$env:OLLAMA_HOST = "http://localhost:11434"
$env:OLLAMA_MODEL = "gemma4:e2b"
uv run --locked streamlit run src/app/agente_v2/streamlit_app.py
```
