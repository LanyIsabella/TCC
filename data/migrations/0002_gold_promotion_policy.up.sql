BEGIN;

CREATE TABLE IF NOT EXISTS silver.gold_promotion_reviews (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    page_extraction_id BIGINT NOT NULL
        REFERENCES silver.silver_page_extractions(id),
    result_fingerprint CHAR(64) NOT NULL,
    evaluation_id UUID NOT NULL,
    evaluation_config_fingerprint CHAR(64) NOT NULL,
    reviewer TEXT NOT NULL CHECK (btrim(reviewer) <> ''),
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    criteria JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS gold_promotion_reviews_page
    ON silver.gold_promotion_reviews(page_extraction_id, reviewed_at DESC);

CREATE OR REPLACE FUNCTION silver.protect_gold_promotion_reviews()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Gold promotion reviews are append-only';
END $$;
DROP TRIGGER IF EXISTS protect_gold_promotion_reviews
    ON silver.gold_promotion_reviews;
CREATE TRIGGER protect_gold_promotion_reviews
    BEFORE UPDATE OR DELETE ON silver.gold_promotion_reviews
    FOR EACH ROW EXECUTE FUNCTION silver.protect_gold_promotion_reviews();

COMMIT;
