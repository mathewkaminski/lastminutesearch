-- migrations/005_add_venue_sports_days.sql
-- Date: 2026-03-02
-- Add sports and days_of_week summary arrays to venues table

ALTER TABLE public.venues
  ADD COLUMN IF NOT EXISTS sports      TEXT[],
  ADD COLUMN IF NOT EXISTS days_of_week TEXT[];
