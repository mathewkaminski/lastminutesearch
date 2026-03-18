"""Confidence scoring for Places API venue lookup results."""

import difflib

SPORTS_TYPES = {
    "park", "stadium", "sports_complex", "gym", "health",
    "establishment", "point_of_interest",
}

AUTO_SAVE_THRESHOLD = 60


def score(venue_name: str, city: str | None, api_result: dict | None) -> int:
    """Calculate confidence score 0-100 for a Places API result.

    Args:
        venue_name: The venue name that was searched.
        city: The city that was searched.
        api_result: Normalized result from PlacesClient.search(), or None.

    Returns:
        Integer confidence score 0-100.
    """
    if api_result is None:
        return 0

    return (
        _name_score(venue_name, api_result.get("name", ""))
        + _city_score(city, api_result.get("formatted_address", ""))
        + _type_score(api_result.get("types", []))
        + _quality_score(api_result.get("user_ratings_total", 0))
    )


def _name_score(searched: str, returned: str) -> int:
    """0-40 points based on fuzzy name match."""
    ratio = difflib.SequenceMatcher(
        None, searched.lower(), returned.lower()
    ).ratio()
    return round(ratio * 40)


def _city_score(city: str | None, formatted_address: str) -> int:
    """0 or 30 points: city appears in returned address."""
    if not city:
        return 0
    return 30 if city.lower() in formatted_address.lower() else 0


def _type_score(types: list[str]) -> int:
    """0 or 20 points: result has at least one sports-relevant type."""
    return 20 if any(t in SPORTS_TYPES for t in types) else 0


def _quality_score(user_ratings_total: int) -> int:
    """0 or 10 points: result has at least one user rating."""
    return 10 if user_ratings_total > 0 else 0
