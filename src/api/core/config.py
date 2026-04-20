"""Configuracoes da API carregadas a partir do ambiente.

Este modulo encapsula a leitura do arquivo `.env` do projeto e expoe um
objeto tipado com as configuracoes utilizadas pela camada HTTP.
"""

from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseModel):
    """Representa as configuracoes utilizadas pela API."""

    model_config = ConfigDict(extra="ignore")

    app_name: str = Field(default="TCC Sistema Agent API")
    app_version: str = Field(default="0.1.0")
    api_prefix: str = Field(default="/api/v1")
    environment: str = Field(default="development")
    ollama_model: str | None = None
    ollama_host: str | None = None
    ollama_temperature: float = Field(default=0.0)
    langsearch_host: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Le o ambiente do projeto e devolve as configuracoes da API.

    O uso de cache evita releituras desnecessarias do arquivo `.env`
    durante o ciclo de vida da aplicacao.

    Returns:
        Settings: Configuracoes consolidadas da API.
    """

    env_file = REPO_ROOT / ".env"
    env_values: dict[str, str] = {}
    if env_file.exists():
        env_values = {
            key: value
            for key, value in dotenv_values(env_file).items()
            if value is not None
        }

    return Settings(
        ollama_model=env_values.get("OLLAMA_MODEL"),
        ollama_host=env_values.get("OLLAMA_HOST"),
        ollama_temperature=float(env_values.get("OLLAMA_TEMPERATURE", "0")),
        langsearch_host=env_values.get("LANGSEARCH_HOST"),
    )
