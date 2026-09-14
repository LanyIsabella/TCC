CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS silver.silver_documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL UNIQUE REFERENCES bronze.documents(record_id),
    total_pages INTEGER NOT NULL DEFAULT 0,
    docling_text TEXT,
    docling_markdown TEXT,
    docling_pages JSONB NOT NULL DEFAULT '{"pages": []}'::jsonb,
    docling_processing_status TEXT NOT NULL DEFAULT 'pending',
    docling_processed_pages INTEGER NOT NULL DEFAULT 0,
    docling_failed_pages INTEGER NOT NULL DEFAULT 0,
    docling_character_count BIGINT NOT NULL DEFAULT 0,
    docling_word_count BIGINT NOT NULL DEFAULT 0,
    docling_processing_time_ms BIGINT,
    docling_content_hash CHAR(64),
    docling_average_score NUMERIC(5, 2),
    docling_weighted_score NUMERIC(5, 2),
    docling_evaluation JSONB NOT NULL DEFAULT '{}'::jsonb,
    docling_extractor_version TEXT,
    docling_processed_at TIMESTAMPTZ,
    glm_ocr_text TEXT,
    glm_ocr_markdown TEXT,
    glm_ocr_pages JSONB NOT NULL DEFAULT '{"pages": []}'::jsonb,
    glm_ocr_processing_status TEXT NOT NULL DEFAULT 'pending',
    glm_ocr_processed_pages INTEGER NOT NULL DEFAULT 0,
    glm_ocr_failed_pages INTEGER NOT NULL DEFAULT 0,
    glm_ocr_character_count BIGINT NOT NULL DEFAULT 0,
    glm_ocr_word_count BIGINT NOT NULL DEFAULT 0,
    glm_ocr_processing_time_ms BIGINT,
    glm_ocr_content_hash CHAR(64),
    glm_ocr_average_score NUMERIC(5, 2),
    glm_ocr_weighted_score NUMERIC(5, 2),
    glm_ocr_evaluation JSONB NOT NULL DEFAULT '{}'::jsonb,
    glm_ocr_extractor_version TEXT,
    glm_ocr_processed_at TIMESTAMPTZ,
    selected_extractor TEXT,
    selected_at TIMESTAMPTZ,
    selection_reason TEXT,
    ready_for_gold BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS silver.silver_document_extractions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES bronze.documents(record_id),
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    processing_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (processing_status IN ('pending', 'processing', 'success', 'error')),
    total_pages INTEGER NOT NULL DEFAULT 0,
    processed_pages INTEGER NOT NULL DEFAULT 0,
    successful_pages INTEGER NOT NULL DEFAULT 0,
    failed_pages INTEGER NOT NULL DEFAULT 0,
    full_text TEXT,
    full_markdown TEXT,
    character_count BIGINT NOT NULL DEFAULT 0,
    word_count BIGINT NOT NULL DEFAULT 0,
    processing_time_ms BIGINT,
    content_hash CHAR(64),
    average_quality_score NUMERIC(5, 2),
    weighted_quality_score NUMERIC(5, 2),
    evaluation_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, extractor, extractor_version)
);

CREATE TABLE IF NOT EXISTS silver.silver_page_extractions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    extraction_id BIGINT NOT NULL
        REFERENCES silver.silver_document_extractions(id) ON DELETE CASCADE,
    document_id BIGINT NOT NULL REFERENCES bronze.documents(record_id),
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    source_page_path TEXT,
    extracted_text TEXT,
    extracted_markdown TEXT,
    structured_output JSONB,
    character_count BIGINT NOT NULL DEFAULT 0,
    word_count BIGINT NOT NULL DEFAULT 0,
    content_hash CHAR(64),
    processing_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (processing_status IN ('pending', 'processing', 'success', 'error')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    processing_time_ms BIGINT,
    error_message TEXT,
    last_attempt_at TIMESTAMPTZ,
    quality_score NUMERIC(5, 2),
    quality_metrics JSONB,
    evaluation_status TEXT NOT NULL DEFAULT 'pending',
    evaluation_method TEXT,
    evaluation_model TEXT,
    evaluation_prompt_version TEXT,
    evaluation_error TEXT,
    evaluated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (extraction_id, page_number)
);

