-- migrations/013_add_province_to_venues.sql
-- Add province column to venues; backfill from formatted address.

ALTER TABLE public.venues
    ADD COLUMN IF NOT EXISTS province TEXT;

-- Backfill: Canadian formatted addresses look like "..., ON A1B 2C3, Canada"
UPDATE public.venues
SET province = (
    regexp_match(address, ',\s*(AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\s+')
)[1]
WHERE province IS NULL
  AND address IS NOT NULL;
