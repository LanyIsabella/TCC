"""Offline contract and source-locator checks; these do not certify human gold."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "rag_eval/baseline/queries.json"
EDITIONS = {
    "10520": "2023",
    "12225": "2023",
    "14724": "2024",
    "15287": "2025",
    "6022": "2018",
    "6023": "2025",
    "6024": "2012",
    "6027": "2012",
    "6028": "2021",
    "6034": "2004",
}
FIELDS = {
    "id",
    "category",
    "split",
    "group_id",
    "question",
    "history",
    "expected_behavior",
    "references",
    "reference_status",
}
BEHAVIORS = {
    "grounded_answer",
    "partial_or_grounded_answer",
    "abstain",
    "clarify",
    "refuse_out_of_scope",
}


@pytest.fixture(scope="module")
def queries():
    return json.loads(DATASET.read_text(encoding="utf-8"))


def test_exact_dataset_counts_and_unique_ids(queries):
    assert len(queries) == 120
    assert len({q["id"] for q in queries}) == 120
    assert Counter(q["category"] for q in queries) == {
        "specific": 60,
        "broad": 20,
        "conversational": 20,
        "negative": 10,
        "ambiguous": 10,
    }
    assert Counter(q["split"] for q in queries) == {
        "development": 40,
        "reserved": 80,
    }


def test_required_fields_and_safe_public_history(queries):
    for query in queries:
        assert set(query) == FIELDS, query["id"]
        assert re.fullmatch(r"[a-z0-9_-]+", query["id"])
        assert re.fullmatch(r"[a-z0-9_-]+", query["group_id"])
        assert isinstance(query["question"], str) and query["question"].strip()
        assert query["expected_behavior"] in BEHAVIORS
        assert isinstance(query["references"], list)
        assert isinstance(query["history"], list)
        for message in query["history"]:
            assert set(message) == {"role", "content"}
            # User-only histories avoid fabricated normative assistant answers.
            assert message["role"] == "user"
            assert isinstance(message["content"], str) and message["content"].strip()
        if query["category"] != "conversational":
            assert query["history"] == []


def test_expected_behaviors_do_not_claim_human_annotation(queries):
    for query in queries:
        if query["references"]:
            assert query["reference_status"] == "pending_human_review"
            assert query["expected_behavior"] in {
                "grounded_answer",
                "partial_or_grounded_answer",
            }
        else:
            assert query["reference_status"] == "not_applicable"
            assert query["expected_behavior"] in {
                "abstain",
                "clarify",
                "refuse_out_of_scope",
            }
        if query["category"] == "specific":
            assert len(query["references"]) == 1
        if query["category"] == "broad":
            assert len({ref["standard_id"] for ref in query["references"]}) >= 2
        if query["category"] == "ambiguous":
            assert query["expected_behavior"] == "clarify"


def test_groups_templates_and_dialogues_never_cross_splits(queries):
    splits = defaultdict(set)
    questions = defaultdict(set)
    dialogues = defaultdict(list)
    for query in queries:
        splits[query["group_id"]].add(query["split"])
        # The same question/template cannot be moved across splits by renaming a group.
        template = re.sub(r"\d+", "#", query["question"].casefold())
        template = " ".join(re.findall(r"\w+", template))
        questions[template].add(query["split"])
        if query["category"] == "conversational":
            dialogues[query["group_id"]].append(query)
    assert all(len(values) == 1 for values in splits.values())
    assert all(len(values) == 1 for values in questions.values())
    assert len(dialogues) == 10
    for turns in dialogues.values():
        assert len(turns) == 2
        first, second = sorted(turns, key=lambda q: q["id"])
        assert first["id"].endswith("_t1")
        assert second["id"].endswith("_t2")
        assert first["history"] == []
        assert second["history"] == [{"role": "user", "content": first["question"]}]


def test_six_specific_queries_for_each_corpus_standard(queries):
    assert Counter(
        query["references"][0]["standard_id"]
        for query in queries
        if query["category"] == "specific"
    ) == {f"abnt_nbr_{number}": 6 for number in EDITIONS}


def test_locators_match_current_pdf_hash_identity_page_and_native_excerpt(queries):
    documents = {}
    for number, edition in EDITIONS.items():
        path = ROOT / f"data/raw/NBR{number}.pdf"
        reader = PdfReader(path)
        label = f"ABNT NBR {number}:{edition}"
        assert label in reader.pages[0].extract_text()
        documents[f"abnt_nbr_{number}"] = (
            f"data/raw/NBR{number}.pdf",
            label,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            reader,
        )
    page_texts = {}
    for query in queries:
        for ref in query["references"]:
            assert set(ref) == {
                "standard_id",
                "standard_label",
                "document_file",
                "document_sha256",
                "physical_page",
                "source_excerpt",
                "locator_method",
            }
            filename, label, digest, reader = documents[ref["standard_id"]]
            assert ref["standard_label"] == label
            assert ref["document_file"] == filename
            assert ref["document_sha256"] == digest
            assert type(ref["physical_page"]) is int
            assert 5 <= ref["physical_page"] <= len(reader.pages)
            assert ref["locator_method"] == "pypdf_native_text_whitespace"
            excerpt = ref["source_excerpt"]
            assert isinstance(excerpt, str) and 15 <= len(excerpt) <= 220
            key = (ref["standard_id"], ref["physical_page"])
            if key not in page_texts:
                page_texts[key] = " ".join(
                    reader.pages[ref["physical_page"] - 1].extract_text().split()
                )
            assert excerpt == " ".join(excerpt.split())
            assert excerpt in page_texts[key], query["id"]
