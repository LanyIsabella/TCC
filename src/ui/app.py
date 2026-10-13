"""Interface Streamlit para conversar com o agente de consultas ABNT."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

ChatMessage = dict[str, str]


def _load_agent() -> Any:
    """Carrega o agente mesmo quando o Streamlit executa este arquivo direto."""

    project_root = Path(__file__).resolve().parents[2]
    project_root_text = str(project_root)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)

    from src.app.agente import build_agent

    return build_agent()


def _normalize_content(content: Any) -> str:
    """Converte os formatos de conteudo usados pelo LangChain em texto."""

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue

            if isinstance(item, Mapping):
                value = item.get("text") or item.get("content")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())

        return "\n".join(parts).strip()

    return str(content).strip() if content is not None else ""


def _extract_answer(result: Any) -> str:
    """Retorna a ultima mensagem textual do assistente."""

    if not isinstance(result, Mapping):
        raise RuntimeError("O agente retornou um formato de resposta invalido.")

    messages = result.get("messages")
    if not isinstance(messages, list):
        raise RuntimeError("O agente retornou uma resposta sem mensagens.")

    for message in reversed(messages):
        if isinstance(message, Mapping):
            raw_role = message.get("role") or message.get("type")
            content = message.get("content")
        else:
            raw_role = getattr(message, "role", None) or getattr(message, "type", None)
            content = getattr(message, "content", None)

        role = {"ai": "assistant", "human": "user"}.get(str(raw_role), str(raw_role))
        answer = _normalize_content(content)
        if role == "assistant" and answer:
            return answer

    raise RuntimeError("O agente nao retornou uma resposta do assistente.")


def invoke_agent(
    prompt: str,
    history: list[ChatMessage] | None = None,
    *,
    agent: Any | None = None,
) -> str:
    """Envia o prompt do UI ao agente e devolve a resposta para o UI."""

    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ValueError("O prompt nao pode ser vazio.")

    conversation = [*(history or []), {"role": "user", "content": normalized_prompt}]

    if agent is None:
        agent = _load_agent()

    result = agent.invoke({"messages": conversation})
    return _extract_answer(result)


def app() -> None:
    
    """Renderiza a tela e conecta o chat ao agente."""
    
    chat_bar()

    st.header("Chatbot para consultas ABNT", divider="gray")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Digite sua mensagem")
    if not prompt:
        return

    prompt = prompt.strip()
    if not prompt:
        return

    history = list(st.session_state.messages)

    # Salva e exibe o usuario antes da chamada bloqueante ao agente.
    user_message = {"role": "user", "content": prompt}
    st.session_state.messages.append(user_message)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Pensando..."):
                answer = invoke_agent(prompt, history)
        except Exception as exc:
            st.error(f"Não foi possível consultar o agente: {exc}")
            return

        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
    



def chat_bar():
    with st.sidebar:
        st.header("Olá, Lany!", text_alignment="left", )
        st.subheader("Acesse suas conversas abaixo", text_alignment="center")
        container = st.container(border=True, vertical_alignment='top')

app()
