BEGIN;

ALTER TABLE silver.silver_document_extractions
    ADD COLUMN IF NOT EXISTS execution_id UUID NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS input_fingerprint CHAR(64),
    ADD COLUMN IF NOT EXISTS input_provenance JSONB NOT NULL
        DEFAULT '{"historical_configuration":"unknown"}'::jsonb;

DO $$
DECLARE item RECORD;
BEGIN
    FOR item IN SELECT conname FROM pg_constraint
        WHERE conrelid = 'silver.silver_document_extractions'::regclass
          AND contype = 'u'
          AND pg_get_constraintdef(oid) = 'UNIQUE (document_id, extractor, extractor_version)'
    LOOP
        EXECUTE format('ALTER TABLE silver.silver_document_extractions DROP CONSTRAINT %I', item.conname);
    END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS silver_execution_identity
    ON silver.silver_document_extractions(execution_id);
CREATE INDEX IF NOT EXISTS silver_execution_inputs
    ON silver.silver_document_extractions(document_id, extractor, input_fingerprint);

ALTER TABLE silver.silver_page_extractions
    ADD COLUMN IF NOT EXISTS result_fingerprint CHAR(64),
    ADD COLUMN IF NOT EXISTS evaluation_id UUID,
    ADD COLUMN IF NOT EXISTS evaluation_request_id UUID,
    ADD COLUMN IF NOT EXISTS evaluation_input_fingerprint CHAR(64),
    ADD COLUMN IF NOT EXISTS evaluation_config_fingerprint CHAR(64),
    ADD COLUMN IF NOT EXISTS evaluation_config JSONB;

CREATE TABLE IF NOT EXISTS silver.page_extraction_history (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    page_extraction_id BIGINT NOT NULL
        REFERENCES silver.silver_page_extractions(id),
    result_fingerprint CHAR(64),
    evaluation_id UUID,
    event_kind TEXT NOT NULL,
    snapshot JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS silver_page_history_result
    ON silver.page_extraction_history(result_fingerprint);

CREATE OR REPLACE FUNCTION silver.result_identity(p silver.silver_page_extractions)
RETURNS TEXT LANGUAGE SQL STABLE AS $$
    SELECT encode(sha256(convert_to(jsonb_build_object(
        'scheme', 'page-result-v1', 'execution', e.execution_id,
        'input', e.input_fingerprint, 'page', p.page_number,
        'text', p.extracted_text, 'markdown', p.extracted_markdown,
        'structured_output', p.structured_output
    )::text, 'UTF8')), 'hex')
    FROM silver.silver_document_extractions e WHERE e.id = p.extraction_id
$$;

-- Existing fields are observations; unrecorded historical settings remain unknown.
UPDATE silver.silver_page_extractions p
SET result_fingerprint = silver.result_identity(p)
WHERE result_fingerprint IS NULL;
UPDATE silver.silver_page_extractions
SET evaluation_id = gen_random_uuid(),
    evaluation_input_fingerprint = result_fingerprint,
    evaluation_config = '{"historical_configuration":"unknown"}'::jsonb
WHERE evaluation_id IS NULL AND evaluation_status <> 'pending';
INSERT INTO silver.page_extraction_history
    (page_extraction_id, result_fingerprint, evaluation_id, event_kind, snapshot)
SELECT p.id, p.result_fingerprint, p.evaluation_id, 'legacy_import', to_jsonb(p)
FROM silver.silver_page_extractions p
WHERE NOT EXISTS (
    SELECT 1 FROM silver.page_extraction_history h WHERE h.page_extraction_id = p.id
);

CREATE OR REPLACE FUNCTION silver.protect_execution_identity()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.execution_id, NEW.document_id, NEW.extractor, NEW.extractor_version,
        NEW.input_fingerprint, NEW.input_provenance)
       IS DISTINCT FROM
       (OLD.execution_id, OLD.document_id, OLD.extractor, OLD.extractor_version,
        OLD.input_fingerprint, OLD.input_provenance) THEN
        RAISE EXCEPTION 'Extraction identity is immutable; create another execution';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS protect_execution_identity ON silver.silver_document_extractions;
CREATE TRIGGER protect_execution_identity BEFORE UPDATE
ON silver.silver_document_extractions FOR EACH ROW
EXECUTE FUNCTION silver.protect_execution_identity();

CREATE OR REPLACE FUNCTION silver.bind_page_provenance()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE changed_result BOOLEAN;
BEGIN
    IF NEW.extracted_text IS NOT NULL OR NEW.extracted_markdown IS NOT NULL THEN
        NEW.content_hash := encode(sha256(convert_to(
            coalesce(nullif(NEW.extracted_text, ''), NEW.extracted_markdown, ''),
            'UTF8')), 'hex');
    ELSE
        NEW.content_hash := NULL;
    END IF;
    NEW.result_fingerprint := silver.result_identity(NEW);
    changed_result := TG_OP = 'UPDATE' AND
        OLD.result_fingerprint IS DISTINCT FROM NEW.result_fingerprint;
    IF changed_result THEN
        NEW.quality_score := NULL;
        NEW.quality_metrics := NULL;
        NEW.evaluation_status := 'pending';
        NEW.evaluation_method := NULL;
        NEW.evaluation_model := NULL;
        NEW.evaluation_prompt_version := NULL;
        NEW.evaluation_error := NULL;
        NEW.evaluated_at := NULL;
        NEW.evaluation_id := NULL;
        NEW.evaluation_request_id := NULL;
        NEW.evaluation_input_fingerprint := NULL;
        NEW.evaluation_config_fingerprint := NULL;
        NEW.evaluation_config := NULL;
    ELSIF NEW.evaluation_status <> 'pending' AND (
        TG_OP = 'INSERT' OR
        (NEW.quality_score, NEW.quality_metrics, NEW.evaluation_status,
         NEW.evaluation_method, NEW.evaluation_model, NEW.evaluation_prompt_version,
         NEW.evaluation_error, NEW.evaluated_at, NEW.evaluation_config_fingerprint)
        IS DISTINCT FROM
        (OLD.quality_score, OLD.quality_metrics, OLD.evaluation_status,
         OLD.evaluation_method, OLD.evaluation_model, OLD.evaluation_prompt_version,
         OLD.evaluation_error, OLD.evaluated_at, OLD.evaluation_config_fingerprint)
    ) THEN
        IF NEW.evaluation_input_fingerprint IS NOT NULL AND
           NEW.evaluation_input_fingerprint <> NEW.result_fingerprint THEN
            RAISE EXCEPTION 'Evaluation belongs to a different extracted result';
        END IF;
        IF NEW.evaluation_id IS NOT DISTINCT FROM OLD.evaluation_id THEN
            NEW.evaluation_id := gen_random_uuid();
        END IF;
        NEW.evaluation_input_fingerprint := NEW.result_fingerprint;
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS bind_page_provenance ON silver.silver_page_extractions;
CREATE TRIGGER bind_page_provenance BEFORE INSERT OR UPDATE
ON silver.silver_page_extractions FOR EACH ROW
EXECUTE FUNCTION silver.bind_page_provenance();

