BEGIN;

CREATE TABLE IF NOT EXISTS silver.page_extraction_selections (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    selection_run_id UUID NOT NULL DEFAULT gen_random_uuid(),
    document_id BIGINT NOT NULL REFERENCES bronze.documents(record_id),
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    selected_page_extraction_id BIGINT REFERENCES silver.silver_page_extractions(id),
    status TEXT NOT NULL CHECK (status IN ('selected', 'retry_required', 'quarantined')),
    decision JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (selection_run_id, page_number)
);

ALTER TABLE gold.gold_rag_documents
    ADD COLUMN IF NOT EXISTS selection_run_id UUID;

CREATE INDEX IF NOT EXISTS page_extraction_selections_document
    ON silver.page_extraction_selections(document_id, created_at DESC);

COMMIT;
