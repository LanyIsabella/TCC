from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROLE_BY_MESSAGE_TYPE = {
    "ai": "assistant",
    "assistant": "assistant",
    "human": "user",
    "user": "user",
    "system": "system",
    "tool": "tool",
}


def make_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(key): make_jsonable(item) for key, item in value.items()}

    if isinstance(value, list | tuple | set):
        return [make_jsonable(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return make_jsonable(model_dump())
        except TypeError:
            pass

    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        try:
            return make_jsonable(dict_method())
        except TypeError:
            pass

    return str(value)


def serialize_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        role = message.get("role")
        if not isinstance(role, str):
            role = "unknown"

        return {
            "role": role,
            "content": make_jsonable(message.get("content")),
            "raw": make_jsonable(message),
        }

    message_type = getattr(message, "type", message.__class__.__name__.lower())
    role = ROLE_BY_MESSAGE_TYPE.get(message_type, message_type)

    return {
        "role": role,
        "message_type": message_type,
        "id": make_jsonable(getattr(message, "id", None)),
        "name": make_jsonable(getattr(message, "name", None)),
        "content": make_jsonable(getattr(message, "content", None)),
        "additional_kwargs": make_jsonable(getattr(message, "additional_kwargs", None)),
        "response_metadata": make_jsonable(getattr(message, "response_metadata", None)),
        "tool_calls": make_jsonable(getattr(message, "tool_calls", None)),
        "invalid_tool_calls": make_jsonable(
            getattr(message, "invalid_tool_calls", None)
        ),
        "usage_metadata": make_jsonable(getattr(message, "usage_metadata", None)),
        "raw": make_jsonable(message),
    }


def serialize_messages(messages: list[Any]) -> list[dict[str, Any]]:
    return [serialize_message(message) for message in messages]


def resolve_export_path(raw_path: str | Path | None, repo_root: Path) -> Path:
    if raw_path is None or not str(raw_path).strip():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = repo_root / "exports" / f"chat_history_{timestamp}.json"
    else:
        cleaned = str(raw_path).strip().strip('"').strip("'")
        path = Path(cleaned)
        if not path.is_absolute():
            path = repo_root / path
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def export_session_history(
    *,
    history_entries: list[dict[str, Any]],
    context_messages: list[Any],
    repo_root: Path,
    output_path: str | Path | None = None,
) -> Path:
    destination = resolve_export_path(output_path, repo_root)
    payload = {
        "exported_at": datetime.now().astimezone().isoformat(),
        "history_entry_count": len(history_entries),
        "context_message_count": len(context_messages),
        "history": make_jsonable(history_entries),
        "context_messages": serialize_messages(context_messages),
    }

    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination
