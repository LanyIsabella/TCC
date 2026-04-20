"""Excecoes de dominio utilizadas pela camada da API."""


class AgentServiceError(Exception):
    """Classe base para erros relacionados ao servico do agente."""

    pass


class AgentNotConfiguredError(AgentServiceError):
    """Indica que o agente nao pode ser inicializado corretamente."""

    pass


class AgentExecutionError(AgentServiceError):
    """Indica que houve falha ao executar o agente."""

    pass


class AgentResponseError(AgentServiceError):
    """Indica que a resposta retornada pelo agente e invalida."""

    pass
