BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM silver.gold_promotion_reviews) THEN
        RAISE EXCEPTION 'Promotion review history exists: retain this schema archive';
    END IF;
END $$;

DROP TRIGGER IF EXISTS protect_gold_promotion_reviews
    ON silver.gold_promotion_reviews;
DROP FUNCTION IF EXISTS silver.protect_gold_promotion_reviews();
DROP TABLE silver.gold_promotion_reviews;

COMMIT;
