"""Testes headless da apresentação documental no chat."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


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
