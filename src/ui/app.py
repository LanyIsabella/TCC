"""Interface Streamlit para conversar com o agente de consultas ABNT."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

ChatMessage = dict[str, str]

SUGGESTIONS = {
    ":material/format_quote: Como fazer uma citação direta curta?": (
        "Como fazer uma citação direta curta segundo a ABNT?"
    ),
    ":material/menu_book: Como montar as referências?": (
        "Como montar as referências bibliográficas de um livro?"
    ),
    ":material/article: Como formatar o TCC?": (
        "Quais são as principais regras de formatação de um TCC segundo a ABNT?"
    ),
}


def _init_session_state() -> None:
    """Inicializa o estado da sessão em um único lugar."""

    if "messages" not in st.session_state:
        st.session_state.messages = []


def _clear_conversation() -> None:
    """Limpa a conversa atual e os controles da tela inicial."""

    st.session_state.messages = []
    st.session_state.pop("suggestion", None)


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

    st.set_page_config(
        page_title="Normas Acadêmicas",
        page_icon=":material/menu_book:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _init_session_state()
    chat_bar()

    st.title("Normas Acadêmicas", icon=":material/menu_book:")
    st.caption(
        "Seu espaço para consultar documentos normativos acadêmicos, estruturar "
        "trabalhos e escrever com mais segurança."
    )

    for message in st.session_state.messages:
        role = message["role"]
        avatar = (
            ":material/person:" if role == "user" else ":material/auto_awesome:"
        )
        with st.chat_message(role, avatar=avatar):
            st.markdown(message["content"])

    prompt = None
    if not st.session_state.messages:
        with st.container(border=True):
            st.subheader("Comece por uma pergunta")
            st.caption(
                "Escolha um exemplo abaixo ou escreva sua dúvida no campo de mensagem."
            )
            selected = st.pills(
                "Sugestões para começar",
                list(SUGGESTIONS),
                key="suggestion",
                label_visibility="collapsed",
                wrap=True,
            )
            if selected:
                prompt = SUGGESTIONS[selected]

    chat_prompt = st.chat_input(
        "Pergunte sobre citações, referências ou formatação ABNT...",
        key="chat_input",
        submit_mode="disable",
    )
    if chat_prompt:
        prompt = chat_prompt

    if not prompt:
        return

    prompt = prompt.strip()
    if not prompt:
        return

    history = list(st.session_state.messages)

    user_message = {"role": "user", "content": prompt}
    st.session_state.messages.append(user_message)
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar=":material/auto_awesome:"):
        try:
            with st.status(
                ":shimmer[Consultando a base de conhecimento...]",
                state="running",
                expanded=False,
                type="compact",
            ) as status:
                answer = invoke_agent(prompt, history)
        except Exception as exc:
            status.update(
                label="Não foi possível concluir a consulta", state="error"
            )
            st.error(f"Não foi possível consultar o agente: {exc}")
            return

        status.update(label="Consulta concluída", state="complete")
        st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})


def chat_bar() -> None:
    """Renderiza a navegação e os controles persistentes do chat."""

    with st.sidebar:
        st.markdown("## :material/menu_book: Normas Acadêmicas")
        st.caption(
            "Documentos normativos acadêmicos de forma simples, clara e confiável."
        )

        st.button(
            "Nova conversa",
            icon=":material/add:",
            type="primary",
            width="stretch",
            on_click=_clear_conversation,
        )

        messages = st.session_state.get("messages", [])
        with st.container(border=True):
            st.markdown("**Conversa atual**")
            if messages:
                user_count = sum(message["role"] == "user" for message in messages)
                question_label = "pergunta" if user_count == 1 else "perguntas"
                st.caption(f"{user_count} {question_label} nesta conversa")
                last_message = next(
                    (
                        message["content"]
                        for message in reversed(messages)
                        if message["role"] == "user"
                    ),
                    "",
                )
                if last_message:
                    st.caption(f"Última pergunta: {last_message[:100]}")
            else:
                st.caption("Nenhuma pergunta feita ainda.")

        with st.expander("Como posso ajudar?", icon=":material/lightbulb:"):
            st.markdown(
                "- Citações diretas e indiretas\n"
                "- Referências bibliográficas\n"
                "- Estrutura e formatação de trabalhos\n"
                "- Dúvidas sobre normas ABNT"
            )

        st.caption("Baseado no conteúdo acadêmico disponível para o projeto.")


app()
