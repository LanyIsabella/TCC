"""Interface Streamlit para conversar com o agente de consultas ABNT."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.evidence import (  # noqa: E402
    AgentResult,
    EvidenceRecord,
    extract_agent_result,
)

ChatMessage = dict[str, Any]

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

    from src.app.agente import build_agent

    return build_agent()


def _render_conversation_summary(container: Any, messages: list[ChatMessage]) -> None:
    """Renderiza o resumo da conversa no container reservado do sidebar."""

    with container.container(border=True):
        st.markdown("**Conversa atual**")
        if not messages:
            st.caption("Nenhuma pergunta feita ainda.")
            return

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


def _agent_history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    """Remove metadados visuais antes de enviar o histórico ao agente."""

    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message.get("role") in {"user", "assistant"}
        and isinstance(message.get("content"), str)
    ]


def _document_label(evidence: EvidenceRecord) -> str:
    title = str(evidence.get("title") or "Documento sem título").strip()
    version = str(evidence.get("version") or "").strip()
    return f"{title} ({version})" if version else title


def _render_document_references(evidences: list[EvidenceRecord]) -> None:
    """Renderiza recortes correspondentes sem executar uma nova consulta."""

    if not evidences:
        return

    unique_evidences: list[EvidenceRecord] = []
    seen_texts: set[str] = set()
    for evidence in evidences:
        if "matched_text" in evidence:
            text = str(evidence.get("matched_text") or "").strip()
        else:
            text = str(evidence.get("text") or "").strip()
        if not text:
            continue
        duplicate_key = " ".join(text.split())
        if duplicate_key in seen_texts:
            continue
        seen_texts.add(duplicate_key)
        unique_evidences.append(evidence)
    if not unique_evidences:
        return

    documents: list[str] = []
    document_keys: set[tuple[str, str]] = set()
    for evidence in unique_evidences:
        label = _document_label(evidence)
        key = (
            str(
                evidence.get("rag_document_id")
                or evidence.get("document_id")
                or label
            ),
            label,
        )
        if key not in document_keys:
            document_keys.add(key)
            documents.append(label)

    reference_label = (
        "Documento de referência"
        if len(documents) == 1
        else "Documentos de referência"
    )
    st.caption(f"**{reference_label}:** {', '.join(documents)}")

    with st.status(
        ":material/check_circle: Trechos que sustentam a resposta",
        state="complete",
        expanded=False,
        type="compact",
    ):
        for rendered_count, evidence in enumerate(unique_evidences, start=1):
            if "matched_text" in evidence:
                text = str(evidence.get("matched_text") or "").strip()
            else:
                text = str(evidence.get("text") or "").strip()

            st.markdown(f"**Trecho {rendered_count}**")

            quote = "\n".join(f"> {line}" for line in text.splitlines())
            st.markdown(quote)
            if rendered_count < len(unique_evidences):
                st.divider()


def invoke_agent(
    prompt: str,
    history: list[ChatMessage] | None = None,
    *,
    agent: Any | None = None,
) -> AgentResult:
    """Envia o prompt e devolve a resposta com evidências validadas."""

    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ValueError("O prompt nao pode ser vazio.")

    conversation = [*(history or []), {"role": "user", "content": normalized_prompt}]

    if agent is None:
        agent = _load_agent()

    result = agent.invoke({"messages": conversation})
    return extract_agent_result(result)


def app() -> None:
    """Renderiza a tela e conecta o chat ao agente."""

    st.set_page_config(
        page_title="Normas Acadêmicas",
        page_icon=":material/menu_book:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    _init_session_state()
    conversation_summary = chat_bar()

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
            if role == "assistant":
                _render_document_references(message.get("evidences", []))

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

    history = _agent_history(st.session_state.messages)

    user_message = {"role": "user", "content": prompt}
    st.session_state.messages.append(user_message)
    _render_conversation_summary(conversation_summary, st.session_state.messages)
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
                result = invoke_agent(prompt, history)
        except Exception as exc:
            status.update(
                label="Não foi possível concluir a consulta", state="error"
            )
            st.error(f"Não foi possível consultar o agente: {exc}")
            return

        status.update(label="Consulta concluída", state="complete")
        st.markdown(result.answer)
        _render_document_references(result.evidences)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result.answer,
            "evidences": result.evidences,
        }
    )
    _render_conversation_summary(conversation_summary, st.session_state.messages)


def chat_bar() -> Any:
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

        conversation_summary = st.empty()
        _render_conversation_summary(
            conversation_summary, st.session_state.get("messages", [])
        )

        with st.expander("Como posso ajudar?", icon=":material/lightbulb:"):
            st.markdown(
                "- Citações diretas e indiretas\n"
                "- Referências bibliográficas\n"
                "- Estrutura e formatação de trabalhos\n"
                "- Dúvidas sobre normas ABNT"
            )

        st.caption("Baseado no conteúdo acadêmico disponível para o projeto.")

    return conversation_summary


app()
