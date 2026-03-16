"""League ID generation and deduplication logic.

A unique league is defined by 9 fields:
1. organization_name (normalized)
2. sport_name (plain text)
3. season_year (derived from dates)
4. venue_name (normalized)
5. day_of_week
6. source_comp_level (normalized)
7. gender_eligibility
8. num_weeks
9. players_per_side

Matching uses fuzzy key comparison: None/empty on either side is treated
as a wildcard (matches any value).  Both sides must have at least
MIN_OVERLAP_FIELDS non-empty key fields for a match to be valid.
"""

import logging
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Minimum number of non-empty fields that must be present on BOTH sides
# of a comparison for it to count as a match.  Prevents two leagues with
# only org_name + sport_season_code from incorrectly matching.
MIN_OVERLAP_FIELDS = 3


def generate_league_id() -> str:
    """Generate a unique UUID4 as string for new league.

    Returns:
        UUID4 string (36 characters)
    """
    return str(uuid.uuid4())


def normalize_for_comparison(text: Optional[str]) -> str:
    """Normalize text for deduplication comparison.

    Process:
    - Convert to lowercase
    - Strip leading/trailing whitespace
    - Replace multiple spaces with single space
    - Remove special characters except spaces and hyphens

    Args:
        text: Text to normalize

    Returns:
        Normalized text, or empty string if None
    """
    if not text:
        return ""

    # Lowercase and strip
    normalized = str(text).lower().strip()

    # Replace multiple spaces with single space
    while "  " in normalized:
        normalized = normalized.replace("  ", " ")

    return normalized


def extract_season_year(data: dict) -> Optional[int]:
    """Extract season year from league data.

    Uses the maximum year from season_start_date and season_end_date.

    Args:
        data: League data dictionary

    Returns:
        Season year (int) or None if no dates available
    """
    years = []

    # Try to extract year from season_start_date
    if data.get("season_start_date"):
        try:
            date_str = str(data.get("season_start_date"))
            # Handle YYYY-MM-DD format
            year = int(date_str.split("-")[0])
            years.append(year)
        except (ValueError, IndexError, AttributeError):
            pass

    # Try to extract year from season_end_date
    if data.get("season_end_date"):
        try:
            date_str = str(data.get("season_end_date"))
            # Handle YYYY-MM-DD format
            year = int(date_str.split("-")[0])
            years.append(year)
        except (ValueError, IndexError, AttributeError):
            pass

    return max(years) if years else None


def build_uniqueness_key(data: dict) -> dict:
    """Build uniqueness key from league data for deduplication.

    Uniqueness defined by 9 fields (all normalized):
    1. organization_name
    2. sport_name (plain text)
    3. season_year
    4. venue_name
    5. day_of_week
    6. source_comp_level
    7. gender_eligibility
    8. num_weeks
    9. players_per_side

    Args:
        data: League data dictionary

    Returns:
        Dictionary with normalized uniqueness fields
    """
    season_year = extract_season_year(data)

    key = {
        "organization_name": normalize_for_comparison(data.get("organization_name")),
        "sport_name": normalize_for_comparison(data.get("sport_name")),
        "season_year": season_year,
        "venue_name": normalize_for_comparison(data.get("venue_name")),
        "day_of_week": normalize_for_comparison(data.get("day_of_week")),
        "source_comp_level": normalize_for_comparison(data.get("source_comp_level")),
        "gender_eligibility": normalize_for_comparison(data.get("gender_eligibility")),
        "num_weeks": _to_int(data.get("num_weeks")),
        "players_per_side": _to_int(data.get("players_per_side")),
    }

    return key


