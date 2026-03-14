-- Migration 010: Three-tier data model — add new Tier 2 columns
-- Date: 2026-03-14

-- New Tier 2 structured data columns
ALTER TABLE leagues_metadata
  ADD COLUMN IF NOT EXISTS team_capacity INTEGER,
  ADD COLUMN IF NOT EXISTS tshirts_included BOOLEAN,
  ADD COLUMN IF NOT EXISTS end_time TIME;

-- Add players_per_side to dedup model comment (documentation only)
COMMENT ON COLUMN leagues_metadata.team_capacity IS 'Tier 2: Max roster size per team';
COMMENT ON COLUMN leagues_metadata.tshirts_included IS 'Tier 2: Whether league provides jerseys/pinnies';
COMMENT ON COLUMN leagues_metadata.end_time IS 'Tier 2: Latest game end time (e.g., 23:00 for 7-11pm window)';
