"""Política de suporte por afirmação, independente da recuperação e dos canais."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationError

from .scope_guard import (
    GREETING_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    has_academic_term,
    normalize_text,
)

logger = logging.getLogger(__name__)
INSUFFICIENT_EVIDENCE = (
    "Não foi possível fundamentar a resposta nos trechos documentais disponíveis "
    "para esta pergunta. É necessário consultar a norma e confirmar o trecho aplicável."
)
PARTIAL_LIMITATION = (
    "Não foi possível fundamentar as demais afirmações nos trechos disponíveis."
)
_RULE_MARKERS = (
    r"\b(deve\w*|obrigatori\w*|permitid\w*|proibid\w*|vedad\w*|cm|mm|pt|pontos)\b"
)
_DOCUMENTARY_FIELDS = r"\b(fontes?|recuos?|(?:tipo|tamanho|estilo) de letras?)\b"
_NORMATIVE_MODAL = (
    r"\b(deve\w*|obrigatori\w*|permitid\w*|proibid\w*|vedad\w*|"
    r"exig\w*|requer\w*|necessári\w*|necessari\w*)\b"
)
_DOCUMENTARY_SUBJECT = (
    r"\b(citac\w*|referenc\w*|margens?|recuos?|fonte|folha|resumo|"
    r"espac\w*|elementos? pre[- ]textuais?|norma\w*|regra\w*|abnt|nbr)\b"
)
_CONCEPTUAL_CUES = (
    r"\b(organiz\w*|consist\w*|signific\w*|descrev\w*|explic\w*|"
    r"apresent\w*|contextualiz\w*|defin\w*|busc\w*|investig\w*|"
    r"analis\w*|objetiv\w*|conhec\w*|teoric\w*|panorama\w*|"
    r"debate\w*|fornec\w*|estabelec\w*|literatur\w*|comunic\w*|"
    r"cultur\w*|desenvolv\w*|transmit\w*|express\w*)\b"
)
_STRUCTURAL_NORMATIVE_SUBJECT = (
    r"\b(referenc\w*|sumari\w*|identific\w*|autori\w*|folha|"
    r"capa|titulo|citac\w*)\b"
)
_STRUCTURAL_NORMATIVE_RELATION = (
    r"\b(represent\w*|correspond\w*|aparec\w*|anteced\w*|"
    r"preced\w*|suced\w*)\b"
)
_STRUCTURAL_NORMATIVE_QUALIFIER = (
    r"\b(secao\w*|secoes\w*|posterior\w*|anterior\w*|antes|"
    r"depois|ordem|titulo|folha|autori\w*)\b"
)
Verifier = Callable[[str, list[str], Mapping[str, Any]], Any]
ClaimClassifier = Callable[[str, list[str]], Any]


@dataclass(frozen=True)
class GroundingDecision:
    answer: str
    evidence_ids: tuple[str, ...]
    status: Literal["supported", "partial", "insufficient", "conversational"]


class ClaimAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: StrictInt
    supported: StrictBool
    evidence_id: str | None = None
    quote: str | None = None


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[ClaimAssessment]


def _canonical(text: str) -> str:
    # shortcut: inline Markdown only, extend for reviewed cases needing richer markup.
    normalized = " ".join(re.sub(r"[`*_]", "", normalize_text(text)).split())
    for direction, bound in (("menos", "minimo"), ("mais", "maximo")):
        normalized = re.sub(
            rf"\bnao (?:deve|pode) (?:conter|ter) {direction} de (?=\d)",
            f"no {bound} ",
            normalized,
        )
    return normalized


def _conversational(claim: str) -> bool:
    if claim in {
        GREETING_MESSAGE,
        OUT_OF_SCOPE_MESSAGE,
        INSUFFICIENT_EVIDENCE,
        PARTIAL_LIMITATION,
    }:
        return True
    text = _canonical(claim)
    return bool(
        re.fullmatch(
            r"(?:ola|oi|obrigad[oa]|bom dia|boa tarde|boa noite)[!.]*|"
            r"(?:voce esta perguntando|voce se refere|qual norma voce|pode esclarecer)"
            r"[^.!]*\?",
            text,
        )
    )


def needs_support(answer: str, question: str = "") -> bool:
    if _conversational(answer):
        return False
    return has_academic_term(question + " " + answer) or bool(
        re.search(_RULE_MARKERS, _canonical(answer))
        or re.search(_DOCUMENTARY_FIELDS, _canonical(question))
        or _QUANTITY.search(_canonical(answer))
    )


def _claim_requires_normative_support(claim: str) -> bool:
    canonical = _canonical(claim)
    return bool(
        _QUANTITY.search(canonical)
        or re.search(r"\b(conforme|segundo|norma\w*|regra\w*|abnt|nbr)\b", canonical)
        or (
            re.search(_NORMATIVE_MODAL, canonical)
            and re.search(_DOCUMENTARY_SUBJECT, canonical)
        )
        or (
            re.search(_STRUCTURAL_NORMATIVE_SUBJECT, canonical)
            and re.search(_STRUCTURAL_NORMATIVE_RELATION, canonical)
            and re.search(_STRUCTURAL_NORMATIVE_QUALIFIER, canonical)
        )
    )


def _implicit_normative_claim(claim: str) -> bool:
    canonical = _canonical(claim)
    return bool(
        re.search(
            r"\b(citac\w*|referenc\w*|margens?|folha|resumo|"
            r"elementos? pre[- ]textuais?)\b",
            canonical,
        )
        and re.search(
            r"\b(fica\w*|ficam\w*|usa\w*|utiliza\w*|apresenta\w*|"
            r"apresentam\w*|aparece\w*|aparecem\w*|segue\w*|seguem\w*)\b",
            canonical,
        )
    )


def is_conceptual_explanation(text: str) -> bool:
    """Conserva prosa conceitual sem tratar ausência de classificação como prova."""
    claims = _claims(text)
    return bool(claims) and all(
        _conversational(claim)
        or (
            bool(re.search(_CONCEPTUAL_CUES, _canonical(claim)))
            and not _claim_requires_normative_support(claim)
            and not _implicit_normative_claim(claim)
        )
        for claim in claims
    )


def _classified_normative_claims(
    classifier: ClaimClassifier | None,
    question: str,
    claims: list[str],
) -> tuple[set[int], bool]:
    if classifier is None:
        return set(), False
    try:
        raw = classifier(question, claims)
        if isinstance(raw, str):
            raw = json.loads(raw)
        entries = raw.get("claims", []) if isinstance(raw, Mapping) else []
        if not isinstance(entries, list):
            return set(), False
        indices = {
            int(item["index"])
            for item in entries
            if isinstance(item, Mapping)
            and str(item.get("index", "")).isdigit()
            and 0 <= int(item["index"]) < len(claims)
        }
        normative = {
            int(item["index"])
            for item in entries
            if isinstance(item, Mapping)
            and str(item.get("kind") or "").casefold() == "normative"
            and str(item.get("index", "")).isdigit()
            and 0 <= int(item["index"]) < len(claims)
        }
        complete = (
            len(entries) == len(claims)
            and indices == set(range(len(claims)))
            and len(indices) == len(entries)
            and all(
                isinstance(item, Mapping)
                and str(item.get("kind") or "").casefold()
                in {"normative", "general", "example"}
                for item in entries
            )
        )
        return normative, complete
    except Exception:
        logger.warning("grounding_claim_classification_invalid=True")
        return set(), False


def _plain_text_rewrite(answer: str, question: str) -> bool:
    request = re.match(
        r"^(?:reescreva|reformule|revise|melhore a clareza)\b[^:]*:\s*\S",
        _canonical(question),
    )
    cues = (
        _RULE_MARKERS
        + "|"
        + _DOCUMENTARY_FIELDS
        + r"|\b(abnt|nbr|normas?|regras?|marge(?:m|ns)|cita(?:cao|coes)|"
        r"referencias?|espacamento)\b"
    )
    return bool(
        request
        and answer.strip()
        and not re.search(cues, _canonical(question + " " + answer))
        and not _QUANTITY.search(_canonical(answer))
    )


def _claims(answer: str) -> list[str]:
    # Decimal points stay inside a claim; line breaks preserve lists and tables.
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])|\n+", answer)
        if part.strip()
    ]


_NUMBERS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "vinte": 20,
}
_UNITS = {
    "mm": ("length", Decimal("0.1")),
    "milimetros": ("length", Decimal("0.1")),
    "cm": ("length", Decimal(1)),
    "centimetros": ("length", Decimal(1)),
    "m": ("length", Decimal(100)),
    "metros": ("length", Decimal(100)),
    "pt": ("point", Decimal(1)),
    "pontos": ("point", Decimal(1)),
    "palavras": ("word", Decimal(1)),
    "linhas": ("line", Decimal(1)),
}
_UNITS.update(
    {
        unit.removesuffix("s"): value
        for unit, value in _UNITS.items()
        if unit.endswith("s")
    }
)
_QUANTITY = re.compile(
    r"\b(\d+(?:[.,]\d+)?|"
    + "|".join(_NUMBERS)
    + r")\s*("
    + "|".join(sorted(_UNITS, key=len, reverse=True))
    + r")\b"
)


def _quantities(text: str) -> tuple[set[tuple[str, Decimal]], set[str]]:
    quantities = {
        _quantity_value(*match.groups()) for match in _QUANTITY.finditer(text)
    }
    remaining = _QUANTITY.sub("", text)
    return quantities, set(re.findall(r"\b\d+(?:[.,]\d+)?\b", remaining))


def _quantity_value(number: str, unit: str) -> tuple[str, Decimal]:
    value = (
        Decimal(_NUMBERS[number])
        if number in _NUMBERS
        else Decimal(number.replace(",", "."))
    )
    dimension, factor = _UNITS[unit]
    return dimension, value * factor


def _literal_form(text: str) -> str:
    return _QUANTITY.sub(_literal_quantity, _canonical(text))


def _literal_quantity(match: re.Match[str]) -> str:
    dimension, value = _quantity_value(*match.groups())
    return f"<{dimension}:{value.normalize()}>"


def _numeric_conflict(claim: str, context: str) -> bool:
    claim = _without_standard_identifiers(claim)
    context = _without_standard_identifiers(context)
    quantities, numbers = _quantities(claim)
    source_quantities, source_numbers = _quantities(context)
    return not quantities.issubset(source_quantities) or not numbers.issubset(
        source_numbers
    )


def _without_standard_identifiers(text: str) -> str:
    return re.sub(
        r"\b(?:abnt\s+)?nbr\s*[-_]?\s*\d+(?:\s*:\s*\d{4})?\b",
        "",
        text,
        flags=re.IGNORECASE,
    )


def _polarity(text: str) -> bool:
    # "Não é obrigatório" expresses permission, rather than prohibition.
    text = re.sub(r"nao (?:e |sao )?obrigatori\w*", "opcional", text)
    return bool(re.search(r"\b(nao|nunca|sem|proibid\w*|vedad\w*)\b", text))


def _qualifiers(text: str) -> list[str]:
    patterns = (
        r"(?<!-)\b(?:se(?!\s+(?:deve|pode|recomenda|permite)\b)|quando|caso|desde que)"
        r"\s+[^,.;:]+",
        r"\b(?:exceto|salvo|a menos que|com excecao)\s+[^.;]+",
        r"\b(?:apenas|somente)\s+[^,.;]+",
    )
    return [
        match.group() for pattern in patterns for match in re.finditer(pattern, text)
    ]


def _qualifier_conflict(claim: str, context: str, question: str) -> bool:
    qualifiers = _qualifiers(context)
    if qualifiers and re.search(r"\b(sempre|sem excecao|em todos os casos)\b", claim):
        return True
    exceptions = ("exceto", "salvo", "a menos que", "com excecao")
    added = [
        q for q in _qualifiers(claim) if q.startswith(exceptions) and q not in context
    ]
    if added:
        return True
    # Equivalent "se/quando" and a condition already explicit in the question are valid.
    targets = claim + " " + question
    return any(
        not _qualifier_is_present(q, targets) for q in qualifiers
    )


def _qualifier_is_present(qualifier: str, targets: str) -> bool:
    body = re.sub(r"^(?:se|quando|caso)\s+", "", qualifier)
    if body in targets:
        return True
    tokens = [
        token
        for token in re.findall(r"\b[\wÀ-ÿ]+\b", body)
        if token not in {"for", "ser", "deve", "devem", "que", "ter"}
    ]
    return len(tokens) >= 2 and all(token in targets for token in tokens)


def _modality_conflict(claim: str, context: str) -> bool:
    claim = re.sub(r"nao (?:e |sao )?obrigatori\w*", "opcional", claim)
    context = re.sub(r"nao (?:e |sao )?obrigatori\w*", "opcional", context)
    optional = r"\b(pode\w*|opcional|facultativ\w*|recomenda\w*)\b"
    mandatory = r"\b(deve\w*|obrigatori\w*)\b"
    if re.search(optional, context) and re.search(mandatory, claim):
        return True
    for first, opposite in (("minimo", "maximo"), ("maximo", "minimo")):
        if first in context and opposite in claim:
            return True
    return False


def _compatible(claim: str, context: str, question: str) -> bool:
    claim, context, question = map(_canonical, (claim, context, question))
    return not any(
        (
            _numeric_conflict(claim, context),
            _polarity(claim) != _polarity(context),
            _modality_conflict(claim, context),
            _qualifier_conflict(claim, context, question),
        )
    )


def _quote_context(quote: str, source: str) -> str:
    # Keep scope and exceptions without borrowing an unrelated rule's polarity.
    for paragraph in re.split(r"\n\s*\n", source):
        text = " ".join(paragraph.split())
        if " ".join(quote.split()) in text:
            return _scoped_quote(quote, text)
    return ""


def _scoped_quote(quote: str, paragraph: str) -> str:
    sentences = _claims(paragraph)
    quoted = [part for part in sentences if " ".join(quote.split()) in part]
    if not quoted:
        return paragraph
    scoped = []
    for index, sentence in enumerate(sentences):
        if sentence not in quoted:
            continue
        if index and _qualifiers(_canonical(sentences[index - 1])):
            scoped.append(sentences[index - 1])
        scoped.append(sentence)
        if index + 1 < len(sentences):
            following = _canonical(sentences[index + 1])
            if _following_restriction(following):
                scoped.append(sentences[index + 1])
    return " ".join(dict.fromkeys(scoped))


def _following_restriction(sentence: str) -> bool:
    if re.search(r"\b(exceto|salvo|a menos que|com excecao)\b", sentence):
        return True
    return bool(
        re.search(r"\b(somente|apenas)\b", sentence)
        and re.search(r"\b(regra|esta|essa|isso|isto)\b", sentence)
    )


def _literal_support(
    claim: str, available: Mapping[str, Any], question: str
) -> str | None:
    for identifier, record in available.items():
        if not _evidence_topic_matches(question, record):
            continue
        source = str(record.get("text") or "")
        if _literal_in_source(claim, source, question):
            return identifier
    return None


def _evidence_topic_matches(question: str, record: Mapping[str, Any]) -> bool:
    """Evita validar uma frase literal de uma norma apenas referencial."""

    normalized_question = _canonical(question)
    document = _canonical(
        " ".join(
            str(record.get(key) or "") for key in ("title", "standard_id")
        )
    )
    source = _canonical(str(record.get("text") or ""))
    if not document:
        return True
    if "referenc" in normalized_question:
        # A verb "citar" can occur in a question explicitly about references;
        # prefer the reference standard unless the question names citations.
        if "citac" not in normalized_question:
            return _reference_topic_matches(document, source)
    if any(marker in normalized_question for marker in ("citac", "citar")):
        return _citation_topic_matches(document, source)
    return True


def _citation_topic_matches(document: str, source: str) -> bool:
    if "citac" in document or "10520" in document:
        return True
    return bool(
        re.search(
            r"\b(citacao direta|citacao indireta|autor[- ]data|"
            r"sistema numerico|recuo de|citac(?:ao|oes)\b[^.!?]{0,120}"
            r"\b(?:linha|linhas|tamanho|menor|uniforme)\b)"
            r"\b",
            source,
        )
    )


def _reference_topic_matches(document: str, source: str) -> bool:
    # Menções ocasionais a referências normativas não tornam uma norma de
    # citações pertinente a uma pergunta sobre referências bibliográficas.
    if ("10520" in document or "citac" in document) and "6023" not in document:
        return False
    if "referenc" in document or "6023" in document:
        return True
    return bool(
        re.search(
            r"\breferenc\w*\b[^.!?]{0,180}\b(?:separad\w*|"
            r"espac\w*|element\w*|autor\w*|apresent\w*|ordem|"
            r"alfab\w*|list\w*|format\w*|alinh\w*)\b|"
            r"\b(?:separad\w*|espac\w*|element\w*|autor\w*|"
            r"apresent\w*|ordem|alfab\w*|list\w*|format\w*|"
            r"alinh\w*)\b[^.!?]{0,180}\breferenc\w*\b",
            source,
        )
    )


def _literal_in_source(claim: str, source: str, question: str) -> bool:
    # Evidence snippets may carry Markdown headings/list markers from extraction;
    # those formatting tokens must not prevent an exact normative sentence match.
    normalized_source = re.sub(
        r"(?m)^[ \t]*#{1,6}[ \t]*[^\r\n]*\r?\n?", "", source
    )
    normalized_source = re.sub(r"(?m)^[ \t]*[-*][ \t]+", "", normalized_source)
    claim_form = _literal_form(claim)
    claim_without_terminal_punctuation = claim_form.rstrip(".!?;:")
    for paragraph in re.split(r"\n\s*\n", normalized_source):
        sentences = _claims(" ".join(paragraph.split()))
        for part in sentences:
            part_form = _literal_form(part)
            part_without_terminal_punctuation = part_form.rstrip(".!?;:")
            part_without_section = re.sub(
                r"^\d+(?:\.\d+)*\s+", "", part_form
            )
            if (
                claim_form == part_form
                or claim_without_terminal_punctuation
                == part_without_terminal_punctuation
                or claim_form == part_without_section
                or claim_without_terminal_punctuation
                == part_without_section.rstrip(".!?;:")
                or _optional_permission(claim, part)
            ):
                return _compatible(claim, _quote_context(part, source), question)
    return False


def _optional_permission(claim: str, source: str) -> bool:
    # Optional use entails permission for the same object; the converse is not proof.
    optional = re.fullmatch(
        r"o uso de (.+) e opcional", _canonical(source).removesuffix(".")
    )
    permitted = re.fullmatch(
        r"(?:voce pode usar|pode-se usar) (.+)", _canonical(claim).removesuffix(".")
    )
    return bool(
        optional
        and permitted
        and _literal_form(optional.group(1)) == _literal_form(permitted.group(1))
    )


def _assess(
    verifier: Verifier | None,
    question: str,
    claims: list[str],
    available: Mapping[str, Any],
) -> list[ClaimAssessment]:
    if verifier is None:
        return []
    try:
        raw = verifier(question, claims, available)
        data = _assessment_data(raw)
        return Assessment.model_validate(data).claims
    except (ValueError, TypeError, ValidationError):
        logger.warning("grounding_verification_invalid=True")
    except Exception:
        logger.exception("grounding_verification_failed=True")
    return []


def _assessment_data(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    envelope = re.fullmatch(
        r"\s*```(?:json)?\s*\n(.*?)\n```\s*", raw, re.DOTALL | re.IGNORECASE
    )
    return json.loads(envelope.group(1) if envelope else raw)


def _verified_support(
    assessment: ClaimAssessment, claim: str, available: Mapping[str, Any], question: str
) -> str | None:
    quote = assessment.quote or ""
    identifier = assessment.evidence_id or ""
    if not assessment.supported or not quote.strip():
        return None
    record = available.get(identifier)
    if record is None:
        return None
    if not _evidence_topic_matches(question, record):
        return None
    context = _quote_context(quote, str(record.get("text") or ""))
    if context and _compatible(claim, context, question):
        return identifier
    return None


def _claim_support(
    claims: list[str],
    available: Mapping[str, Any],
    question: str,
    verifier: Verifier | None,
) -> dict[int, str | None]:
    normalized_claims = [
        re.sub(r"^[ \t]*[-*+][ \t]+", "", claim) for claim in claims
    ]
    support = {
        index: _literal_support(claim, available, question)
        for index, claim in enumerate(normalized_claims)
    }
    if not available or all(support.values()):
        return support
    assessments = _assess(verifier, question, normalized_claims, available)
    counts = Counter(item.index for item in assessments)
    for item in assessments:
        if 0 <= item.index < len(claims) and counts[item.index] == 1:
            support[item.index] = support[item.index] or _verified_support(
                item, normalized_claims[item.index], available, question
            )
    return support


def _compose(
    answer: str,
    claims: list[str],
    support: Mapping[int, str | None],
    required: set[int] | None = None,
) -> GroundingDecision:
    required = set(range(len(claims))) if required is None else required
    kept = [
        claim
        for index, claim in enumerate(claims)
        if index not in required or support[index] or _conversational(claim)
    ]
    identifiers = tuple(
        dict.fromkeys(
            identifier
            for index, identifier in support.items()
            if index in required and identifier
        )
    )
    if not required:
        return GroundingDecision(answer, (), "conversational")
    unsupported = [
        claim
        for index, claim in enumerate(claims)
        if index in required and not support[index]
    ]
    if required and not identifiers:
        if kept:
            return GroundingDecision(
                _preserve_structure(answer, unsupported), (), "partial"
            )
        return GroundingDecision(INSUFFICIENT_EVIDENCE, (), "insufficient")
    if len(kept) == len(claims):
        return GroundingDecision(answer, identifiers, "supported")
    return GroundingDecision(
        _preserve_structure(answer, unsupported), identifiers, "partial"
    )


def _preserve_structure(answer: str, unsupported: list[str]) -> str:
    cleaned = answer
    for claim in unsupported:
        cleaned = cleaned.replace(claim, "")
    cleaned = re.sub(r"(?m)^\s*[-*]\s*$\r?\n?", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        return INSUFFICIENT_EVIDENCE
    return f"{cleaned}\n\n{PARTIAL_LIMITATION}"


def ground_answer(
    answer: str,
    available: Mapping[str, Any],
    question: str = "",
    verifier: Verifier | None = None,
    *,
    normative_context: bool = False,
    response_mode: str | None = None,
    claim_classifier: ClaimClassifier | None = None,
) -> GroundingDecision:
    """IDs e similaridade não provam suporte; paráfrases exigem avaliação semântica."""
    if (
        _conversational(answer)
        or _plain_text_rewrite(answer, question)
        or not (normative_context or needs_support(answer, question))
    ):
        return GroundingDecision(answer, (), "conversational")
    claims = _claims(answer)
    support = _claim_support(claims, available, question, verifier)
    required = None
    if response_mode == "mixed":
        required = {
            index
            for index, claim in enumerate(claims)
            if _claim_requires_normative_support(claim)
            or _implicit_normative_claim(claim)
        }
        classified, complete = _classified_normative_claims(
            claim_classifier, question, claims
        )
        required.update(classified)
        if not complete:
            required.update(
                index
                for index, claim in enumerate(claims)
                if _claim_requires_normative_support(claim)
                or _implicit_normative_claim(claim)
                or not is_conceptual_explanation(claim)
            )
    return _compose(answer, claims, support, required)