def _to_int(val) -> Optional[int]:
    """Coerce a value to int for identity comparison, or None."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _is_empty(val) -> bool:
    """Check if a uniqueness key value is empty/unknown."""
    if val is None:
        return True
    if isinstance(val, str) and val.strip() in ("", "none"):
        return True
    return False


def keys_match(key_a: dict, key_b: dict) -> bool:
    """Check if two uniqueness keys represent the same league.

    Rules:
    - Empty/None on either side = wildcard (skip that field)
    - Both non-empty and equal = match on that field
    - Both non-empty and different = not the same league
    - At least MIN_OVERLAP_FIELDS must be non-empty on BOTH sides

    Args:
        key_a: Uniqueness key dict (from build_uniqueness_key)
        key_b: Uniqueness key dict

    Returns:
        True if keys represent the same league
    """
    overlap_count = 0

    for field in key_a:
        val_a = key_a[field]
        val_b = key_b.get(field)

        a_empty = _is_empty(val_a)
        b_empty = _is_empty(val_b)

        if a_empty or b_empty:
            continue

        # Both non-empty: must be equal
        if val_a != val_b:
            return False

        overlap_count += 1

    return overlap_count >= MIN_OVERLAP_FIELDS


def league_display_name(data: dict) -> str:
    """Build a readable label for a league from its fields.

    Example: "5v5 Soccer | Wednesday | Recreational | CoEd"

    Args:
        data: League data dict (raw or prepared)

    Returns:
        Human-readable label string
    """
    parts = []

    # Players per side prefix (e.g. "5v5")
    pps = data.get("players_per_side")
    if pps:
        parts.append(f"{pps}v{pps}")

    # Sport name (direct text field)
    sport = data.get("sport_name")
    if sport:
        parts.append(str(sport).title())

    # Day, level, gender
    for field in ("day_of_week", "source_comp_level", "gender_eligibility"):
        val = data.get(field)
        if val:
            parts.append(str(val).title())

    if not parts:
        return data.get("organization_name", "Unknown")

    return " | ".join(parts)


MIN_PARENT_CHILD_OVERLAP = 1


def _is_parent_child_pair(
    league_a: dict, league_b: dict, parent_map: dict
) -> bool:
    """True if one league's source_url is a child of the other's."""
    url_a = league_a.get("source_url", league_a.get("url_scraped", ""))
    url_b = league_b.get("source_url", league_b.get("url_scraped", ""))
    return (url_a in parent_map and parent_map[url_a] == url_b) or \
           (url_b in parent_map and parent_map[url_b] == url_a)


def keys_match_relaxed(key_a: dict, key_b: dict, min_overlap: int = 1) -> bool:
    """Like keys_match but with a configurable overlap threshold."""
    overlap_count = 0
    for field in key_a:
        val_a = key_a[field]
        val_b = key_b.get(field)
        if _is_empty(val_a) or _is_empty(val_b):
            continue
        if val_a != val_b:
            return False
        overlap_count += 1
    return overlap_count >= min_overlap


IDENTIFYING_FIELDS = [
    "organization_name", "sport_name", "season_year", "venue_name",
    "day_of_week", "source_comp_level", "gender_eligibility",
    "num_weeks", "players_per_side",
]


def deduplicate_batch(
    leagues: List[Dict[str, Any]],
    parent_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Merge duplicate leagues within a single extraction batch.

    Leagues from different pages (home, registration, detail) that
    represent the same league are merged into one record with the
    most complete data.

    Args:
        leagues: List of extracted league dicts

    Returns:
        Deduplicated list (always <= len(leagues))
    """
    if not leagues:
        return []

    groups: List[List[Dict[str, Any]]] = []
    group_keys: List[dict] = []

    for league in leagues:
        key = build_uniqueness_key(league)
        matched_idx = None

        for i, gk in enumerate(group_keys):
            if keys_match(key, gk):
                matched_idx = i
                break

        # Parent-child fallback: relaxed overlap when sport_name matches
        if matched_idx is None and parent_map:
            for i, gk in enumerate(group_keys):
                if _is_parent_child_pair(league, groups[i][0], parent_map):
                    sport_a = normalize_for_comparison(league.get("sport_name"))
                    sport_b = normalize_for_comparison(groups[i][0].get("sport_name"))
                    if sport_a and sport_b and sport_a == sport_b:
                        if keys_match_relaxed(key, gk, MIN_PARENT_CHILD_OVERLAP):
                            matched_idx = i
                            break

        if matched_idx is not None:
            groups[matched_idx].append(league)
            # Refresh the group key with the merged result so subsequent
            # matches benefit from newly-filled fields
            merged = _merge_group(groups[matched_idx])
            group_keys[matched_idx] = build_uniqueness_key(merged)
        else:
            groups.append([league])
            group_keys.append(key)

    result = [_merge_group(group) for group in groups]
    if len(result) < len(leagues):
        logger.info(
            f"Batch dedup: {len(leagues)} extracted -> {len(result)} unique leagues"
        )
    return result


