-- migrations/016_venue_name_only_unique.sql
-- Switch venue dedup key from (venue_name, city) to venue_name only.
-- City in leagues_metadata is the campaign city, not the venue's actual city.
-- The venue's real city comes from the Google Places address.

DROP INDEX IF EXISTS idx_venues_name_city;
CREATE UNIQUE INDEX idx_venues_name ON public.venues (LOWER(venue_name));
