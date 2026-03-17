-- migrations/014_add_google_name_to_venues.sql
-- Add google_name column to store the name returned by Google Places API,
-- distinct from venue_name (the scraped name used as the join key).

ALTER TABLE public.venues
    ADD COLUMN IF NOT EXISTS google_name TEXT;

-- Backfill from stored raw_api_response (results[0].name)
UPDATE public.venues
SET google_name = raw_api_response -> 'results' -> 0 ->> 'name'
WHERE google_name IS NULL
  AND raw_api_response IS NOT NULL;