CREATE OR REPLACE FUNCTION silver.record_page_history()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' OR (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM
                          (to_jsonb(OLD) - 'updated_at') THEN
        INSERT INTO silver.page_extraction_history
            (page_extraction_id, result_fingerprint, evaluation_id, event_kind, snapshot)
        VALUES (NEW.id, NEW.result_fingerprint, NEW.evaluation_id,
            CASE WHEN NEW.evaluation_id IS NOT NULL THEN 'evaluation'
                 ELSE 'result' END, to_jsonb(NEW));
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS record_page_history ON silver.silver_page_extractions;
CREATE TRIGGER record_page_history AFTER INSERT OR UPDATE
ON silver.silver_page_extractions FOR EACH ROW
EXECUTE FUNCTION silver.record_page_history();

CREATE OR REPLACE FUNCTION silver.protect_page_history()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Extraction history is append-only';
END $$;
DROP TRIGGER IF EXISTS protect_page_history ON silver.page_extraction_history;
CREATE TRIGGER protect_page_history BEFORE UPDATE OR DELETE
ON silver.page_extraction_history FOR EACH ROW
EXECUTE FUNCTION silver.protect_page_history();

CREATE TABLE IF NOT EXISTS gold.document_derivations (
    rag_document_id BIGINT PRIMARY KEY REFERENCES gold.gold_rag_documents(id),
    origin JSONB NOT NULL,
    fingerprint CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS protect_derivation_history ON gold.document_derivations;
CREATE TRIGGER protect_derivation_history BEFORE UPDATE OR DELETE
ON gold.document_derivations FOR EACH ROW
EXECUTE FUNCTION silver.protect_page_history();

CREATE OR REPLACE VIEW gold.gold_rag_derivation_status AS
SELECT g.id AS rag_document_id, g.extraction_id,
    e.execution_id, e.input_fingerprint, g.content_hash,
    e.input_fingerprint IS NULL OR lineage.origin IS NULL
        AS historical_configuration_unknown,
    (lineage.origin IS NOT NULL AND lineage.origin->'pages' IS DISTINCT FROM (
        SELECT jsonb_object_agg(p.page_number::text,p.result_fingerprint)
        FROM silver.silver_page_extractions p WHERE p.extraction_id=e.id
    )) OR g.content_hash IS DISTINCT FROM e.content_hash OR EXISTS (
        SELECT 1 FROM silver.silver_document_extractions newer
        WHERE newer.document_id = e.document_id AND newer.extractor = e.extractor
          AND newer.id > e.id AND newer.processing_status = 'success'
          AND (newer.input_fingerprint IS DISTINCT FROM e.input_fingerprint
               OR newer.content_hash IS DISTINCT FROM e.content_hash)
    ) AS is_stale,
    lineage.fingerprint AS derivation_fingerprint
FROM gold.gold_rag_documents g
JOIN silver.silver_document_extractions e ON e.id = g.extraction_id
LEFT JOIN gold.document_derivations lineage ON lineage.rag_document_id=g.id;

CREATE OR REPLACE VIEW gold.gold_rag_page_derivation_status AS
SELECT p.id AS page_index_id, p.rag_document_id,
    s.result_fingerprint AS source_result_fingerprint,
    d.historical_configuration_unknown,
    d.is_stale OR s.id IS NULL OR
        p.page_content_hash IS DISTINCT FROM s.content_hash AS source_is_stale,
    p.embedding_status = 'success' AND p.embedding IS NOT NULL AND
        p.embedding_content_hash = p.content_hash AS embedding_matches_recorded_text,
    encode(sha256(convert_to(jsonb_build_object(
        'scheme', 'embedding-derivation-v1', 'result', s.result_fingerprint,
        'text', p.content_hash, 'embedding_text', p.embedding_content_hash,
        'model', p.embedding_model, 'dimension', p.embedding_dimension,
        'model_digest', p.model_digest
    )::text, 'UTF8')), 'hex') AS derivation_fingerprint
FROM gold.gold_rag_page_index p
JOIN gold.gold_rag_documents g ON g.id = p.rag_document_id
JOIN gold.gold_rag_derivation_status d ON d.rag_document_id = g.id
LEFT JOIN silver.silver_page_extractions s
    ON s.extraction_id = g.extraction_id AND s.page_number = p.page_number;

COMMIT;
