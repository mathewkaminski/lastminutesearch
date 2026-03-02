"""Query generator for building and managing search queries.

This module handles:
- Building Google search query strings
- Generating normalized query fingerprints for deduplication
- Detecting duplicate queries to prevent re-searching
- Creating all city × sport × season combinations from user input
"""

import logging
from typing import List, Dict, Optional, Tuple
from src.database.supabase_client import get_client

logger = logging.getLogger(__name__)


def build_query(
    city: str,
    sport: str,
    season: str = None
) -> str:
    """Build a Google search query string.

    Pattern: "{city} {season} {sport} league" or "{city} {sport} league"

    Args:
        city: City name (e.g., "Toronto")
        sport: Sport name (e.g., "soccer")
        season: Optional season (e.g., "summer")

    Returns:
        Formatted query string

    Examples:
        >>> build_query("Toronto", "soccer", "summer")
        "Toronto summer soccer league"

        >>> build_query("Chicago", "basketball")
        "Chicago basketball league"
    """
    if season:
        return f"{city} {season} {sport} league"
    return f"{city} {sport} league"


def generate_query_fingerprint(
    city: str,
    state_province: str = None,
    country: str = None,
    sport: str = None,
    season: str = None,
    year: int = None
) -> str:
    """Generate normalized query identity for deduplication.

    Fingerprint format: "city|state|country|sport|season|year" (all lowercase)
    This allows us to detect if we've already searched the same combination.

    Args:
        city: City name
        state_province: State/province (optional)
        country: Country code (optional - no default, makes system country-agnostic)
        sport: Sport name
        season: Season name (optional)
        year: Year (optional)

    Returns:
        Normalized fingerprint string

    Examples:
        >>> generate_query_fingerprint("Toronto", sport="soccer")
        "toronto|||soccer||"

        >>> generate_query_fingerprint("Toronto", country="CA", sport="soccer", season="summer", year=2024)
        "toronto||ca|soccer|summer|2024"

        >>> generate_query_fingerprint("Toronto", country="US", sport="Soccer")
        "toronto||us|soccer||"  # Case-insensitive
    """
    parts = [
        (city or "").lower().strip(),
        (state_province or "").lower().strip(),
        (country or "").lower().strip(),
        (sport or "").lower().strip(),
        (season or "").lower().strip(),
        str(year) if year else ""
    ]
    return "|".join(parts)


def check_duplicate_query(
    fingerprint: str,
    days: int = 30
) -> bool:
    """Check if a query was already executed recently.

    Args:
        fingerprint: Query fingerprint from generate_query_fingerprint()
        days: Look back this many days (default: 30)

    Returns:
        True if duplicate found, False if query is new

    Raises:
        Exception: If database query fails
    """
    try:
        client = get_client()

        # Query search_queries for matching fingerprint from last N days
        result = client.table("search_queries").select("query_id").eq(
            "query_fingerprint", fingerprint
        ).gte(
            "search_date", f"now() - interval '{days} days'"
        ).execute()

        is_duplicate = len(result.data) > 0

        if is_duplicate:
            logger.debug(f"Duplicate query detected (last {days} days): {fingerprint}")
        else:
            logger.debug(f"New query: {fingerprint}")

        return is_duplicate

    except Exception as e:
        logger.error(f"Failed to check duplicate query: {str(e)}")
        raise


def parse_multiline_input(text: str) -> List[str]:
    """Parse multi-line text input from user (cities/sports).

    Handles:
    - Strips whitespace from each line
    - Ignores empty lines
    - Handles various line endings

    Args:
        text: Multi-line string (e.g., "Toronto\nChicago\nNew York")

    Returns:
        List of cleaned values

    Examples:
        >>> parse_multiline_input("Toronto\\nChicago\\n  New York  \\n")
        ["Toronto", "Chicago", "New York"]
    """
    if not text:
        return []

    lines = text.split("\n")
    cleaned = [line.strip() for line in lines if line.strip()]
    return cleaned


def generate_queries_from_input(
    cities: List[str],
    sports: List[str],
    seasons: List[str] = None,
    country: str = None,
    state_province: str = None,
    year: int = None,
    check_duplicates: bool = True,
    duplicate_days: int = 30
) -> Tuple[List[Dict], List[Dict]]:
    """Generate all city × sport × season query combinations from user input.

    This creates the full search matrix while filtering out duplicates.

    Args:
        cities: List of city names
        sports: List of sport names
        seasons: Optional list of seasons (default: None = no season filter)
        country: Country code (optional - no default, makes system country-agnostic)
        state_province: Optional state/province code
        year: Optional year for filtering
        check_duplicates: Check database for duplicate queries (default: True)
        duplicate_days: How many days back to check for duplicates (default: 30)

    Returns:
        Tuple of (new_queries, duplicate_queries):
        - new_queries: List of query dicts ready to execute
        - duplicate_queries: List of query dicts that were skipped (already searched)

        Each query dict contains:
        {
            'query_text': str,
            'city': str,
            'sport': str,
            'season': str or None,
            'country': str,
            'state_province': str or None,
            'year': int or None,
            'query_fingerprint': str
        }

    Examples:
        >>> queries, dupes = generate_queries_from_input(
        ...     cities=["Toronto", "Chicago"],
        ...     sports=["soccer", "basketball"],
        ...     check_duplicates=False
        ... )
        >>> len(queries)  # 2 cities × 2 sports = 4 queries
        4
    """
    new_queries = []
    duplicate_queries = []

    # Handle None/empty seasons
    seasons_list = seasons if seasons else [None]

    # Generate all combinations
    total_combinations = len(cities) * len(sports) * len(seasons_list)
    logger.info(f"Generating queries: {len(cities)} cities × {len(sports)} sports × {len(seasons_list)} seasons = {total_combinations}")

    for city in cities:
        for sport in sports:
            for season in seasons_list:
                try:
                    # Build the query text
                    query_text = build_query(city, sport, season)

                    # Generate fingerprint
                    fingerprint = generate_query_fingerprint(
                        city=city,
                        state_province=state_province,
                        country=country,
                        sport=sport,
                        season=season,
                        year=year
                    )

                    # Check for duplicates if enabled
                    is_duplicate = False
                    if check_duplicates:
                        is_duplicate = check_duplicate_query(fingerprint, duplicate_days)

                    # Build query dict
                    query_dict = {
                        'query_text': query_text,
                        'city': city,
                        'sport': sport,
                        'season': season,
                        'country': country,
                        'state_province': state_province,
                        'year': year,
                        'query_fingerprint': fingerprint
                    }

                    if is_duplicate:
                        duplicate_queries.append(query_dict)
                        logger.debug(f"Skipping duplicate: {query_text}")
                    else:
                        new_queries.append(query_dict)
                        logger.debug(f"Added new query: {query_text}")

                except Exception as e:
                    logger.error(f"Error generating query ({city}, {sport}, {season}): {str(e)}")
                    continue

    logger.info(
        f"Query generation complete: {len(new_queries)} new, "
        f"{len(duplicate_queries)} duplicates"
    )

    return new_queries, duplicate_queries
