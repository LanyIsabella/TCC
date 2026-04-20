"""Colecao de roteadores expostos pela API."""

from src.api.routers.agent import router as agent_router
from src.api.routers.health import router as health_router

__all__ = ["agent_router", "health_router"]
