BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM silver.page_extraction_selections) THEN
        RAISE EXCEPTION 'Page extraction selection history exists: retain this schema archive';
    END IF;
END $$;

DROP TABLE IF EXISTS silver.page_extraction_selections;
ALTER TABLE gold.gold_rag_documents DROP COLUMN IF EXISTS selection_run_id;

COMMIT;
