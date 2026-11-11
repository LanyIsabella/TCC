from __future__ import annotations

import argparse
import importlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from history_export import export_session_history
from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = REPO_ROOT / "src" / "app"
AGENTE_PATH = APP_DIR / "agente.py"
AGENTE_MODULE = "src.app.agente"
EXIT_COMMANDS = {"/sair", "sair", "exit", "quit"}
EXPORT_COMMANDS = {"/exportar", "/export"}
console = Console(
    theme=Theme(
        {
            "assistant": "bold bright_green",
            "error": "bold bright_red",
            "info": "bold bright_cyan",
            "muted": "dim white",
            "success": "bold bright_green",
            "user": "bold bright_blue",
            "warning": "bold bright_yellow",
        }
    )
)


def ensure_repo_path() -> None:
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def load_agente_module() -> Any:
    cached_module = sys.modules.get(AGENTE_MODULE)
    if cached_module is not None:
        return cached_module

    if not AGENTE_PATH.exists():
        msg = f"Arquivo do agente nao encontrado em: {AGENTE_PATH}"
        raise RuntimeError(msg)

    load_dotenv(REPO_ROOT / ".env")
    ensure_repo_path()

    try:
        return importlib.import_module(AGENTE_MODULE)
    except Exception as exc:
        msg = f"Nao foi possivel carregar o modulo do agente em: {AGENTE_PATH}"
        raise RuntimeError(msg) from exc


def load_agent() -> Any:
    module = load_agente_module()
    agent = getattr(module, "agent", None)

    if agent is None or not hasattr(agent, "invoke"):
        msg = "O modulo src/app/agente.py nao expoe um objeto 'agent' utilizavel."
        raise RuntimeError(msg)

    return agent


def normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue

            if isinstance(item, dict):
                for key in ("text", "content"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        parts.append(value.strip())
                        break

        if parts:
            return "\n".join(parts)

    return str(content).strip()


def render_commands_table() -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="info", no_wrap=True)
    table.add_column(style="muted")
    table.add_row("/ajuda", "mostra os comandos disponiveis")
    table.add_row("/exportar [arquivo]", "salva o historico da sessao em JSON")
    table.add_row("/limpar", "reinicia o contexto da conversa")
    table.add_row("/sair", "encerra o chatbot")
    return table


def render_message_panel(title: str, body: Any, style: str) -> Panel:
    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=style,
        box=box.ROUNDED,
        padding=(1, 2),
    )


def print_info(message: str) -> None:
    console.print(Text(message, style="info"))


def print_success(message: str) -> None:
    console.print(Panel.fit(Text(message, style="success"), border_style="success"))


def print_error(title: str, error: Exception | str) -> None:
    message = error if isinstance(error, str) else str(error)
    console.print(
        render_message_panel(title, Text(message, style="error"), style="error")
    )


def print_answer(answer: str) -> None:
    console.print(
        render_message_panel(
            "[assistant]Assistente[/assistant]",
            Markdown(answer, code_theme="monokai"),
            style="assistant",
        )
    )


def format_grounding_result(result: Any) -> str:
    """Renderiza apenas a proveniência pública e o estado de fundamentação."""

    labels = {
        "supported": "Fundamentação: apoiada",
        "partial": "Fundamentação: parcial",
        "unsupported": "Fundamentação: não fundamentada",
        "conversational": "Fundamentação: conversacional",
    }
    lines = [labels.get(result.grounding_status, "Fundamentação: não fundamentada")]
    for limitation in result.limitations:
        lines.append(f"Limitação: {limitation}")

    from src.app.evidence import public_evidence

    for evidence in result.evidences:
        public = public_evidence(evidence)
        location = ", ".join(
            str(value)
            for value in (
                public.get("title"),
                public.get("standard_id"),
                public.get("version"),
                f"p. {public['page_number']}" if public.get("page_number") else None,
            )
            if value
        )
        lines.append(f"Evidência {public.get('evidence_id', 'sem id')}: {location}")
        lines.append(f"  {public.get('text', '')}")
        for field in ("turn_id", "tool_call_id", "execution_id"):
            if public.get(field):
                lines.append(f"  {field}: {public[field]}")
        if public.get("omitted_content"):
            lines.append(f"  Conteúdo omitido: {public['omitted_content']}")
    return "\n".join(lines)


def print_grounding_result(result: Any) -> None:
    status = getattr(result, "grounding_status", "unsupported")
    style = "success" if status == "supported" else "warning"
    console.print(
        render_message_panel(
            "[info]Fundamentação[/info]",
            Text(format_grounding_result(result)),
            style=style,
        )
    )


