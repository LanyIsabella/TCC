"""Interface Streamlit V2 com a identidade visual da aplicação original."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.agente_v2.orchestrator import AgentV2  # noqa: E402

ChatMessage = dict[str, Any]
MappingLike = dict[str, Any]

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
    """Inicializa todo o estado visual da V2 em um único lugar."""

    if "conversation_id_v2" not in st.session_state:
        st.session_state.conversation_id_v2 = uuid4().hex
    if "messages_v2" not in st.session_state:
        st.session_state.messages_v2 = []
    if "agent_v2" not in st.session_state:
        st.session_state.agent_v2 = None


def _clear_conversation() -> None:
    """Cria uma conversa nova sem reaproveitar contexto ou evidências."""

    st.session_state.conversation_id_v2 = uuid4().hex
    st.session_state.messages_v2 = []
    st.session_state.pop("suggestion_v2", None)


def _agent() -> AgentV2:
    """Devolve o agente V2 da sessão atual."""

    if st.session_state.agent_v2 is None:
        st.session_state.agent_v2 = AgentV2()
    return st.session_state.agent_v2


def _render_conversation_summary(container: Any, messages: list[ChatMessage]) -> None:
    """Renderiza o resumo da conversa no container reservado da sidebar."""

    with container.container(border=True):
        st.markdown("**Conversa atual**")
        if not messages:
            st.caption("Nenhuma pergunta feita ainda.")
            return

        user_count = sum(message.get("role") == "user" for message in messages)
        question_label = "pergunta" if user_count == 1 else "perguntas"
        st.caption(f"{user_count} {question_label} nesta conversa")

        last_message = next(
            (
                message.get("content", "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        if last_message:
            st.caption(f"Última pergunta: {str(last_message)[:100]}")


def _agent_history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    """Remove metadados visuais antes de enviar o histórico ao AgentV2."""

    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message.get("role") in {"user", "assistant"}
        and isinstance(message.get("content"), str)
    ]


def _document_label(evidence: MappingLike) -> str:
    title = str(evidence.get("title") or "Documento sem título").strip()
    version = str(evidence.get("version") or "").strip()
    return f"{title} ({version})" if version else title


def _evidence_text(evidence: MappingLike) -> str:
    matched_text = str(evidence.get("matched_text") or "").strip()
    return matched_text or str(evidence.get("text") or "").strip()


def _published_evidences(record: dict[str, Any]) -> list[MappingLike]:
    """Retorna somente os trechos explicitamente publicados pelo grounding."""

    published_ids = [
        normalized_id
        for value in record.get("published_evidence_ids") or ()
        if (normalized_id := str(value or "").strip())
    ]
    if not published_ids:
        return []
    candidates: dict[str, MappingLike] = {}
    for evidence in record.get("evidences") or ():
        if not isinstance(evidence, dict):
            continue
        evidence_id = str(evidence.get("evidence_id") or "").strip()
        if evidence_id:
            candidates[evidence_id] = evidence
    rendered: list[MappingLike] = []
    seen_ids: set[str] = set()
    for evidence_id in published_ids:
        if evidence_id in seen_ids:
            continue
        evidence = candidates.get(evidence_id)
        if evidence is None:
            continue
        text = _evidence_text(evidence)
        if not text:
            continue
        seen_ids.add(evidence_id)
        rendered.append(dict(evidence))
    return rendered


def _render_document_references(evidences: list[MappingLike]) -> None:
    """Renderiza os recortes publicados, sem executar nova recuperação."""

    if not evidences:
        return

    documents: list[str] = []
    document_keys: set[tuple[str, str]] = set()
    for evidence in evidences:
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
        for rendered_count, evidence in enumerate(evidences, start=1):
            st.markdown(f"**Trecho {rendered_count}**")
            st.caption(_document_label(evidence))
            page_number = evidence.get("page_number")
            if page_number is not None:
                st.caption(f"Página: {page_number}")
            quote = "\n".join(
                f"> {line}" for line in _evidence_text(evidence).splitlines()
            )
            st.markdown(quote)
            if rendered_count < len(evidences):
                st.divider()


def _presentation_record(result: dict[str, Any]) -> dict[str, Any]:
    """Conserva a decisão pública e somente as evidências publicadas."""

    published_ids = [str(value) for value in result.get("published_evidence_ids") or ()]
    return {
        "turn_id": result.get("turn_id"),
        "grounding_status": result.get("grounding_status", "unsupported"),
        "limitations": [
            str(value)
            for value in result.get("limitations") or ()
            if str(value).strip()
        ],
        "published_evidence_ids": published_ids,
        "evidences": _published_evidences(
            {
                "published_evidence_ids": published_ids,
                "evidences": result.get("evidences") or (),
            }
        ),
    }


def _render_presentation(record: dict[str, Any], answer: str = "") -> None:
    limitations = [
        limitation
        for limitation in record.get("limitations") or ()
        if str(limitation).strip() != answer.strip()
    ]
    if limitations:
        st.caption("Limitações: " + " ".join(limitations))
    _render_document_references(record.get("evidences") or [])


def invoke_agent(
    prompt: str,
    history: list[ChatMessage] | None = None,
    *,
    conversation_id: str,
    agent: Any | None = None,
) -> dict[str, Any]:
    """Envia uma pergunta ao AgentV2 sem transportar metadados visuais."""

    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        raise ValueError("O prompt não pode ser vazio.")
    if agent is None:
        agent = _agent()
    messages = [
        *_agent_history(history or []),
        {"role": "user", "content": normalized_prompt},
    ]
    return agent.invoke({"conversation_id": conversation_id, "messages": messages})


def _render_message(message: ChatMessage) -> None:
    role = message["role"]
    avatar = ":material/person:" if role == "user" else ":material/auto_awesome:"
    with st.chat_message(role, avatar=avatar):
        st.markdown(message["content"])
        if role == "assistant":
            _render_presentation(message.get("presentation") or {}, message["content"])


def chat_bar() -> Any:
    """Renderiza a sidebar com a identidade da V1."""

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
            conversation_summary, st.session_state.get("messages_v2", [])
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


def main() -> None:
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

    for message in st.session_state.messages_v2:
        _render_message(message)

    prompt = None
    if not st.session_state.messages_v2:
        with st.container(border=True):
            st.subheader("Comece por uma pergunta")
            st.caption(
                "Escolha um exemplo abaixo ou escreva sua dúvida no campo de mensagem."
            )
            selected = st.pills(
                "Sugestões para começar",
                list(SUGGESTIONS),
                key="suggestion_v2",
                label_visibility="collapsed",
                wrap=True,
            )
            if selected:
                prompt = SUGGESTIONS[selected]

    chat_prompt = st.chat_input(
        "Pergunte sobre citações, referências ou formatação ABNT...",
        key="chat_input_v2",
        submit_mode="disable",
    )
    if chat_prompt:
        prompt = chat_prompt
    if not prompt or not prompt.strip():
        return

    prompt = prompt.strip()
    history = list(st.session_state.messages_v2)
    st.session_state.messages_v2.append({"role": "user", "content": prompt})
    _render_conversation_summary(conversation_summary, st.session_state.messages_v2)
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
                result = invoke_agent(
                    prompt,
                    history,
                    conversation_id=st.session_state.conversation_id_v2,
                )
        except Exception as exc:
            status.update(label="Não foi possível concluir a consulta", state="error")
            st.error(f"Não foi possível consultar o agente: {exc}")
            return

        status.update(label="Consulta concluída", state="complete")
        answer = str(result.get("answer") or "")
        if not answer:
            status.update(label="Não foi possível concluir a consulta", state="error")
            st.error("Não foi possível consultar o agente: resposta vazia.")
            return
        presentation = _presentation_record(result)
        st.markdown(answer)
        _render_presentation(presentation, answer)

    st.session_state.messages_v2.append(
        {
            "role": "assistant",
            "content": answer,
            "turn_id": presentation.get("turn_id"),
            "presentation": presentation,
        }
    )
    _render_conversation_summary(conversation_summary, st.session_state.messages_v2)


if __name__ == "__main__":
    main()
