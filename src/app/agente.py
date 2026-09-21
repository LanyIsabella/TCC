from functools import lru_cache
from typing import Any

from langchain.agents import create_agent

from .client import Client
from .prompt import load_prompt_sys
from .scope_guard import ScopeDecision, classify_messages, guarded_response
from .tools.rag_search import rag_document_search


class ScopedAgent:
    """Impede chamadas ao modelo para mensagens fora do escopo definido."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        decision = classify_messages(messages)
        if decision in {ScopeDecision.GREETING, ScopeDecision.OUT_OF_SCOPE}:
            return guarded_response(messages, decision)
        return self._agent.invoke(payload)


@lru_cache(maxsize=1)
def build_agent():
    client = Client()
    system_prompt = load_prompt_sys()

    return ScopedAgent(
        create_agent(
            model=client.return_model(),
            tools=[rag_document_search],
            system_prompt=system_prompt,
        )
    )


agent = build_agent()

__all__ = ["agent", "build_agent"]
