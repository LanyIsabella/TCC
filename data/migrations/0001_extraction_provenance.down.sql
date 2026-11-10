BEGIN;

-- A used ledger cannot be erased by a schema downgrade. Restore a pre-migration
-- backup into another database and retain this database as the version archive.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM silver.silver_document_extractions
               WHERE input_fingerprint IS NOT NULL)
       OR EXISTS (SELECT 1 FROM silver.page_extraction_history
                  WHERE event_kind <> 'legacy_import')
       OR EXISTS (SELECT 1 FROM gold.document_derivations) THEN
        RAISE EXCEPTION 'Versioned history exists: restore backup into another database; retain this archive';
    END IF;
END $$;

DROP VIEW gold.gold_rag_page_derivation_status;
DROP VIEW gold.gold_rag_derivation_status;
DROP TABLE gold.document_derivations;
DROP TRIGGER record_page_history ON silver.silver_page_extractions;
DROP TRIGGER bind_page_provenance ON silver.silver_page_extractions;
DROP TRIGGER protect_execution_identity ON silver.silver_document_extractions;
DROP FUNCTION silver.record_page_history();
DROP FUNCTION silver.bind_page_provenance();
DROP FUNCTION silver.protect_execution_identity();
DROP TABLE silver.page_extraction_history;
DROP FUNCTION silver.protect_page_history();
DROP FUNCTION silver.result_identity(silver.silver_page_extractions);
ALTER TABLE silver.silver_page_extractions
    DROP COLUMN result_fingerprint,
    DROP COLUMN evaluation_id,
    DROP COLUMN evaluation_request_id,
    DROP COLUMN evaluation_input_fingerprint,
    DROP COLUMN evaluation_config_fingerprint,
    DROP COLUMN evaluation_config;
DROP INDEX silver.silver_execution_identity;
DROP INDEX silver.silver_execution_inputs;
ALTER TABLE silver.silver_document_extractions
    DROP COLUMN execution_id,
    DROP COLUMN input_fingerprint,
    DROP COLUMN input_provenance,
    ADD UNIQUE(document_id,extractor,extractor_version);

COMMIT;