def _merge_group(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge a group of league records that represent the same league.

    The record with the most filled fields becomes the base.
    Remaining nulls are filled from other records.

    Args:
        records: List of league dicts (all same logical league)

    Returns:
        Single merged dict
    """
    if len(records) == 1:
        return records[0]

    # Sort by non-None field count descending (most complete first)
    sorted_recs = sorted(
        records,
        key=lambda r: sum(1 for v in r.values() if v is not None),
        reverse=True,
    )

    merged = sorted_recs[0].copy()
    for supplement in sorted_recs[1:]:
        for field, value in supplement.items():
            if merged.get(field) is None and value is not None:
                merged[field] = value

    # Recalculate identifying_fields_pct after merge
    filled = sum(1 for f in IDENTIFYING_FIELDS if not _is_empty(merged.get(f)))
    merged["identifying_fields_pct"] = round(100 * filled / len(IDENTIFYING_FIELDS), 1)

    return merged


def check_duplicate_league(
    data: dict, supabase_client, table_name: str = "leagues_metadata"
) -> Optional[str]:
    """Check if league already exists based on uniqueness criteria.

    Query Supabase to find if a league with matching uniqueness fields exists.

    Uniqueness fields:
    1. organization_name (normalized)
    2. sport_name (plain text)
    3. season_year (derived)
    4. venue_name (normalized)
    5. day_of_week (normalized)
    6. source_comp_level (normalized)
    7. gender_eligibility (normalized)
    8. num_weeks
    9. players_per_side

    Args:
        data: League data dictionary
        supabase_client: Supabase client instance
        table_name: Table to query (default: "leagues_metadata")

    Returns:
        Existing league_id if duplicate found, None if unique
    """
    try:
        uniqueness_key = build_uniqueness_key(data)

        # Select all fields needed for comparison, scoped by base_domain
        # to avoid scanning the entire table.
        _DEDUP_FIELDS = (
            "league_id, organization_name, sport_name, season_year, "
            "venue_name, day_of_week, source_comp_level, gender_eligibility, "
            "num_weeks, players_per_side"
        )

        query = supabase_client.table(table_name).select(_DEDUP_FIELDS)

        # Scope to same base_domain when available
        base_domain = data.get("base_domain")
        if not base_domain:
            from src.utils.domain_extractor import extract_base_domain
            base_domain = extract_base_domain(data.get("url_scraped"))
        if base_domain:
            query = query.eq("base_domain", base_domain)

        response = query.execute()

        if not response.data:
            return None

        # Client-side comparison using fuzzy key matching
        best_match = None
        best_overlap = 0

        for record in response.data:
            record_key = build_uniqueness_key(record)

            if keys_match(uniqueness_key, record_key):
                # Count overlap to prefer the strongest match
                overlap = sum(
                    1 for f in uniqueness_key
                    if not _is_empty(uniqueness_key[f])
                    and not _is_empty(record_key.get(f))
                    and uniqueness_key[f] == record_key.get(f)
                )
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_match = record.get("league_id")

        if best_match:
            logger.info(
                f"Duplicate league found: {best_match} "
                f"({best_overlap} fields matched)"
            )
            return best_match

        return None

    except Exception as e:
        logger.error(
            f"Error checking for duplicate league: {str(e)}",
            extra={"organization_name": data.get("organization_name")},
        )
        # On error, assume it's new (safer than blocking valid inserts)
        return None


def format_uniqueness_key(key: dict) -> str:
    """Format uniqueness key as readable string for logging.

    Args:
        key: From build_uniqueness_key()

    Returns:
        Formatted key string
    """
    parts = [
        f"org={key.get('organization_name', 'N/A')[:20]}",
        f"sport={key.get('sport_name', 'N/A')[:15]}",
        f"year={key.get('season_year', 'N/A')}",
        f"venue={key.get('venue_name', 'N/A')[:20]}",
        f"dow={key.get('day_of_week', 'N/A')[:3]}",
        f"level={key.get('source_comp_level', 'N/A')[:3]}",
        f"gender={key.get('gender_eligibility', 'N/A')[:3]}",
        f"weeks={key.get('num_weeks', 'N/A')}",
        f"pps={key.get('players_per_side', 'N/A')}",
    ]
    return " | ".join(parts)
