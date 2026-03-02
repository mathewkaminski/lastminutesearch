"""Rule-based listing type classifier for leagues_metadata records."""
import re

_DROPIN_KEYWORDS = re.compile(
    r"drop.?in|pick.?up|one.?time|casual|social night|open play",
    re.IGNORECASE,
)

_DROPIN_PRICE_THRESHOLD = 20.0  # USD/CAD
_LEAGUE_MIN_WEEKS = 4


def classify_listing_type(record: dict) -> str:
    """Classify a league record as 'league', 'drop_in', or 'unknown'.

    Rules (first match wins):
      1. Keyword match in league_name or division_name → drop_in
      2. num_weeks is 1 or None AND individual_fee < $20 → drop_in
      3. num_weeks >= 4 OR team_fee > 0 → league
      4. No match → unknown

    Args:
        record: Dict with any subset of leagues_metadata fields.

    Returns:
        One of: 'league', 'drop_in', 'unknown'
    """
    name_fields = " ".join(
        str(record.get(f) or "") for f in ("league_name", "division_name")
    )

    # Rule 1: keyword match
    if _DROPIN_KEYWORDS.search(name_fields):
        return "drop_in"

    num_weeks = record.get("num_weeks")
    individual_fee = record.get("individual_fee")
    team_fee = record.get("team_fee")

    # Rule 2: short/no duration + cheap price
    short_duration = num_weeks is None or num_weeks <= 1
    cheap = individual_fee is not None and individual_fee < _DROPIN_PRICE_THRESHOLD
    if short_duration and cheap:
        return "drop_in"

    # Rule 3: multi-week or team pricing → league
    if (num_weeks is not None and num_weeks >= _LEAGUE_MIN_WEEKS) or (team_fee is not None and team_fee > 0):
        return "league"

    return "unknown"
