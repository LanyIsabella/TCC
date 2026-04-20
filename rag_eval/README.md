# RAG Evaluation

Evaluate a RAG (Retrieval Augmented Generation) system with custom metrics

## Quick Start

### 1. Configure Your Model

This project can use either OpenAI or a local Ollama instance.

If you are using PowerShell, set variables like this:

```powershell
$env:OPENAI_API_KEY="your-openai-key"
```

If you are using the repository root `.env`, `evals.py` will load it automatically.

Choose your LLM provider:

```bash
# OpenAI
OPENAI_API_KEY="your-openai-key"

# Or local Ollama
OLLAMA_HOST="http://localhost:11434"
OLLAMA_MODEL="gemma4:e2b"
```

### 2. Install Dependencies

Using `uv` (recommended):

```bash
uv sync
```

Or using `pip`:

```bash
pip install -e .
```

### 3. Run the Evaluation

Using `uv`:

```bash
uv run python evals.py
```

Or using `pip`:

```bash
python evals.py
```

## Project Structure

```
rag_eval/
├── README.md           # This file
├── pyproject.toml      # Project configuration
├── rag.py              # Your RAG application code
├── evals.py            # Evaluation workflow
├── __init__.py         # Makes this a Python package
└── evals/              # Evaluation-related data
    ├── datasets/       # Test datasets
    ├── experiments/    # Experiment results
    └── logs/           # Evaluation logs and traces
```

## Customization

### Provider Selection

- If `OPENAI_API_KEY` is set, the evaluation uses OpenAI.
- Otherwise, if `OLLAMA_HOST` and `OLLAMA_MODEL` are set, it uses Ollama through its OpenAI-compatible API.
- You can override the model name with `RAGAS_MODEL`.

### Modify the LLM Provider

In `evals.py`, update the LLM configuration:

```python
from ragas.llms import llm_factory

# Use Anthropic Claude
llm = llm_factory("claude-3-5-sonnet-20241022", provider="anthropic")

# Use Google Gemini
llm = llm_factory("gemini-1.5-pro", provider="google")

# Use local Ollama
llm = llm_factory("mistral", provider="ollama", base_url="http://localhost:11434")
```

### Customize Test Cases

Edit the `load_dataset()` function in `evals.py` to add or modify test cases.

### Change Evaluation Metrics

Update the `my_metric` definition in `evals.py` to use different grading criteria.

## Documentation

Visit https://docs.ragas.io for more information.
