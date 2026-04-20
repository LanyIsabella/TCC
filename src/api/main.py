"""Ponto de entrada da aplicacao FastAPI.

Este modulo monta a instancia principal da API, registra as rotas
versionadas e centraliza o tratamento das excecoes de dominio da camada
de servico.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.core.config import get_settings
from src.api.core.exceptions import (
    AgentExecutionError,
    AgentNotConfiguredError,
    AgentResponseError,
)
from src.api.routers.agent import router as agent_router
from src.api.routers.health import router as health_router
from src.api.schemas.common import APIInfoResponse, ErrorResponse


def create_app() -> FastAPI:
    """Cria e configura a aplicacao FastAPI.

    Returns:
        FastAPI: Instancia configurada com rotas, metadados e handlers
        de excecao.
    """

    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(agent_router, prefix=settings.api_prefix)

    @app.get("/", response_model=APIInfoResponse, tags=["Meta"])
    def read_root() -> APIInfoResponse:
        """Retorna metadados basicos da API.

        Returns:
            APIInfoResponse: Informacoes de nome, versao e links uteis.
        """

        return APIInfoResponse(
            app_name=settings.app_name,
            version=settings.app_version,
            docs_url=app.docs_url or "/docs",
            api_prefix=settings.api_prefix,
        )

    @app.exception_handler(AgentNotConfiguredError)
    async def handle_agent_not_configured(
        _request: Request, exc: AgentNotConfiguredError
    ) -> JSONResponse:
        """Converte falhas de configuracao do agente em resposta HTTP 503."""

        return JSONResponse(
            status_code=503,
            content=ErrorResponse(detail=str(exc)).model_dump(),
        )

    @app.exception_handler(AgentExecutionError)
    async def handle_agent_execution_error(
        _request: Request, exc: AgentExecutionError
    ) -> JSONResponse:
        """Converte falhas de execucao do agente em resposta HTTP 502."""

        return JSONResponse(
            status_code=502,
            content=ErrorResponse(detail=str(exc)).model_dump(),
        )

    @app.exception_handler(AgentResponseError)
    async def handle_agent_response_error(
        _request: Request, exc: AgentResponseError
    ) -> JSONResponse:
        """Converte respostas invalidas do agente em resposta HTTP 502."""

        return JSONResponse(
            status_code=502,
            content=ErrorResponse(detail=str(exc)).model_dump(),
        )

    return app


app = create_app()
