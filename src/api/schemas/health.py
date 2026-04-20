"""Schemas usados pelas rotas de health check."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Estrutura de resposta da rota de verificacao da API."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    app_name: str
    version: str
