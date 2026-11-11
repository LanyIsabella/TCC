"""Interface Streamlit independente para o agente V2."""

from __future__ import annotations

from uuid import uuid4

import streamlit as st

from .orchestrator import AgentV2


def _agent() -> AgentV2:
    if "agent_v2" not in st.session_state:
        st.session_state.agent_v2 = AgentV2()
    return st.session_state.agent_v2


def main() -> None:
    st.set_page_config(page_title="Agente Acadêmico V2", page_icon="📚")
    st.title("Agente Acadêmico V2")
    if "conversation_id_v2" not in st.session_state:
        st.session_state.conversation_id_v2 = uuid4().hex
    if "messages_v2" not in st.session_state:
        st.session_state.messages_v2 = []
    if st.button("Nova conversa"):
        st.session_state.conversation_id_v2 = uuid4().hex
        st.session_state.messages_v2 = []
        st.rerun()
    for message in st.session_state.messages_v2:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    question = st.chat_input("Pergunte sobre as normas acadêmicas")
    if not question:
        return
    st.session_state.messages_v2.append({"role": "user", "content": question})
    with st.chat_message("assistant"):
        with st.spinner("Consultando as evidências..."):
            result = _agent().invoke(
                {
                    "conversation_id": st.session_state.conversation_id_v2,
                    "messages": st.session_state.messages_v2,
                }
            )
        st.markdown(result["answer"])
        if result["limitations"]:
            st.caption("Limitações: " + " ".join(result["limitations"]))
        evidences = result["evidences"]
        if evidences:
            with st.expander("Evidências documentais"):
                for evidence in evidences:
                    st.markdown(
                        f"**{evidence.get('title', 'Documento')}** — "
                        f"p. {evidence.get('page_number', '?')}\n\n"
                        f"> {evidence.get('text', '')}"
                    )
    st.session_state.messages_v2 = result["messages"]


if __name__ == "__main__":
    main()
