from pathlib import Path

import pytest


@pytest.mark.integration
def test_normative_metadata_columns_are_present_and_migration_is_idempotent(
    isolated_pg,
):
    connect, _ = isolated_pg
    root = Path(__file__).parents[2]
    up = (root / "data/migrations/0003_normative_metadata.up.sql").read_text(
        encoding="utf-8"
    )
    with connect() as connection:
        connection.execute(
            "UPDATE bronze.documents SET manifest_metadata = "
            "'{\"version\": \"2012\"}'::jsonb WHERE record_id = 17"
        )
        connection.execute(up)
        columns = connection.execute(
            """
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE column_name = 'normative_metadata'
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        legacy_version = connection.execute(
            "SELECT manifest_metadata->>'version' "
            "FROM bronze.documents WHERE record_id = 17"
        ).fetchone()[0]
    assert columns == [
        ("bronze", "documents", "normative_metadata"),
        ("gold", "gold_rag_documents", "normative_metadata"),
        ("silver", "silver_documents", "normative_metadata"),
    ]
    assert legacy_version == "2012"


@pytest.mark.integration
def test_normative_metadata_rollback_refuses_data_loss(isolated_pg):
    connect, _ = isolated_pg
    root = Path(__file__).parents[2]
    down = (root / "data/migrations/0003_normative_metadata.down.sql").read_text(
        encoding="utf-8"
    )
    with connect() as connection:
        connection.execute(
            "UPDATE bronze.documents SET normative_metadata = "
            "'{\"schema_version\": \"normative-metadata-v1\"}'::jsonb "
            "WHERE record_id = 17"
        )
        with pytest.raises(Exception, match="Normative metadata exists"):
            connection.execute(down)
