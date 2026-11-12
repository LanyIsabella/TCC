"""Testes headless da apresentação documental no chat."""

import subprocess
import sys
from pathlib import Path

from src.app.agente_v2 import streamlit_app as v2_streamlit_app
from streamlit.testing.v1 import AppTest


class _SessionState(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class _RenderContext:
    def __init__(self, events, kind):
        self._events = events
        self._kind = kind

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._kind in {"user", "assistant"}:
            self._events.append(("chat_message_end", self._kind))
        return False

    def container(self, **_kwargs):
        return self

    def update(self, **kwargs):
        self._events.append(("status_update", kwargs))


class _FakeStreamlit:
    def __init__(self, questions, buttons=None, pills=None):
        self.session_state = _SessionState()
        self.events = []
        self._questions = iter(questions)
        self._buttons = iter(buttons or [])
        self._pills = iter(pills or [])
        self.sidebar = _RenderContext(self.events, "sidebar")

    def set_page_config(self, **kwargs):
        self.events.append(("page_config", kwargs))

    def title(self, value, **_kwargs):
        self.events.append(("title", value))

    def button(self, label, on_click=None, **_kwargs):
        clicked = next(self._buttons, False)
        if clicked and on_click is not None:
            on_click()
        self.events.append(("button", label, clicked))
        return clicked

    def rerun(self):
        raise AssertionError("rerun inesperado")

    def chat_message(self, role, **_kwargs):
        self.events.append(("chat_message", role))
        return _RenderContext(self.events, role)

    def chat_input(self, _label, **_kwargs):
        return next(self._questions)

    def markdown(self, value, **_kwargs):
        self.events.append(("markdown", value))

    def status(self, label, **_kwargs):
        self.events.append(("status", label))
        return _RenderContext(self.events, "status")

    def caption(self, value):
        self.events.append(("caption", value))

    def expander(self, _label, **_kwargs):
        return _RenderContext(self.events, "expander")

    def container(self, **_kwargs):
        return _RenderContext(self.events, "container")

    def empty(self):
        return _RenderContext(self.events, "empty")

    def subheader(self, value):
        self.events.append(("subheader", value))

    def pills(self, *_args, **_kwargs):
        return next(self._pills, None)

    def divider(self):
        self.events.append(("divider",))

    def error(self, value):
        self.events.append(("error", value))


class _FakeAgent:
    def __init__(self, events):
        self.events = events

    def invoke(self, payload):
        self.events.append(("invoke", payload["messages"][-1]["content"]))
        return {
            "answer": "Resposta",
            "limitations": [],
            "evidences": [],
            "messages": [
                *payload["messages"],
                {"role": "assistant", "content": "Resposta"},
            ],
        }


class _MetadataAgent:
    def __init__(self, events):
        self.events = events
        self.calls = 0

    def invoke(self, payload):
        self.calls += 1
        evidence_id = f"document:{self.calls}:page:1"
        self.events.append(("invoke", payload["messages"][-1]["content"]))
        return {
            "answer": f"Resposta {self.calls}",
            "limitations": [f"Limitação {self.calls}", f"Resposta {self.calls}"],
            "evidences": [
                {
                    "evidence_id": evidence_id,
                    "title": f"Norma {self.calls}",
                    "page_number": 1,
                    "text": f"Trecho {self.calls}",
                },
                {
                    "evidence_id": f"document:{self.calls}:page:2",
                    "title": "Não publicar",
                    "page_number": 2,
                    "text": "Evidência não selecionada",
                },
            ],
            "published_evidence_ids": [evidence_id],
            "messages": [
                *payload["messages"],
                {"role": "assistant", "content": f"Resposta {self.calls}"},
            ],
        }


def test_v2_streamlit_entrypoint_bootstraps_when_run_as_file(tmp_path: Path) -> None:
    app_path = (
        Path(__file__).parents[1]
        / "src"
        / "app"
        / "agente_v2"
        / "streamlit_app.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; runpy.run_path(sys.argv[1], run_name='streamlit_test')",
            str(app_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_v2_uses_v1_page_identity_and_initial_suggestions(monkeypatch) -> None:
    fake_st = _FakeStreamlit([None])
    monkeypatch.setattr(v2_streamlit_app, "st", fake_st)
    monkeypatch.setattr(v2_streamlit_app, "_agent", lambda: _FakeAgent(fake_st.events))

    v2_streamlit_app.main()

    config = next(event[1] for event in fake_st.events if event[0] == "page_config")
    assert config == {
        "page_title": "Normas Acadêmicas",
        "page_icon": ":material/menu_book:",
        "layout": "wide",
        "initial_sidebar_state": "expanded",
    }
    assert ("title", "Normas Acadêmicas") in fake_st.events
    assert ("subheader", "Comece por uma pergunta") in fake_st.events
    assert ("button", "Nova conversa", False) in fake_st.events


def test_v2_initial_screen_headless() -> None:
    app_path = (
        Path(__file__).parents[1]
        / "src"
        / "app"
        / "agente_v2"
        / "streamlit_app.py"
    )
    app = AppTest.from_file(app_path, default_timeout=10).run()

    assert not app.exception
    assert any(item.value == "Normas Acadêmicas" for item in app.title)
    assert any(item.value == "Comece por uma pergunta" for item in app.subheader)
    assert app.chat_input[0].placeholder == (
        "Pergunte sobre citações, referências ou formatação ABNT..."
    )
    assert any(button.label == "Nova conversa" for button in app.button)


def test_v2_initial_suggestion_submits_to_agent(monkeypatch) -> None:
    selected = next(iter(v2_streamlit_app.SUGGESTIONS))
    fake_st = _FakeStreamlit([None], pills=[selected])
    fake_agent = _FakeAgent(fake_st.events)
    monkeypatch.setattr(v2_streamlit_app, "st", fake_st)
    monkeypatch.setattr(v2_streamlit_app, "_agent", lambda: fake_agent)

    v2_streamlit_app.main()

    assert ("invoke", v2_streamlit_app.SUGGESTIONS[selected]) in fake_st.events


def test_v2_presentation_never_promotes_unpublished_evidence() -> None:
    record = v2_streamlit_app._presentation_record(
        {
            "answer": "Resposta sem suporte",
            "evidences": [
                {
                    "evidence_id": "rejected",
                    "title": "Não publicar",
                    "text": "Trecho rejeitado",
                }
            ],
            "published_evidence_ids": [],
        }
    )

    assert record["evidences"] == []


def test_v2_keeps_source_label_with_each_published_evidence(monkeypatch) -> None:
    fake_st = _FakeStreamlit([None])
    monkeypatch.setattr(v2_streamlit_app, "st", fake_st)

    v2_streamlit_app._render_document_references(
        [
            {
                "evidence_id": "document:1:page:5",
                "title": "ABNT NBR 10520",
                "version": "2023",
                "page_number": 5,
                "text": "Trecho da primeira norma.",
            },
            {
                "evidence_id": "document:2:page:5",
                "title": "ABNT NBR 6023",
                "version": "2023",
                "page_number": 5,
                "text": "Trecho da segunda norma.",
            },
        ]
    )

    captions = [event[1] for event in fake_st.events if event[0] == "caption"]
    assert "ABNT NBR 10520 (2023)" in captions
    assert "ABNT NBR 6023 (2023)" in captions


def test_v2_new_conversation_resets_visual_context_and_id(monkeypatch) -> None:
    fake_st = _FakeStreamlit([None, None], buttons=[False, True])
    fake_agent = _FakeAgent(fake_st.events)
    monkeypatch.setattr(v2_streamlit_app, "st", fake_st)
    monkeypatch.setattr(v2_streamlit_app, "_agent", lambda: fake_agent)

    v2_streamlit_app.main()
    first_id = fake_st.session_state.conversation_id_v2
    fake_st.session_state.messages_v2 = [
        {
            "role": "assistant",
            "content": "Resposta",
            "turn_id": "turn-1",
            "presentation": {"published_evidence_ids": ["e1"]},
        }
    ]
    fake_st.session_state.suggestion_v2 = "selected"

    v2_streamlit_app.main()

    assert fake_st.session_state.conversation_id_v2 != first_id
    assert fake_st.session_state.messages_v2 == []
    assert "suggestion_v2" not in fake_st.session_state


def test_v2_renders_submitted_user_message_once_before_agent_call(monkeypatch) -> None:
    fake_st = _FakeStreamlit(["Como citar?", None])
    fake_agent = _FakeAgent(fake_st.events)
    monkeypatch.setattr(v2_streamlit_app, "st", fake_st)
    monkeypatch.setattr(v2_streamlit_app, "_agent", lambda: fake_agent)

    v2_streamlit_app.main()
    first_run = list(fake_st.events)
    invoke_index = first_run.index(("invoke", "Como citar?"))
    user_index = first_run.index(("chat_message", "user"))

    assert user_index < invoke_index
    assert first_run.count(("chat_message", "user")) == 1

    v2_streamlit_app.main()
    second_run = fake_st.events[len(first_run) :]

    assert second_run.count(("chat_message", "user")) == 1
    assert not any(event[0] == "invoke" for event in second_run)


def test_v2_persists_turn_metadata_across_rerun_and_new_question(monkeypatch) -> None:
    fake_st = _FakeStreamlit(["Primeira pergunta", "Segunda pergunta", None])
    fake_agent = _MetadataAgent(fake_st.events)
    monkeypatch.setattr(v2_streamlit_app, "st", fake_st)
    monkeypatch.setattr(v2_streamlit_app, "_agent", lambda: fake_agent)

    v2_streamlit_app.main()
    first_run_size = len(fake_st.events)
    v2_streamlit_app.main()
    second_run_size = len(fake_st.events)
    v2_streamlit_app.main()
    third_run = fake_st.events[second_run_size:]

    assert fake_agent.calls == 2
    assert any(
        "Limitação 1" in event[1]
        for event in third_run
        if event[0] == "caption"
    )
    assert any(
        "Trecho 1" in event[1]
        for event in third_run
        if event[0] == "markdown"
    )
    assert any(
        "Limitação 2" in event[1]
        for event in third_run
        if event[0] == "caption"
    )
    assert not any(
        "Resposta 1" in event[1] or "Resposta 2" in event[1]
        for event in third_run
        if event[0] == "caption"
    )
    for index, event in enumerate(third_run):
        if event[0] == "caption" and "Limitação" in event[1]:
            assert any(
                prior == ("chat_message", "assistant")
                for prior in third_run[:index]
            )
            assert any(
                following == ("chat_message_end", "assistant")
                for following in third_run[index + 1 :]
            )
    assert any(
        "Trecho 2" in event[1]
        for event in third_run
        if event[0] == "markdown"
    )
    assert not any(
        "Não publicar" in event[1]
        for event in third_run
        if event[0] == "markdown"
    )
    assert not any(event[0] == "invoke" for event in third_run)
    assert first_run_size < second_run_size


def test_assistant_history_renders_reference_and_collapsed_evidence() -> None:
    app_path = Path(__file__).parents[1] / "src" / "ui" / "app.py"
    app = AppTest.from_file(app_path, default_timeout=10).run()
    app.session_state["messages"] = [
        {"role": "user", "content": "O que é uma referência?"},
        {
            "role": "assistant",
            "content": "Uma referência identifica a obra consultada.",
            "evidences": [
                {
                    "evidence_id": "document:42:page:4",
                    "document_id": 8,
                    "title": "ABNT NBR 6023",
                    "version": "2023",
                    "page_number": 4,
                    "section": "Referências",
                    "text": "A referência identifica a obra consultada.",
                    "matched_text": "A referência identifica a obra consultada.",
                }
            ],
        },
    ]

    app.run()

    assert not app.exception
    assert any(
        "Documento de referência" in item.value for item in app.caption
    )
    assert not any("Página:" in item.value for item in app.caption)
    assert app.status[0].label == (
        ":material/check_circle: Trechos que sustentam a resposta"
    )
    assert app.status[0].proto.expanded is False
    assert any(
        "A referência identifica a obra consultada." in item.value
        for item in app.markdown
    )
