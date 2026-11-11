"""Interface Streamlit independente para o agente V2."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.agente_v2.orchestrator import AgentV2  # noqa: E402


def _agent() -> AgentV2:
    if "agent_v2" not in st.session_state:
        st.session_state.agent_v2 = AgentV2()
    return st.session_state.agent_v2


def _presentation_record(result: dict) -> dict:
    return {
        "turn_id": result.get("turn_id"),
        "limitations": list(result.get("limitations") or ()),
        "published_evidence_ids": list(result.get("published_evidence_ids") or ()),
        "evidences": [
            dict(evidence)
            for evidence in result.get("evidences") or ()
            if isinstance(evidence, dict)
        ],
    }


def _render_presentation(record: dict, answer: str = "") -> None:
    limitations = [
        limitation
        for limitation in record.get("limitations") or ()
        if str(limitation).strip() != answer.strip()
    ]
    if limitations:
        st.caption("Limitações: " + " ".join(limitations))
    published_ids = set(record.get("published_evidence_ids") or ())
    evidences = [
        evidence
        for evidence in record.get("evidences") or ()
        if evidence.get("evidence_id") in published_ids
    ]
    if evidences:
        with st.expander("Evidências documentais"):
            for evidence in evidences:
                st.markdown(
                    f"**{evidence.get('title', 'Documento')}** — "
                    f"p. {evidence.get('page_number', '?')}\n\n"
                    f"> {evidence.get('text', '')}"
                )


def main() -> None:
    st.set_page_config(page_title="Agente Acadêmico V2", page_icon="📚")
    st.title("Agente Acadêmico V2")
    if "conversation_id_v2" not in st.session_state:
        st.session_state.conversation_id_v2 = uuid4().hex
    if "messages_v2" not in st.session_state:
        st.session_state.messages_v2 = []
    if "presentation_v2" not in st.session_state:
        st.session_state.presentation_v2 = []
    if st.button("Nova conversa"):
        st.session_state.conversation_id_v2 = uuid4().hex
        st.session_state.messages_v2 = []
        st.session_state.presentation_v2 = []
        st.rerun()
    assistant_index = 0
    for message in st.session_state.messages_v2:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                if assistant_index < len(st.session_state.presentation_v2):
                    _render_presentation(
                        st.session_state.presentation_v2[assistant_index],
                        message["content"],
                    )
                assistant_index += 1
    question = st.chat_input("Pergunte sobre as normas acadêmicas")
    if not question:
        return
    st.session_state.messages_v2.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Consultando as evidências..."):
            result = _agent().invoke(
                {
                    "conversation_id": st.session_state.conversation_id_v2,
                    "messages": st.session_state.messages_v2,
                }
            )
        st.markdown(result["answer"])
        presentation = _presentation_record(result)
        st.session_state.presentation_v2.append(presentation)
        _render_presentation(presentation, result["answer"])
    st.session_state.messages_v2 = result["messages"]


if __name__ == "__main__":
    main()
