"""Verificação suplementar isolada; não muda os testes ou o código de produção."""

import ast
import copy
import importlib
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.app import agente
from src.app.evidence import _normalize_content
from src.app.grounding import INSUFFICIENT_EVIDENCE

QUESTION = "Qual a margem do TCC segundo a ABNT?"
SOURCE = "O título deve usar fonte de 12 pontos."


@pytest.mark.parametrize(
    "content,expected",
    [
        ("  citação  ", "citação"),
        (None, ""),
        ([], ""),
        (["um", " ", {"type": "text", "text": "dois"}], "um\ndois"),
        ([{"content": "citação"}], "citação"),
        ([{"text": ""}], ""),
        ([{"text": 123}, None, 8], ""),
        (["um", {"content": " dois "}], "um\ndois"),
        (16, "16"),
    ],
)
def test_normalizer_reused_by_new_agent_paths(content, expected):
    assert _normalize_content(content) == expected
    assert agente.ScopedAgent(None)._content_text(content) == expected


@pytest.fixture
def cli(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "src" / "terminal"))
    return importlib.import_module("src.terminal.main")


class UnsafeInner:
    def invoke(self, payload):
        return {
            "messages": [
                *payload["messages"],
                {"role": "assistant", "content": "A margem deve medir 7 cm."},
            ]
        }


@pytest.mark.parametrize("mode", ["prompt", "interactive"])
def test_old_cli_entry_points_publish_new_grounding_decision(cli, monkeypatch, mode):
    answers = []
    inputs = iter([QUESTION, "/sair"])
    console = SimpleNamespace(
        status=lambda *a, **kw: nullcontext(),
        input=lambda *a: next(inputs),
        print=lambda *a, **kw: None,
    )
    monkeypatch.setattr(cli, "console", console)
    monkeypatch.setattr(cli, "print_banner", lambda: None)
    monkeypatch.setattr(cli, "print_info", lambda *_: None)
    monkeypatch.setattr(cli, "print_answer", answers.append)
    monkeypatch.setattr(cli, "load_agent", lambda: agente.ScopedAgent(UnsafeInner()))
    assert cli.main(["--prompt", QUESTION] if mode == "prompt" else []) == 0
    assert answers == [INSUFFICIENT_EVIDENCE]


def test_old_cli_reports_agent_loading_failure(cli, monkeypatch):
    errors = []

    def fail():
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(cli, "load_agent", fail)
    monkeypatch.setattr(cli, "print_error", lambda title, error: errors.append(error))
    assert cli.main(["--prompt", QUESTION]) == 1
    assert str(errors[0]) == "fixture failure"


def test_old_loader_returns_actual_current_agent_module(cli):
    assert cli.load_agente_module() is agente
    assert hasattr(cli.load_agent(), "invoke")


def test_old_loader_wraps_import_failure(cli, monkeypatch):
    monkeypatch.delitem(sys.modules, cli.AGENTE_MODULE)
    monkeypatch.setattr(cli, "load_dotenv", lambda *_: None)

    def fail(name):
        assert name == cli.AGENTE_MODULE
        raise ImportError("fixture missing dependency")

    monkeypatch.setattr(cli.importlib, "import_module", fail)
    with pytest.raises(RuntimeError) as error:
        cli.load_agente_module()
    assert isinstance(error.value.__cause__, ImportError)


def test_old_loader_reports_missing_file(cli, monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, cli.AGENTE_MODULE)
    monkeypatch.setattr(cli, "AGENTE_PATH", tmp_path / "missing.py")
    with pytest.raises(RuntimeError, match="nao encontrado"):
        cli.load_agente_module()


@pytest.mark.parametrize("name", ["_verify_claims", "_synthesize_from_retrieval"])
def test_ascii_mutants_preserve_json_data_but_change_model_input(name):
    tree = ast.parse(Path(agente.__file__).read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    method = next(
        n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    wire_texts = []
    parsed_data = []
    for ascii_mode in [False, True]:
        variant = copy.deepcopy(method)
        switches = [
            k
            for n in ast.walk(variant)
            if isinstance(n, ast.Call)
            for k in n.keywords
            if k.arg == "ensure_ascii"
        ]
        assert len(switches) == 1
        switches[0].value = ast.Constant(ascii_mode)
        module = ast.fix_missing_locations(ast.Module(body=[variant], type_ignores=[]))
        namespace = dict(vars(agente))
        exec(compile(module, "<isolated-ascii-variant>", "exec"), namespace)
        calls = []

        def invoke(messages, calls=calls):
            calls.append(messages)
            return SimpleNamespace(content=SOURCE)

        scoped = agente.ScopedAgent(None, SimpleNamespace(invoke=invoke))
        evidence = {"e1": {"evidence_id": "e1", "text": SOURCE + "\nCitação: ç 😀"}}
        if name == "_verify_claims":
            namespace[name](scoped, QUESTION, [SOURCE], evidence)
            wire = calls[0][-1]["content"]
        else:
            payload = {"messages": [{"role": "user", "content": QUESTION}]}
            result = {
                "messages": [
                    *payload["messages"],
                    {
                        "role": "tool",
                        "name": "rag_document_search",
                        "content": json.dumps(
                            {
                                "status": "success",
                                "documents": [{"evidence": list(evidence.values())}],
                            }
                        ),
                    },
                ]
            }
            output = namespace[name](scoped, payload, result)
            assert output["messages"][-1]["content"] == SOURCE
            wire = calls[0][-1]["content"].split("Contexto RAG recuperado:\n", 1)[1]
        assert len(calls) == 1
        wire_texts.append(wire)
        parsed_data.append(json.loads(wire))
    assert parsed_data[0] == parsed_data[1]
    assert wire_texts[0] != wire_texts[1]
    assert "ç" in wire_texts[0] and r"\u00e7" in wire_texts[1]
