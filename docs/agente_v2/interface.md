# Interface e operação

A UI independente está em `src/app/agente_v2/streamlit_app.py`. Ela inicializa o modelo sob demanda, mostra mensagens do turno, estado de grounding, limitações e evidências em um expander. Não importa nem altera `src/app/agente.py` ou `src/ui/app.py`.

Para executar:

```powershell
$env:OLLAMA_HOST = "http://localhost:11434"
$env:OLLAMA_MODEL = "gemma4:e2b"
uv run --locked streamlit run src/app/agente_v2/streamlit_app.py
```
