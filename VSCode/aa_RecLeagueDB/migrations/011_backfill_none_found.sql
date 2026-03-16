-- Backfill existing rows where source_comp_level is NULL or empty
-- Sets "None Found" as the sentinel value and "A" as baseline standardized level
UPDATE leagues_metadata
SET source_comp_level = 'None Found',
    standardized_comp_level = 'A'
WHERE source_comp_level IS NULL
   OR TRIM(source_comp_level) = '';
