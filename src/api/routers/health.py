"""Rotas de observabilidade e verificacao simples da API."""

from typing import Annotated

from fastapi import APIRouter, Depends

from src.api.core.config import Settings, get_settings
from src.api.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse, summary="Verifica a disponibilidade")
def healthcheck(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Retorna o estado atual da aplicacao.

    Args:
        settings: Configuracoes carregadas da API.

    Returns:
        HealthResponse: Indicador simples de disponibilidade do servico.
    """

    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.app_version,
    )