class ChatSession:
    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self.messages: list[Any] = []
        self.history: list[dict[str, Any]] = []
        self.last_result: Any | None = None

    def _timestamp(self) -> str:
        return datetime.now().astimezone().isoformat()

    def clear(self) -> None:
        self.history.append(
            {
                "entry_type": "event",
                "timestamp": self._timestamp(),
                "event": "context_cleared",
                "cleared_message_count": len(self.messages),
            }
        )
        self.messages.clear()

    def ask(self, question: str) -> str:
        self.last_result = None
        self.history.append(
            {
                "entry_type": "message",
                "role": "user",
                "timestamp": self._timestamp(),
                "content": question,
            }
        )
        payload = {"messages": [*self.messages, {"role": "user", "content": question}]}
        try:
            result = self.agent.invoke(payload)
        except Exception as exc:
            self.history.append(
                {
                    "entry_type": "error",
                    "timestamp": self._timestamp(),
                    "stage": "invoke",
                    "message": str(exc),
                }
            )
            raise

        from src.app.evidence import extract_agent_result, public_evidence

        try:
            if not isinstance(result, dict):
                raise RuntimeError("O agente retornou um formato de resposta invalido.")
            messages = result.get("messages")
            if not isinstance(messages, list) or not messages:
                raise RuntimeError("O agente retornou uma resposta sem mensagens.")
            extracted = extract_agent_result(result, question=question)
            self.last_result = extracted
            reply = extracted.answer
        except RuntimeError as exc:
            self.history.append(
                {
                    "entry_type": "error",
                    "timestamp": self._timestamp(),
                    "stage": "validation",
                    "message": str(exc),
                }
            )
            raise
        self.messages = messages

        assistant_entry = {
            "entry_type": "message",
            "role": "assistant",
            "timestamp": self._timestamp(),
            "content": reply,
            "grounding_status": extracted.grounding_status,
            "limitations": list(extracted.limitations),
            "evidences": [
                public_evidence(evidence) for evidence in extracted.evidences
            ],
        }
        self.history.append(assistant_entry)
        return reply

    def export_history(self, output_path: str | Path | None = None) -> Path:
        return export_session_history(
            history_entries=self.history,
            context_messages=self.messages,
            repo_root=REPO_ROOT,
            output_path=output_path,
        )


def print_banner() -> None:
    header = Group(
        Text("Chatbot CLI", style="bold white"),
        Text(
            "Conectado diretamente a src/app/agente.py",
            style="muted",
        ),
        Text(""),
        render_commands_table(),
    )

    if console.is_terminal:
        console.clear()

    console.print(render_message_panel("[info]Terminal[/info]", header, style="info"))


def print_help() -> None:
    body = Group(
        Text("Digite sua pergunta e pressione Enter.", style="muted"),
        Text(""),
        render_commands_table(),
    )
    console.print(render_message_panel("[info]Ajuda[/info]", body, style="info"))


def run_interactive(session: ChatSession) -> None:
    print_banner()

    while True:
        try:
            user_input = console.input("[user]Voce[/user] [muted]> [/muted]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            print_info("Encerrando chatbot.")
            return

        if not user_input:
            continue

        lowered = user_input.lower()
        if lowered in EXIT_COMMANDS:
            print_info("Encerrando chatbot.")
            return
        command, _, remainder = user_input.partition(" ")
        if command.lower() in EXPORT_COMMANDS:
            try:
                export_path = session.export_history(remainder.strip() or None)
            except Exception as exc:
                print_error("[error]Erro ao exportar o historico[/error]", exc)
                continue

            print_success(f"Historico exportado para: {export_path}")
            continue
        if lowered == "/limpar":
            session.clear()
            print_success("Contexto limpo.")
            continue
        if lowered in {"/ajuda", "/help", "help"}:
            print_help()
            continue

        try:
            with console.status("[info]Consultando agente...[/info]", spinner="dots"):
                answer = session.ask(user_input)
        except Exception as exc:
            print_error("[error]Erro ao consultar o agente[/error]", exc)
            continue

        print_answer(answer)
        if session.last_result is not None:
            print_grounding_result(session.last_result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CLI para conversar com o agente definido em src/app/agente.py."
    )
    parser.add_argument(
        "-p",
        "--prompt",
        help="Envia uma unica pergunta para o agente e encerra.",
    )
    parser.add_argument(
        "--export-history",
        nargs="?",
        const="",
        metavar="ARQUIVO",
        help="Exporta o historico da sessao em JSON. Sem caminho, usa exports/.",
    )
    args = parser.parse_args(argv)

    try:
        with console.status("[info]Carregando agente...[/info]", spinner="dots"):
            session = ChatSession(load_agent())
    except Exception as exc:
        print_error("[error]Falha ao carregar o agente[/error]", exc)
        return 1

    if args.prompt:
        try:
            with console.status("[info]Consultando agente...[/info]", spinner="dots"):
                answer = session.ask(args.prompt)
            print_answer(answer)
            if session.last_result is not None:
                print_grounding_result(session.last_result)
            if args.export_history is not None:
                export_path = session.export_history(args.export_history or None)
                print_success(f"Historico exportado para: {export_path}")
            return 0
        except Exception as exc:
            print_error("[error]Erro ao consultar o agente[/error]", exc)
            return 1

    run_interactive(session)
    if args.export_history is not None:
        try:
            export_path = session.export_history(args.export_history or None)
            print_success(f"Historico exportado para: {export_path}")
        except Exception as exc:
            print_error("[error]Erro ao exportar o historico[/error]", exc)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
