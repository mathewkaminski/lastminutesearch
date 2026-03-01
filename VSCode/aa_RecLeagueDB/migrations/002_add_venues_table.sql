-- Migration: Add venues table + city/venue_id to leagues_metadata
-- Date: 2026-03-01

-- 1. Create venues table
CREATE TABLE IF NOT EXISTS public.venues (
    venue_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_name        TEXT NOT NULL,
    city              TEXT,
    address           TEXT,
    lat               DECIMAL(10,7),
    lng               DECIMAL(10,7),
    google_place_id   TEXT UNIQUE,
    confidence_score  INT CHECK (confidence_score BETWEEN 0 AND 100),
    manually_verified BOOLEAN DEFAULT FALSE,
    raw_api_response  JSONB,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Prevent duplicate venue+city entries
CREATE UNIQUE INDEX IF NOT EXISTS idx_venues_name_city
    ON public.venues (LOWER(venue_name), LOWER(city));

-- 2. Add venue_id + city to leagues_metadata
ALTER TABLE public.leagues_metadata
    ADD COLUMN IF NOT EXISTS venue_id UUID REFERENCES public.venues(venue_id),
    ADD COLUMN IF NOT EXISTS city TEXT;

-- 3. One-time backfill: populate city from search pipeline
UPDATE public.leagues_metadata lm
SET city = sq.city
FROM public.scrape_queue sc
JOIN public.search_results sr ON sc.source_result_id = sr.result_id
JOIN public.search_queries sq  ON sr.query_id = sq.query_id
WHERE lm.url_scraped = sc.url
  AND lm.city IS NULL;

-- 4. Indexes
CREATE INDEX IF NOT EXISTS idx_leagues_city     ON public.leagues_metadata(city);
CREATE INDEX IF NOT EXISTS idx_leagues_venue_id ON public.leagues_metadata(venue_id);
CREATE INDEX IF NOT EXISTS idx_venues_place_id  ON public.venues(google_place_id);
