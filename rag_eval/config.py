import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_DIR = Path(__file__).resolve().parent
ROOT_DIR = PROJECT_DIR.parent
DEFAULT_OLLAMA_MODEL = "gemma4:e2b"


@dataclass(frozen=True)
class LLMConfig:
    client: OpenAI
    model_name: str
    provider_name: str


def load_environment() -> None:
    """Load the repository .env first, then allow rag_eval/.env to override it."""
    load_dotenv(ROOT_DIR / ".env")
    load_dotenv(PROJECT_DIR / ".env", override=True)


def _normalize_ollama_base_url(host: str) -> str:
    host = host.rstrip("/")
    if host.endswith("/v1"):
        return host
    return f"{host}/v1"


def resolve_llm_config() -> LLMConfig:
    load_environment()

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        return LLMConfig(
            client=OpenAI(api_key=openai_api_key),
            model_name=os.getenv("RAGAS_MODEL", "gpt-4o-mini"),
            provider_name="openai",
        )

    ollama_host = os.getenv("OLLAMA_HOST")
    ollama_model = os.getenv(
        "RAGAS_MODEL",
        os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
    )
    if ollama_host and ollama_model:
        return LLMConfig(
            client=OpenAI(
                api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
                base_url=_normalize_ollama_base_url(ollama_host),
            ),
            model_name=ollama_model,
            provider_name="ollama",
        )

    msg = (
        "Nenhum provedor de LLM foi configurado. "
        "Defina OPENAI_API_KEY para OpenAI ou OLLAMA_HOST + OLLAMA_MODEL para Ollama."
    )
    raise RuntimeError(msg)
