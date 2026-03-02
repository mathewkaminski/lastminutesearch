-- migrations/003b_league_checker_rpc_functions.sql
-- Date: 2026-03-02
-- Run in Supabase SQL editor (cannot be applied via migration runner — uses CREATE OR REPLACE FUNCTION)

-- RPC 1: get_latest_league_checks
-- Returns the most recent check row per league_id.
-- Used by CheckStore.get_latest_check_per_league()
CREATE OR REPLACE FUNCTION get_latest_league_checks()
RETURNS TABLE (
    check_id        UUID,
    league_id       UUID,
    checked_at      TIMESTAMPTZ,
    old_num_teams   INT,
    new_num_teams   INT,
    status          TEXT
) AS $$
    SELECT DISTINCT ON (league_id)
        check_id, league_id, checked_at, old_num_teams, new_num_teams, status
    FROM public.league_checks
    WHERE league_id IS NOT NULL
    ORDER BY league_id, checked_at DESC;
$$ LANGUAGE SQL;


-- RPC 2: get_urls_with_check_age
-- Returns each distinct url_scraped with league count, last checked timestamp, and change flag.
-- Used by CheckStore.get_urls_with_check_age() and the League Checker UI.
CREATE OR REPLACE FUNCTION get_urls_with_check_age()
RETURNS TABLE (
    url_scraped     TEXT,
    org_name        TEXT,
    league_count    BIGINT,
    last_checked_at TIMESTAMPTZ,
    has_changes     BOOLEAN
) AS $$
    SELECT
        lm.url_scraped,
        lm.organization_name    AS org_name,
        COUNT(DISTINCT lm.league_id) AS league_count,
        MAX(lc.checked_at)      AS last_checked_at,
        BOOL_OR(lc.status = 'CHANGED') AS has_changes
    FROM public.leagues_metadata lm
    LEFT JOIN public.league_checks lc ON lc.league_id = lm.league_id
    WHERE lm.is_archived = FALSE
    GROUP BY lm.url_scraped, lm.organization_name
    ORDER BY last_checked_at ASC NULLS FIRST;
$$ LANGUAGE SQL;


-- Verification queries (run after creating functions):
-- SELECT * FROM get_urls_with_check_age() LIMIT 5;
-- SELECT * FROM get_latest_league_checks() LIMIT 5;
