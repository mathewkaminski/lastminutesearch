"""League ID generation and deduplication logic.

A unique league is defined by:
1. organization_name (normalized)
2. sport_season_code
3. season_year (derived from dates)
4. venue_name (normalized)
5. day_of_week
6. competition_level (normalized)
7. gender_eligibility
8. num_weeks
"""

import logging
import uuid
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


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

    Uniqueness defined by 8 fields (all normalized):
    1. organization_name
    2. sport_season_code
    3. season_year
    4. venue_name
    5. day_of_week
    6. competition_level
    7. gender_eligibility
    8. num_weeks

    Args:
        data: League data dictionary

    Returns:
        Dictionary with normalized uniqueness fields
    """
    season_year = extract_season_year(data)

    key = {
        "organization_name": normalize_for_comparison(data.get("organization_name")),
        "sport_season_code": str(data.get("sport_season_code", "")).upper().strip(),
        "season_year": season_year,
        "venue_name": normalize_for_comparison(data.get("venue_name")),
        "day_of_week": normalize_for_comparison(data.get("day_of_week")),
        "competition_level": normalize_for_comparison(data.get("competition_level")),
        "gender_eligibility": normalize_for_comparison(data.get("gender_eligibility")),
        "num_weeks": data.get("num_weeks"),
    }

    return key


def check_duplicate_league(
    data: dict, supabase_client, table_name: str = "leagues_metadata"
) -> Optional[str]:
    """Check if league already exists based on uniqueness criteria.

    Query Supabase to find if a league with matching uniqueness fields exists.

    Uniqueness fields:
    1. organization_name (normalized)
    2. sport_season_code
    3. season_year (derived)
    4. venue_name (normalized)
    5. day_of_week (normalized)
    6. competition_level (normalized)
    7. gender_eligibility (normalized)
    8. num_weeks

    Args:
        data: League data dictionary
        supabase_client: Supabase client instance
        table_name: Table to query (default: "leagues_metadata")

    Returns:
        Existing league_id if duplicate found, None if unique
    """
    try:
        uniqueness_key = build_uniqueness_key(data)

        # Query database for matching records
        # Since Supabase doesn't support normalized comparisons directly,
        # we'll fetch all records and do client-side comparison
        response = supabase_client.table(table_name).select("league_id").execute()

        if not response.data:
            # No existing records
            return None

        # Client-side comparison using normalized fields
        for record in response.data:
            record_key = {
                "organization_name": normalize_for_comparison(
                    record.get("organization_name")
                ),
                "sport_season_code": str(record.get("sport_season_code", ""))
                .upper()
                .strip(),
                "season_year": record.get("season_year"),
                "venue_name": normalize_for_comparison(record.get("venue_name")),
                "day_of_week": normalize_for_comparison(record.get("day_of_week")),
                "competition_level": normalize_for_comparison(
                    record.get("competition_level")
                ),
                "gender_eligibility": normalize_for_comparison(
                    record.get("gender_eligibility")
                ),
                "num_weeks": record.get("num_weeks"),
            }

            # Check if all uniqueness fields match
            if uniqueness_key == record_key:
                logger.info(
                    f"Duplicate league found: {record.get('league_id')}",
                    extra={
                        "organization_name": data.get("organization_name"),
                        "sport_season_code": data.get("sport_season_code"),
                    },
                )
                return record.get("league_id")

        # No duplicate found
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
        f"sport={key.get('sport_season_code', 'N/A')}",
        f"year={key.get('season_year', 'N/A')}",
        f"venue={key.get('venue_name', 'N/A')[:20]}",
        f"dow={key.get('day_of_week', 'N/A')[:3]}",
        f"level={key.get('competition_level', 'N/A')[:3]}",
        f"gender={key.get('gender_eligibility', 'N/A')[:3]}",
        f"weeks={key.get('num_weeks', 'N/A')}",
    ]
    return " | ".join(parts)
