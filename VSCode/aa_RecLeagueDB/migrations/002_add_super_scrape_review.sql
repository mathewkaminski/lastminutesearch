-- migrations/002_add_super_scrape_review.sql
-- Review queue for super scraper borderline contradictions

CREATE TABLE IF NOT EXISTS super_scrape_review (
    review_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url               TEXT NOT NULL,
    extracted         JSONB NOT NULL,          -- new extracted league data
    existing_league_id UUID REFERENCES leagues_metadata(league_id),
    reason            TEXT,                    -- which fields contradicted
    status            TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING / ACCEPTED / REJECTED
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ
);

CREATE INDEX idx_ssr_url ON super_scrape_review(url);
CREATE INDEX idx_ssr_status ON super_scrape_review(status);
