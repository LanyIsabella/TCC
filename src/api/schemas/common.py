"""Schemas utilitarios compartilhados por mais de uma rota."""

from pydantic import BaseModel, ConfigDict


class ErrorResponse(BaseModel):
    """Modelo padrao de erro da API."""

    model_config = ConfigDict(extra="forbid")

    detail: str


class APIInfoResponse(BaseModel):
    """Modelo retornado pela rota raiz com metadados da API."""

    model_config = ConfigDict(extra="forbid")

    app_name: str
    version: str
    docs_url: str
    api_prefix: str
