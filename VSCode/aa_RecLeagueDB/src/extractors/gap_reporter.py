"""Field coverage gap reporting for extracted league data."""

# 19 extractable league data fields
# Excludes: organization_name, sport_season_code (required identifiers),
#           season_year (derived from dates), url_scraped (input)
ALL_LEAGUE_FIELDS: list[str] = [
    "season_start_date",
    "season_end_date",
    "day_of_week",
    "start_time",
    "num_weeks",
    "time_played_per_week",
    "stat_holidays",
    "venue_name",
    "competition_level",
    "gender_eligibility",
    "team_fee",
    "individual_fee",
    "registration_deadline",
    "num_teams",
    "slots_left",
    "has_referee",
    "requires_insurance",
    "insurance_policy_link",
    "players_per_side",
]

# Maps field names to the crawler category that typically contains them
_FIELD_TO_CATEGORY: dict[str, str] = {
    "num_teams": "SCHEDULE",
    "day_of_week": "SCHEDULE",
    "start_time": "SCHEDULE",
    "team_fee": "REGISTRATION",
    "individual_fee": "REGISTRATION",
    "registration_deadline": "REGISTRATION",
    "slots_left": "REGISTRATION",
    "has_referee": "POLICY",
    "requires_insurance": "POLICY",
    "insurance_policy_link": "POLICY",
    "venue_name": "VENUE",
    "season_start_date": "DETAIL",
    "season_end_date": "DETAIL",
    "num_weeks": "DETAIL",
    "time_played_per_week": "DETAIL",
    "competition_level": "DETAIL",
    "gender_eligibility": "DETAIL",
    "players_per_side": "DETAIL",
    "stat_holidays": "DETAIL",
}


def compute_field_coverage(leagues: list[dict]) -> dict:
    """Compute which league fields are populated across all extracted leagues.

    Args:
        leagues: List of extracted league dicts (from yaml_extractor output)

    Returns:
        {
            "covered": ["day_of_week", "venue_name", ...],
            "missing": ["team_fee", "num_teams", ...],
            "coverage_pct": 52.6,
            "missing_categories": {"REGISTRATION": ["team_fee"], "SCHEDULE": ["num_teams"]}
        }
    """
    covered: set[str] = set()
    for league in leagues:
        for field in ALL_LEAGUE_FIELDS:
            if league.get(field) is not None:
                covered.add(field)

    missing = sorted(set(ALL_LEAGUE_FIELDS) - covered)
    coverage_pct = len(covered) / len(ALL_LEAGUE_FIELDS) * 100 if ALL_LEAGUE_FIELDS else 0.0

    return {
        "covered": sorted(covered),
        "missing": missing,
        "coverage_pct": round(coverage_pct, 1),
        "missing_categories": map_fields_to_categories(missing),
    }


def map_fields_to_categories(fields: list[str]) -> dict[str, list[str]]:
    """Map a list of field names to their crawler field categories.

    Args:
        fields: List of field names (typically the 'missing' list from compute_field_coverage)

    Returns:
        {"SCHEDULE": ["num_teams"], "REGISTRATION": ["team_fee", "individual_fee"], ...}
    """
    result: dict[str, list[str]] = {}
    for field in fields:
        category = _FIELD_TO_CATEGORY.get(field)
        if category:
            result.setdefault(category, []).append(field)
    return result
