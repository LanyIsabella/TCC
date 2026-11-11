BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM bronze.documents
        WHERE normative_metadata IS NOT NULL
    ) OR EXISTS (
        SELECT 1
        FROM silver.silver_documents
        WHERE normative_metadata IS NOT NULL
    ) OR EXISTS (
        SELECT 1
        FROM gold.gold_rag_documents
        WHERE normative_metadata IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Normative metadata exists: retain this schema archive';
    END IF;
END $$;

ALTER TABLE bronze.documents DROP COLUMN IF EXISTS normative_metadata;
ALTER TABLE silver.silver_documents DROP COLUMN IF EXISTS normative_metadata;
ALTER TABLE gold.gold_rag_documents DROP COLUMN IF EXISTS normative_metadata;

COMMIT;
