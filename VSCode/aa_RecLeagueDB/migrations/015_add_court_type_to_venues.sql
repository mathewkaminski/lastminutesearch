-- migrations/015_add_court_type_to_venues.sql
-- Add court type classification columns to venues.

ALTER TABLE public.venues
    ADD COLUMN IF NOT EXISTS court_type_broad       TEXT,
    ADD COLUMN IF NOT EXISTS court_type_broad_conf  INT CHECK (court_type_broad_conf BETWEEN 0 AND 100),
    ADD COLUMN IF NOT EXISTS court_type_specific    TEXT,
    ADD COLUMN IF NOT EXISTS court_type_specific_conf INT CHECK (court_type_specific_conf BETWEEN 0 AND 100);
