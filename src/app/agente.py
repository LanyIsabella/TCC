from functools import lru_cache

from langchain.agents import create_agent

from .client import Client
from .prompt import load_prompt_sys
from .tools.rag_search import rag_document_search
from .tools.web_search import langsearch_websearch_tool


@lru_cache(maxsize=1)
def build_agent():
    client = Client()
    system_prompt = load_prompt_sys()

    return create_agent(
        model=client.return_model(),
        tools=[langsearch_websearch_tool, rag_document_search],
        system_prompt=system_prompt,
    )


agent = build_agent()

__all__ = ["agent", "build_agent"]
