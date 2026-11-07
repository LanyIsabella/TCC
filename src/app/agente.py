import json
import re
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent

from .citation_validator import grounded_answer, supporting_excerpts
from .client import Client
from .prompt import load_prompt_sys
from .query_planner import is_broad_question
from .scope_guard import (
    ScopeDecision,
    classify_messages,
    guarded_response,
    normalize_text,
)
from .tools.rag_search import rag_document_search

NORMATIVE_TERMS = (
    "abnt",
    "norma",
    "citação",
    "citacao",
    "referência",
    "referencia",
    "formatação",
    "formatacao",
    "tcc",
    "sumário",
    "sumario",
    "resumo",
    "lombada",
    "seção",
    "secao",
)
STANDARD_PATTERN = re.compile(r"\b(?:ABNT\s+)?NBR\s+\d{4,5}\b", re.IGNORECASE)
PLACEHOLDER_RESPONSE_MARKERS = (
    "faca sua pergunta",
    "estou pronto para ajudar",
    "como posso ajudar",
    "como posso te auxiliar",
    "estou a disposicao para ajudar",
    "sou seu assistente",
)


class ScopedAgent:
    """Impede chamadas ao modelo para mensagens fora do escopo definido."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        decision = classify_messages(messages)
        if decision in {ScopeDecision.GREETING, ScopeDecision.OUT_OF_SCOPE}:
            return guarded_response(messages, decision)
        question = self._last_user_message(messages)
        if self._requires_normative_grounding(question) and is_broad_question(
            question
        ):
            evidence = self._recover_evidence(question)
            if evidence:
                return {
                    "messages": [
                        *messages,
                        {
                            "role": "assistant",
                            "content": self._extractive_fallback(evidence),
                        },
                    ]
                }
        result = self._agent.invoke(payload)
        evidence = self._extract_evidence(
            result.get("messages", []) if isinstance(result, dict) else []
        )
        if self._requires_normative_grounding(question) and not evidence:
            recovery_evidence = self._recover_evidence(question)
            if recovery_evidence:
                evidence.extend(recovery_evidence)
                assistant = self._last_assistant(
                    result.get("messages", []) if isinstance(result, dict) else []
                )
                if assistant is not None and self._is_placeholder_response(
                    self._content(assistant)
                ):
                    self._set_content(
                        assistant,
                        self._extractive_fallback(recovery_evidence),
                    )
        return self._ensure_normative_grounding(payload, result, evidence)

    def _ensure_normative_grounding(
        self,
        payload: dict[str, Any],
        result: Any,
        prefetched_evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Aplica a garantia de citação também no UI e no terminal."""
        if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
            return result
        question = self._last_user_message(payload.get("messages", []))
        if not any(term in question.casefold() for term in NORMATIVE_TERMS):
            return result

        evidence = [
            *(prefetched_evidence or []),
            *self._extract_evidence(result["messages"]),
        ]
        assistant = self._last_assistant(result["messages"])
        if assistant is None:
            return result
        raw_answer = self._content(assistant)
        if self._is_placeholder_response(raw_answer):
            self._set_content(
                assistant,
                "Não foi possível gerar uma resposta fundamentada para esta "
                "pergunta. A consulta foi tratada como acadêmica, mas o modelo "
                "não produziu uma resposta com base nos documentos recuperados.",
            )
            return result

        answer = grounded_answer(raw_answer, evidence, question)
        if not evidence:
            self._set_content(
                assistant,
                "Não localizei evidência suficiente nos documentos normativos "
                "disponíveis para responder com segurança.",
            )
        else:
            if not (
                "base normativa" in answer.casefold()
                and STANDARD_PATTERN.search(answer)
            ):
                answer = f"{answer.rstrip()}\n\n{self._citation_block(evidence[0])}"
            self._set_content(assistant, answer)
        return result

    def _requires_normative_grounding(self, question: str) -> bool:
        """Identifica perguntas que exigem recuperação documental."""
        normalized = question.casefold()
        return any(term in normalized for term in NORMATIVE_TERMS)

    def _recover_evidence(self, question: str) -> list[dict[str, Any]]:
        """Executa o RAG quando o modelo não produziu evidência própria."""
        try:
            raw_result = rag_document_search.invoke({"question": question})
            parsed = json.loads(raw_result)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, dict) or not parsed.get("evidence_found"):
            return []
        documents = parsed.get("documents")
        if not isinstance(documents, list):
            return []
        return [document for document in documents if isinstance(document, dict)]

    def _extractive_fallback(self, evidence: list[dict[str, Any]]) -> str:
        """Monta uma síntese legível a partir dos trechos normativos."""
        excerpts = supporting_excerpts(evidence, query=None, limit=8)
        if not excerpts:
            return (
                "Não foi possível sintetizar uma resposta a partir dos trechos "
                "recuperados nos documentos normativos."
            )
        lines = [
            "Os trechos normativos recuperados indicam os seguintes pontos "
            "relevantes para a formatação do trabalho:",
            "",
        ]
        for excerpt in excerpts:
            source = str(excerpt["standard"])
            if excerpt.get("version"):
                source += f":{excerpt['version']}"
            if excerpt.get("page"):
                source += f", p. {excerpt['page']}"
            lines.extend([f"> {excerpt['text']}", f"> Fonte: {source}", ""])
        return grounded_answer("\n".join(lines).rstrip(), evidence, query=None)

        points: list[str] = []
        categories: set[str] = set()
        for excerpt in excerpts:
            normalized = normalize_text(str(excerpt.get("text") or ""))
            if "fonte tamanho 12" in normalized and "fonte" not in categories:
                points.append(
                    "Fonte: recomenda-se tamanho 12 para o texto e para a capa. "
                    "Citações longas, notas, paginação, fontes e legendas podem "
                    "usar tamanho menor e uniforme."
                )
                categories.add("fonte")
            elif (
                "1,5" in normalized
                and "espaco" in normalized
                and "espacamento" not in categories
            ):
                points.append(
                    "Espaçamento: o texto deve usar 1,5 entre linhas; citações "
                    "longas, notas, referências, títulos, fontes e legendas usam "
                    "espaçamento simples."
                )
                categories.add("espacamento")
            elif (
                "elementos pre-textuais" in normalized
                and "estrutura" not in categories
            ):
                points.append(
                    "Estrutura: os elementos pré-textuais devem iniciar no anverso "
                    "da folha, enquanto elementos textuais e pós-textuais podem "
                    "ser apresentados no anverso e no verso."
                )
                categories.add("estrutura")
        if not points:
            points.append(
                "A norma recuperada define requisitos para a apresentação e a "
                "estrutura de trabalhos acadêmicos."
            )
        lines = [
            "Segundo a ABNT NBR 14724:2024, as principais regras de formatação "
            "de um TCC incluem:",
            "",
        ]
        lines.extend(f"- {point}" for point in points)
        return grounded_answer("\n".join(lines), evidence, query=None)

    def _is_placeholder_response(self, answer: str) -> bool:
        """Evita que uma saudação genérica seja aceita como resposta final."""
        normalized = " ".join(normalize_text(answer).split())
        return len(normalized) <= 500 and any(
            marker in normalized for marker in PLACEHOLDER_RESPONSE_MARKERS
        )

    def _last_user_message(self, messages: Any) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if self._role(message) == "user":
                return self._content(message)
        return ""

    def _extract_evidence(self, messages: list[Any]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for message in messages:
            if self._role(message) != "tool":
                continue
            try:
                tool_result = json.loads(self._content(message))
            except (TypeError, ValueError):
                continue
            if not isinstance(tool_result, dict) or not tool_result.get(
                "evidence_found"
            ):
                continue
            documents = tool_result.get("documents")
            if isinstance(documents, list):
                evidence.extend(doc for doc in documents if isinstance(doc, dict))
        return evidence

    def _last_assistant(self, messages: list[Any]) -> Any | None:
        for message in reversed(messages):
            if self._role(message) == "assistant" and self._content(message):
                return message
        return None

    def _role(self, message: Any) -> str:
        if isinstance(message, dict):
            return {"ai": "assistant", "human": "user"}.get(
                str(message.get("role") or message.get("type")),
                str(message.get("role") or message.get("type") or ""),
            )
        return {"ai": "assistant", "human": "user"}.get(
            str(getattr(message, "role", None) or getattr(message, "type", None)),
            str(getattr(message, "role", None) or getattr(message, "type", None) or ""),
        )

    def _content(self, message: Any) -> str:
        raw = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", "")
        )
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, list):
            return "\n".join(
                item
                if isinstance(item, str)
                else str(item.get("text") or item.get("content") or "")
                for item in raw
                if isinstance(item, str) or isinstance(item, dict)
            ).strip()
        return str(raw or "").strip()

    def _set_content(self, message: Any, content: str) -> None:
        if isinstance(message, dict):
            message["content"] = content
        else:
            message.content = content

    def _citation_block(self, document: dict[str, Any]) -> str:
        standard = str(
            document.get("standard_label")
            or document.get("standard_id")
            or document.get("title")
            or "Documento normativo"
        ).strip()
        version = str(document.get("version") or "").strip()
        pages = []
        matched_pages = document.get("matched_pages")
        if isinstance(matched_pages, list):
            pages = [
                str(item.get("page_number"))
                for item in matched_pages
                if isinstance(item, dict) and item.get("page_number")
            ]
        if not pages and isinstance(document.get("pages"), list):
            pages = [str(page) for page in document["pages"] if page]
        label = f"- {standard}"
        if version:
            label += f":{version}"
        if pages:
            label += f", p. {', '.join(pages)}"
        return f"### Base normativa\n\n{label}."


@lru_cache(maxsize=1)
def build_agent():
    client = Client()
    system_prompt = load_prompt_sys()

    return ScopedAgent(
        create_agent(
            model=client.return_model(),
            tools=[rag_document_search],
            system_prompt=system_prompt,
        )
    )


agent = build_agent()

__all__ = ["agent", "build_agent"]
