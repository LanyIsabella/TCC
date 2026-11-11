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
        return False


class _FakeStreamlit:
    def __init__(self, questions):
        self.session_state = _SessionState()
        self.events = []
        self._questions = iter(questions)

    def set_page_config(self, **_kwargs):
        pass

    def title(self, value):
        self.events.append(("title", value))

    def button(self, _label):
        return False

    def rerun(self):
        raise AssertionError("rerun inesperado")

    def chat_message(self, role):
        self.events.append(("chat_message", role))
        return _RenderContext(self.events, role)

    def chat_input(self, _label):
        return next(self._questions)

    def markdown(self, value):
        self.events.append(("markdown", value))

    def spinner(self, _label):
        return _RenderContext(self.events, "spinner")

    def caption(self, value):
        self.events.append(("caption", value))

    def expander(self, _label):
        return _RenderContext(self.events, "expander")


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
            "limitations": [f"Limitação {self.calls}"],
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
