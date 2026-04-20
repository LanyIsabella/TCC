"""Dependencias compartilhadas pelas rotas da API."""

from functools import lru_cache

from src.api.core.exceptions import AgentNotConfiguredError
from src.api.services.agent_service import AgentService


@lru_cache
def get_agent_service() -> AgentService:
    """Instancia e reutiliza o servico responsavel por chamar o agente.

    Returns:
        AgentService: Servico pronto para execucao das interacoes.

    Raises:
        AgentNotConfiguredError: Quando o agente nao pode ser carregado.
    """

    try:
        from src.app.agente import build_agent

        return AgentService(agent=build_agent())
    except Exception as exc:
        raise AgentNotConfiguredError("Nao foi possivel inicializar o agente.") from exc
