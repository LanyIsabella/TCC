from __future__ import annotations

from data.run_pipeline import PipelineOptions, build_pipeline_steps, run_pipeline


def test_pipeline_steps_follow_the_required_order() -> None:
    steps = build_pipeline_steps(PipelineOptions(document_id=8))

    assert [step.name for step in steps] == [
        "bronze",
        "init-db",
        "extract",
        "evaluate",
        "activate",
        "embed",
        "validate",
    ]


def test_pipeline_commands_propagate_document_and_resume_flags() -> None:
    options = PipelineOptions(
        document_id=8,
        retry_errors=True,
        force=True,
        skip_bronze=True,
        direct_glm_ocr=True,
    )

    steps = build_pipeline_steps(options)
    commands = {step.name: step.command for step in steps}

    assert "bronze" not in commands
    assert commands["extract"][-4:] == (
        "--extractor",
        "all",
        "--retry-errors",
        "--force",
    )
    assert commands["evaluate"][-3:] == (
        "--extractor",
        "all",
        "--retry-errors",
    )
    assert commands["activate"][-1] == "8"
    assert "--extractor" not in commands["activate"]
    assert commands["embed"][-3:] == (
        "--document-id",
        "8",
        "--retry-errors",
    )
    assert commands["validate"][-2:] == ("--document-id", "8")


def test_pipeline_can_skip_individual_stages() -> None:
    options = PipelineOptions(
        document_id=8,
        skip_init_db=True,
        skip_extract=True,
        skip_evaluate=True,
        skip_activate=True,
        skip_embed=True,
        skip_validate=True,
    )

    steps = build_pipeline_steps(options)

    assert [step.name for step in steps] == ["bronze"]


def test_dry_run_does_not_need_database_for_activation_ids(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "data.run_pipeline.discover_document_ids",
        lambda _document_id: (_ for _ in ()).throw(
            AssertionError("dry-run não deve consultar a Bronze")
        ),
    )

    run_pipeline(PipelineOptions(dry_run=True, skip_bronze=True))

    assert "activate: (aguarda IDs da Bronze)" in capsys.readouterr().out
