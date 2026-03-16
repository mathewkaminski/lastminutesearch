-- Migration: Create leagues_metadata table
-- Purpose: Store structured league metadata extracted from websites
-- Created: 2026-02-16
-- Status: Phase 1 - MVP Schema

CREATE TABLE IF NOT EXISTS public.leagues_metadata (
    -- Identifiers
    league_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID, -- FK to organizations (populate in future phase)
    url_id UUID, -- FK to urls (populate in future phase)
    organization_name TEXT NOT NULL,
    url_scraped TEXT NOT NULL,

    -- Sport/Season Classification
    sport_season_code CHAR(3) NOT NULL,
    season_year INT, -- Derived from max(start_date, end_date)
    season_start_date DATE,
    season_end_date DATE,

    -- Scheduling
    day_of_week TEXT, -- Monday-Sunday
    start_time TIME,
    num_weeks INT,
    time_played_per_week INTERVAL,
    stat_holidays JSONB, -- Holiday schedule exceptions

    -- Venue
    venue_name TEXT,

    -- Competition
    source_comp_level TEXT,
    standardized_comp_level VARCHAR(1),
    gender_eligibility TEXT, -- Mens, Womens, CoEd, Other, Unsure

    -- Pricing
    team_fee DECIMAL(10,2),
    individual_fee DECIMAL(10,2),
    registration_deadline DATE,

    -- Capacity
    num_teams INT,
    slots_left INT,

    -- Policies
    has_referee BOOLEAN,
    requires_insurance BOOLEAN,
    insurance_policy_link TEXT,

    -- Quality
    quality_score INT CHECK (quality_score >= 0 AND quality_score <= 100),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_archived BOOLEAN DEFAULT FALSE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_leagues_org_name ON public.leagues_metadata(organization_name);
CREATE INDEX IF NOT EXISTS idx_leagues_sss_code ON public.leagues_metadata(sport_season_code);
CREATE INDEX IF NOT EXISTS idx_leagues_season_year ON public.leagues_metadata(season_year);
CREATE INDEX IF NOT EXISTS idx_leagues_org_id ON public.leagues_metadata(organization_id);
CREATE INDEX IF NOT EXISTS idx_leagues_url_id ON public.leagues_metadata(url_id);

-- Comments for documentation
COMMENT ON TABLE public.leagues_metadata IS 'Structured league metadata extracted from websites. Uniqueness: (org_name, sss_code, season_year, venue_name, day_of_week, competition_level, gender_eligibility, num_weeks)';
COMMENT ON COLUMN public.leagues_metadata.league_id IS 'Unique identifier for this league offering';
COMMENT ON COLUMN public.leagues_metadata.organization_id IS 'Foreign key to organizations table (future)';
COMMENT ON COLUMN public.leagues_metadata.url_id IS 'Foreign key to urls table (future)';
COMMENT ON COLUMN public.leagues_metadata.sport_season_code IS 'SSS format: XYY (X=season 1-9, YY=sport 01-99)';
COMMENT ON COLUMN public.leagues_metadata.quality_score IS 'Data quality score 0-100 based on field coverage';
