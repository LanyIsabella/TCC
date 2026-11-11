BEGIN;

-- Nullable columns preserve legacy JSON and permit staged, non-destructive backfill.
ALTER TABLE bronze.documents
    ADD COLUMN IF NOT EXISTS normative_metadata JSONB;
ALTER TABLE silver.silver_documents
    ADD COLUMN IF NOT EXISTS normative_metadata JSONB;
ALTER TABLE gold.gold_rag_documents
    ADD COLUMN IF NOT EXISTS normative_metadata JSONB;

COMMIT;
