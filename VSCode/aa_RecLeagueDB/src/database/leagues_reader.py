"""Shared DB query layer for league management pages.

All queries are pre-filtered to listing_type='league' AND is_archived=False.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from src.database.supabase_client import get_client

logger = logging.getLogger(__name__)

# Fields checked in the coverage report
COVERAGE_FIELDS = [
    "day_of_week",
    "start_time",
    "venue_name",
    "team_fee",
    "individual_fee",
    "season_start_date",
    "season_end_date",
    "source_comp_level",
    "gender_eligibility",
    "num_weeks",
]

# Fields that define a unique league (identity model from DATABASE_SCHEMA.md)
_IDENTITY_FIELDS = (
    "organization_name",
    "sport_season_code",
    "season_year",
    "venue_name",
    "day_of_week",
    "source_comp_level",
)


def get_leagues(filters: dict | None = None) -> list[dict]:
    """Return all active league records, optionally filtered.

    Args:
        filters: Optional dict with any of:
            - org_search (str): ilike match on organization_name
            - sport_names (list[str]): exact-match on sport_name
            - days_of_week (list[str]): exact-match multi-select
            - genders (list[str]): exact-match multi-select
            - comp_levels (list[str]): exact-match on standardized_comp_level
            - base_domains (list[str]): exact-match on base_domain
            - quality_min (int): minimum quality_score
            - quality_max (int): maximum quality_score

    Returns:
        List of league record dicts, ordered by quality_score ascending.
    """
    client = get_client()
    listing_types = (filters or {}).get("listing_types", ["league"])
    q = (
        client.table("leagues_metadata")
        .select("*")
        .in_("listing_type", listing_types)
        .eq("is_archived", False)
    )

    if filters:
        if org := filters.get("org_search"):
            q = q.ilike("organization_name", f"%{org}%")
        if sports := filters.get("sport_names"):
            q = q.in_("sport_name", sports)
        if days := filters.get("days_of_week"):
            q = q.in_("day_of_week", days)
        if genders := filters.get("genders"):
            q = q.in_("gender_eligibility", genders)
        if levels := filters.get("comp_levels"):
            q = q.in_("standardized_comp_level", levels)
        if domains := filters.get("base_domains"):
            q = q.in_("base_domain", domains)
        if (qmin := filters.get("quality_min")) is not None:
            q = q.gte("quality_score", qmin)
        if (qmax := filters.get("quality_max")) is not None:
            q = q.lte("quality_score", qmax)

    result = q.order("quality_score").execute()
    return result.data or []


def get_filter_options() -> dict:
    """Return distinct values for dynamic filter dropdowns.

    Returns:
        Dict with keys: sport_names, base_domains, comp_levels, genders.
        Each value is a sorted list of non-null distinct strings.
    """
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("sport_name, base_domain, standardized_comp_level, gender_eligibility")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []

    def _distinct(field: str) -> list[str]:
        vals = {r.get(field) for r in rows if r.get(field)}
        return sorted(vals)

    return {
        "sport_names": _distinct("sport_name"),
        "base_domains": _distinct("base_domain"),
        "comp_levels": _distinct("standardized_comp_level"),
        "genders": _distinct("gender_eligibility"),
    }


def get_quality_summary() -> dict:
    """Return aggregate quality metrics for all active leagues.

    Returns:
        Dict with keys: total, avg_score, pct_good (>=70), pct_poor (<50).
    """
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("quality_score")
        .eq("listing_type", "league")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return {"total": 0, "avg_score": 0.0, "pct_good": 0.0, "pct_poor": 0.0}

    total = len(rows)
    scores = [r.get("quality_score") or 0 for r in rows]
    return {
        "total": total,
        "avg_score": round(sum(scores) / total, 1),
        "pct_good": round(sum(1 for s in scores if s >= 70) * 100 / total, 1),
        "pct_poor": round(sum(1 for s in scores if s < 50) * 100 / total, 1),
    }


def get_field_coverage() -> dict[str, float]:
    """Return % of leagues where each important field is populated.

    Returns:
        Dict of field_name -> coverage percentage (0.0–100.0).
    """
    client = get_client()
    fields_str = ", ".join(["quality_score"] + COVERAGE_FIELDS)
    result = (
        client.table("leagues_metadata")
        .select(fields_str)
        .eq("listing_type", "league")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return {f: 0.0 for f in COVERAGE_FIELDS}

    total = len(rows)
    return {
        field: round(
            sum(1 for r in rows if r.get(field) is not None) * 100 / total, 1
        )
        for field in COVERAGE_FIELDS
    }


def get_duplicate_groups() -> list[dict]:
    """Find suspected duplicate leagues by identity-field grouping.

    Two records are suspected duplicates if they share the same
    (org_name, sport_code, season_year, venue, day_of_week, source_comp_level).

    Returns:
        List of dicts, each with keys 'key' (tuple) and 'records' (list of 2+ rows).
    """
    client = get_client()
    fields = (
        "league_id, organization_name, sport_season_code, season_year, "
        "venue_name, day_of_week, source_comp_level, quality_score, url_scraped, updated_at"
    )
    result = (
        client.table("leagues_metadata")
        .select(fields)
        .eq("listing_type", "league")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []

    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        key = tuple(
            (row.get(f) or "").lower().strip() if isinstance(row.get(f), str)
            else (row.get(f) or "")
            for f in _IDENTITY_FIELDS
        )
        groups[key].append(row)

    return [
        {"key": key, "records": records}
        for key, records in groups.items()
        if len(records) > 1
    ]


def get_duplicate_groups_for_url(url_scraped: str) -> list[dict]:
    """Return duplicate groups scoped to a single url_scraped.

    Same logic as get_duplicate_groups() but pre-filtered to one URL.
    """
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("*")
        .eq("url_scraped", url_scraped)
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []

    from src.database.consolidator import find_within_url_duplicates
    dup_groups = find_within_url_duplicates(rows)

    # Convert ConsolidationGroup → same dict format as get_duplicate_groups()
    groups = []
    id_to_row = {r["league_id"]: r for r in rows}
    for g in dup_groups:
        keep = id_to_row.get(g.keep_id)
        arch = id_to_row.get(g.archive_id)
        if keep and arch:
            groups.append({"records": [keep, arch], "confidence": g.confidence})
    return groups


def archive_league(league_id: str) -> None:
    """Set is_archived=True for a single league record.

    Args:
        league_id: UUID of the league to archive.
    """
    client = get_client()
    client.table("leagues_metadata").update({"is_archived": True}).eq("league_id", league_id).execute()
    logger.info("Archived league %s", league_id)


def add_to_rescrape_queue(urls: list[str]) -> None:
    """Insert URLs into scrape_queue with status PENDING.

    Upserts on url to avoid duplicates if already queued.

    Args:
        urls: List of url_scraped values to re-queue.
    """
    if not urls:
        return
    client = get_client()
    rows = [{"url": url, "status": "PENDING", "source": "rescrape_trigger"} for url in urls]
    client.table("scrape_queue").upsert(rows, on_conflict="url").execute()
    logger.info("Added %d URLs to rescrape queue", len(urls))


def update_num_teams(league_id: str, num_teams: int) -> None:
    """Write a confirmed new team count directly to leagues_metadata.

    Args:
        league_id: UUID of the league to update.
        num_teams: The confirmed number of teams.
    """
    from datetime import datetime, timezone
    client = get_client()
    client.table("leagues_metadata").update({
        "num_teams": num_teams,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("league_id", league_id).execute()
    logger.info("Updated num_teams for league %s → %d", league_id, num_teams)
