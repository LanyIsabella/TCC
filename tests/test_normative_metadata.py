from data.normative_metadata import (
    build_normative_metadata,
    metadata_conflicts,
    normalize_standard_identifier,
)


def test_normalizes_common_abnt_spellings_and_inline_edition():
    assert normalize_standard_identifier("NBR 6023") == {
        "issuer": "ABNT",
        "code": "NBR 6023",
        "edition": None,
        "canonical": "ABNT NBR 6023",
    }
    assert normalize_standard_identifier("ABNT NBR 6023") == (
        normalize_standard_identifier("NBR 6023")
    )
    assert normalize_standard_identifier("NBR 6023:2018")["edition"] == "2018"


def test_preserves_composite_iso_identifier():
    result = normalize_standard_identifier("ABNT NBR ISO/IEC 27001:2022")
    assert result["canonical"] == "ABNT NBR ISO/IEC 27001"
    assert result["edition"] == "2022"
    assert normalize_standard_identifier("ISO/IEC 27001:2022")["canonical"] == (
        "ISO/IEC 27001"
    )


def test_publication_and_effective_dates_are_distinct_and_provenanced():
    result = build_normative_metadata(
        {
            "id": "abnt_nbr_6034",
            "version": "2005",
            "publication_date": "2004-12-01",
            "effective_date": "2005-01-01",
        },
        source_layer="bronze",
    )
    assert result["schema_version"] == "normative-metadata-v1"
    assert result["identity"]["canonical"] == "ABNT NBR 6034"
    assert result["edition"] == "2005"
    assert result["dates"]["publication"] == "2004-12-01"
    assert result["dates"]["effective"] == "2005-01-01"
    assert result["provenance"]["dates.effective"]["source_layer"] == "bronze"


def test_missing_and_conflicting_values_are_explicit_not_invented():
    result = build_normative_metadata({"id": "abnt_nbr_6024"}, source_layer="gold")
    assert result["title"] is None
    assert result["provenance"]["title"]["status"] == "unknown"
    assert metadata_conflicts(
        {"title": "A", "version": "2012"},
        {"title": "B", "version": "2012"},
    ) == ["title"]


def test_two_editions_share_identity_but_not_edition_key():
    old = build_normative_metadata({"id": "NBR 6023:2018"}, source_layer="bronze")
    new = build_normative_metadata({"id": "NBR 6023:2025"}, source_layer="bronze")
    assert old["identity"]["canonical"] == new["identity"]["canonical"]
    assert old["edition"] != new["edition"]
