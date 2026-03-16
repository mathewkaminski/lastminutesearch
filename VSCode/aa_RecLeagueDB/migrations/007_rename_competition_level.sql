-- Migration 007: Rename competition_level to source_comp_level, add standardized_comp_level
-- Date: 2026-03-15

ALTER TABLE leagues_metadata RENAME COLUMN competition_level TO source_comp_level;
ALTER TABLE leagues_metadata ADD COLUMN standardized_comp_level VARCHAR(1);

-- Backfill standardized values from existing source data
UPDATE leagues_metadata SET standardized_comp_level = 'A' WHERE LOWER(TRIM(source_comp_level)) = 'competitive';
UPDATE leagues_metadata SET standardized_comp_level = 'B' WHERE LOWER(TRIM(source_comp_level)) = 'intermediate';
UPDATE leagues_metadata SET standardized_comp_level = 'C' WHERE LOWER(TRIM(source_comp_level)) = 'recreational';

COMMENT ON COLUMN public.leagues_metadata.source_comp_level IS 'Raw competition level label from the source page';
COMMENT ON COLUMN public.leagues_metadata.standardized_comp_level IS 'Normalized single-letter grade: A=most competitive, B, C, D descending';