CREATE TABLE IF NOT EXISTS gold.gold_rag_documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES bronze.documents(record_id),
    extraction_id BIGINT NOT NULL
        REFERENCES silver.silver_document_extractions(id),
    silver_document_id BIGINT
        REFERENCES silver.silver_documents(id),
    title TEXT,
    document_type TEXT,
    issuer TEXT,
    version TEXT,
    document_status TEXT,
    source_extractor TEXT NOT NULL,
    full_text TEXT NOT NULL,
    full_markdown TEXT NOT NULL,
    total_pages INTEGER NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    context_token_limit INTEGER,
    context_window_exceeded BOOLEAN NOT NULL DEFAULT false,
    context_warning TEXT,
    search_vector TSVECTOR,
    quality_score NUMERIC(5, 2),
    content_hash CHAR(64) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, extraction_id)
);

CREATE TABLE IF NOT EXISTS gold.gold_rag_page_index (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rag_document_id BIGINT NOT NULL
        REFERENCES gold.gold_rag_documents(id) ON DELETE CASCADE,
    document_id BIGINT REFERENCES bronze.documents(record_id),
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    page_text TEXT NOT NULL,
    source_extractor TEXT,
    page_content_hash CHAR(64),
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension = 768),
    embedding VECTOR(768),
    model_digest TEXT NOT NULL DEFAULT 'unknown',
    content_hash CHAR(64) NOT NULL,
    embedding_content_hash CHAR(64),
    generated_at TIMESTAMPTZ,
    embedding_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending', 'success', 'error')),
    embedding_error TEXT,
    last_attempt_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rag_document_id, page_number)
);

ALTER TABLE gold.gold_rag_page_index
    ADD COLUMN IF NOT EXISTS embedding_content_hash CHAR(64);

ALTER TABLE gold.gold_rag_documents
    ADD COLUMN IF NOT EXISTS silver_document_id BIGINT
        REFERENCES silver.silver_documents(id);
ALTER TABLE gold.gold_rag_documents
    ADD COLUMN IF NOT EXISTS search_vector TSVECTOR;

ALTER TABLE gold.gold_rag_documents
    ADD COLUMN IF NOT EXISTS context_token_limit INTEGER;
ALTER TABLE gold.gold_rag_documents
    ADD COLUMN IF NOT EXISTS context_window_exceeded BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE gold.gold_rag_documents
    ADD COLUMN IF NOT EXISTS context_warning TEXT;
ALTER TABLE gold.gold_rag_page_index
    ADD COLUMN IF NOT EXISTS document_id BIGINT
        REFERENCES bronze.documents(record_id);
ALTER TABLE gold.gold_rag_page_index
    ADD COLUMN IF NOT EXISTS source_extractor TEXT;
ALTER TABLE gold.gold_rag_page_index
    ADD COLUMN IF NOT EXISTS page_content_hash CHAR(64);
ALTER TABLE gold.gold_rag_page_index
    ADD COLUMN IF NOT EXISTS search_vector TSVECTOR;

