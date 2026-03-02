-- migrations/003_add_league_checks_table.sql
-- Date: 2026-03-01

CREATE TABLE IF NOT EXISTS public.league_checks (
    check_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    check_run_id     UUID NOT NULL,
    league_id        UUID REFERENCES public.leagues_metadata(league_id),
    checked_at       TIMESTAMPTZ DEFAULT NOW(),
    old_num_teams    INT,
    new_num_teams    INT,
    division_name    TEXT,
    nav_path         TEXT[],
    screenshot_paths TEXT[],
    status           TEXT CHECK (status IN ('MATCH', 'CHANGED', 'NOT_FOUND', 'ERROR')),
    raw_teams        TEXT[],
    url_checked      TEXT,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_league_checks_league_id  ON public.league_checks(league_id);
CREATE INDEX IF NOT EXISTS idx_league_checks_run_id     ON public.league_checks(check_run_id);
CREATE INDEX IF NOT EXISTS idx_league_checks_checked_at ON public.league_checks(checked_at);
