-- migrations/004_add_domain_and_listing_type.sql
-- Date: 2026-03-02

ALTER TABLE public.leagues_metadata
  ADD COLUMN IF NOT EXISTS base_domain  TEXT,
  ADD COLUMN IF NOT EXISTS listing_type TEXT DEFAULT 'unknown'
    CONSTRAINT listing_type_values CHECK (listing_type IN ('league', 'drop_in', 'unknown'));

CREATE INDEX IF NOT EXISTS idx_leagues_base_domain  ON public.leagues_metadata(base_domain);
CREATE INDEX IF NOT EXISTS idx_leagues_listing_type ON public.leagues_metadata(listing_type);