UPDATE gold.gold_rag_documents
SET search_vector =
        setweight(to_tsvector('portuguese', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('portuguese', coalesce(version, '')), 'B') ||
        setweight(to_tsvector('portuguese', coalesce(full_text, '')), 'C') ||
        setweight(to_tsvector('portuguese', coalesce(metadata::text, '')), 'D')
WHERE search_vector IS NULL;
UPDATE gold.gold_rag_page_index p
SET document_id = d.document_id,
    source_extractor = d.source_extractor,
    page_content_hash = p.content_hash,
    search_vector = to_tsvector('portuguese', coalesce(p.page_text, ''))
FROM gold.gold_rag_documents d
WHERE d.id = p.rag_document_id
  AND (p.document_id IS NULL OR p.search_vector IS NULL);

CREATE INDEX IF NOT EXISTS idx_silver_document_extractions_document
    ON silver.silver_document_extractions (document_id);
CREATE INDEX IF NOT EXISTS idx_silver_document_extractions_status
    ON silver.silver_document_extractions (processing_status);
CREATE INDEX IF NOT EXISTS idx_silver_document_extractions_extractor
    ON silver.silver_document_extractions (extractor);
CREATE INDEX IF NOT EXISTS idx_silver_documents_document
    ON silver.silver_documents (document_id);
CREATE INDEX IF NOT EXISTS idx_silver_documents_status
    ON silver.silver_documents (docling_processing_status, glm_ocr_processing_status);
CREATE INDEX IF NOT EXISTS idx_silver_page_extractions_document
    ON silver.silver_page_extractions (document_id);
CREATE INDEX IF NOT EXISTS idx_silver_page_extractions_execution
    ON silver.silver_page_extractions (extraction_id);
CREATE INDEX IF NOT EXISTS idx_silver_page_extractions_extractor
    ON silver.silver_page_extractions (extractor);
CREATE INDEX IF NOT EXISTS idx_silver_page_extractions_page
    ON silver.silver_page_extractions (page_number);
CREATE INDEX IF NOT EXISTS idx_silver_page_extractions_status
    ON silver.silver_page_extractions (processing_status);
CREATE INDEX IF NOT EXISTS idx_silver_page_extractions_evaluation
    ON silver.silver_page_extractions (evaluation_status);
CREATE INDEX IF NOT EXISTS idx_silver_page_extractions_hash
    ON silver.silver_page_extractions (content_hash);
CREATE INDEX IF NOT EXISTS idx_gold_rag_documents_document
    ON gold.gold_rag_documents (document_id);
CREATE INDEX IF NOT EXISTS idx_gold_rag_documents_active
    ON gold.gold_rag_documents (document_id) WHERE is_active;
CREATE UNIQUE INDEX IF NOT EXISTS idx_gold_rag_documents_one_active
    ON gold.gold_rag_documents (document_id) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_gold_rag_documents_extractor
    ON gold.gold_rag_documents (source_extractor);
CREATE INDEX IF NOT EXISTS idx_gold_rag_documents_search_vector
    ON gold.gold_rag_documents USING gin (search_vector);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_document
    ON gold.gold_rag_page_index (rag_document_id);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_number
    ON gold.gold_rag_page_index (page_number);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_hash
    ON gold.gold_rag_page_index (content_hash);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_status
    ON gold.gold_rag_page_index (embedding_status);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_source_extractor
    ON gold.gold_rag_page_index (source_extractor);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_document_id
    ON gold.gold_rag_page_index (document_id);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_document_page
    ON gold.gold_rag_page_index (document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_search_vector
    ON gold.gold_rag_page_index USING gin (search_vector);
CREATE INDEX IF NOT EXISTS idx_gold_rag_page_embedding_hnsw
    ON gold.gold_rag_page_index
    USING hnsw (embedding vector_cosine_ops);

DROP VIEW IF EXISTS silver.silver_ocr_performance_summary;

CREATE VIEW silver.silver_ocr_performance_summary AS
SELECT
    p.extractor,
    p.extractor_version,
    COUNT(DISTINCT p.document_id) FILTER (
        WHERE p.evaluation_status = 'success'
    ) AS documents_evaluated,
    COUNT(*) FILTER (WHERE p.evaluation_status = 'success') AS pages_evaluated,
    COUNT(*) FILTER (
        WHERE p.evaluation_status = 'reference_unavailable'
    ) AS pages_without_reference,
    COUNT(*) FILTER (WHERE p.processing_status = 'error') AS pages_with_error,
    AVG(p.quality_score) FILTER (
        WHERE p.evaluation_status = 'success'
    ) AS simple_average_quality,
    SUM(p.quality_score * NULLIF(p.word_count, 0)) /
        NULLIF(SUM(p.word_count) FILTER (
            WHERE p.evaluation_status = 'success'
        ), 0) AS weighted_average_quality,
    AVG((p.quality_metrics ->> 'cer')::numeric) FILTER (
        WHERE p.evaluation_status = 'success'
    ) AS average_cer,
    AVG((p.quality_metrics ->> 'wer')::numeric) FILTER (
        WHERE p.evaluation_status = 'success'
    ) AS average_wer,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'textual_fidelity')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_textual_fidelity,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'content_completeness')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_content_completeness,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'reading_order')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_reading_order,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'structural_preservation')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_structural_preservation,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'lists_preservation')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_lists_preservation,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'tables_preservation')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_tables_preservation,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'numbers_and_references')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_numbers_and_references,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'duplication_control')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_duplication_control,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'noise_control')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_noise_control,
    AVG((p.quality_metrics -> 'evaluation' -> 'scores' ->> 'hallucination_control')::numeric)
        FILTER (WHERE p.evaluation_status = 'success') AS average_hallucination_control,
    AVG(p.processing_time_ms) FILTER (
        WHERE p.processing_status = 'success'
    ) AS average_processing_time_ms,
    100.0 * COUNT(*) FILTER (
        WHERE p.evaluation_status = 'success'
          AND (p.quality_metrics ->> 'requires_manual_review')::boolean
    ) / NULLIF(COUNT(*) FILTER (
        WHERE p.evaluation_status = 'success'
    ), 0) AS manual_review_percent
FROM silver.silver_page_extractions AS p
GROUP BY p.extractor, p.extractor_version;
