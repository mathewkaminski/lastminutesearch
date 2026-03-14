"""Data validation and quality scoring for extracted league data."""

import logging
from typing import Tuple, List, Optional
from datetime import datetime

from src.config.sss_codes import validate_sss_code

logger = logging.getLogger(__name__)


def validate_required_fields(data: dict) -> Tuple[bool, List[str]]:
    """Validate that required fields are present and non-empty.

    Required fields:
    - organization_name
    - sport_name (or sport_season_code as fallback)
    - url_scraped

    Args:
        data: Extracted league data dictionary

    Returns:
        (is_valid, missing_fields)
        is_valid: True if all required fields present
        missing_fields: List of missing/empty field names
    """
    missing = []

    for field in ("organization_name", "url_scraped"):
        value = data.get(field)
        if not value or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)

    # sport_name is primary; sport_season_code accepted as fallback
    sport_name = data.get("sport_name")
    sport_code = data.get("sport_season_code")
    has_sport = bool(sport_name and str(sport_name).strip()) or bool(
        sport_code and str(sport_code).strip()
    )
    if not has_sport:
        missing.append("sport_name")

    is_valid = len(missing) == 0
    return is_valid, missing


def calculate_quality_score(data: dict) -> int:
    """Calculate data quality score (0-100) based on three-tier field coverage.

    Scoring:
    - Start at 100
    - Required fields missing: -20 each (org_name, sport_season_code, url)
    - Tier 1 (identifier) fields missing: -8 each
    - Tier 2 (structured data) fields missing: -3 each
    - Pricing missing (neither fee): -8
    - Invalid values: -10 each
    - Suspicious data: -15 each
    - Staleness: -20 to -30

    Args:
        data: Extracted league data dictionary

    Returns:
        Quality score (0-100)
    """
    score = 100
    penalties_log = []

    # Validate required fields (already validated, but check again)
    if not data.get("organization_name"):
        score -= 20
        penalties_log.append("missing_organization_name")
    if not data.get("sport_season_code"):
        score -= 20
        penalties_log.append("missing_sport_season_code")
    if not data.get("url_scraped"):
        score -= 20
        penalties_log.append("missing_url_scraped")

    # Tier 1: Identifier fields (missing = -8 each)
    tier1_fields = [
        "season_start_date",
        "season_end_date",
        "day_of_week",
        "num_weeks",
        "venue_name",
        "competition_level",
        "gender_eligibility",
        "has_referee",
        "players_per_side",
    ]

    for field in tier1_fields:
        if not data.get(field):
            score -= 8
            penalties_log.append(f"missing_t1_{field}")

    # Tier 2: Structured data fields (missing = -3 each)
    tier2_fields = [
        "start_time",
        "time_played_per_week",
        "registration_deadline",
        "num_teams",
    ]

    for field in tier2_fields:
        if not data.get(field):
            score -= 3
            penalties_log.append(f"missing_t2_{field}")

    # Check pricing (need at least one) — important enough for -8
    if not data.get("team_fee") and not data.get("individual_fee"):
        score -= 8
        penalties_log.append("missing_team_fee_and_individual_fee")

    # Check invalid values
    if data.get("sport_season_code"):
        if not validate_sss_code(str(data.get("sport_season_code"))):
            score -= 10
            penalties_log.append("invalid_sport_season_code")

    # Check for negative or zero fees
    if data.get("team_fee"):
        try:
            fee = float(data.get("team_fee"))
            if fee <= 0:
                score -= 10
                penalties_log.append("invalid_team_fee_negative_or_zero")
        except (ValueError, TypeError):
            score -= 10
            penalties_log.append("invalid_team_fee_not_numeric")

    if data.get("individual_fee"):
        try:
            fee = float(data.get("individual_fee"))
            if fee <= 0:
                score -= 10
                penalties_log.append("invalid_individual_fee_negative_or_zero")
        except (ValueError, TypeError):
            score -= 10
            penalties_log.append("invalid_individual_fee_not_numeric")

    # Check for suspicious data patterns
    # Suspicious: num_teams = 1 (probably extraction error)
    if data.get("num_teams"):
        try:
            num_teams = int(data.get("num_teams"))
            if num_teams == 1:
                score -= 15
                penalties_log.append("suspicious_num_teams_equals_one")
            elif num_teams <= 0 or num_teams > 1000:
                score -= 10
                penalties_log.append("suspicious_num_teams_out_of_range")
        except (ValueError, TypeError):
            pass

    # Check date validity
    if data.get("season_start_date") and data.get("season_end_date"):
        try:
            # Try to parse as string dates (YYYY-MM-DD)
            start = datetime.strptime(
                str(data.get("season_start_date")), "%Y-%m-%d"
            ).date()
            end = datetime.strptime(str(data.get("season_end_date")), "%Y-%m-%d").date()

            if end < start:
                score -= 15
                penalties_log.append("season_end_before_season_start")
            elif (end - start).days > 365:
                score -= 5
                penalties_log.append("season_duration_over_365_days")
        except (ValueError, TypeError):
            score -= 10
            penalties_log.append("invalid_date_format")

    # Staleness penalty: de-prioritize old/ancient seasons
    start_str = data.get("season_start_date") or data.get("season_end_date")
    if start_str:
        try:
            season_date = datetime.strptime(str(start_str), "%Y-%m-%d").date()
            age_days = (datetime.utcnow().date() - season_date).days
            if age_days > 730:  # >2 years old
                score -= 30
                penalties_log.append("stale_season_over_2_years")
            elif age_days > 365:  # >1 year old
                score -= 20
                penalties_log.append("stale_season_over_1_year")
        except (ValueError, TypeError):
            pass

    # Ensure score is within bounds
    score = max(0, min(100, score))

    logger.debug(
        f"Quality score: {score}, penalties: {penalties_log}",
        extra={"organization_name": data.get("organization_name")},
    )

    return score


def validate_extracted_data(data: dict) -> Tuple[bool, dict]:
    """Validate extracted data and return validation result.

    Args:
        data: Extracted league data dictionary

    Returns:
        (is_valid, validation_result)
        is_valid: True if data passes validation
        validation_result: Dict with validation details:
            - is_valid (bool)
            - missing_required (list)
            - quality_score (int 0-100)
            - errors (list of validation errors)
    """
    result = {
        "is_valid": False,
        "missing_required": [],
        "quality_score": 0,
        "errors": [],
    }

    # Check required fields
    has_required, missing_required = validate_required_fields(data)
    result["missing_required"] = missing_required

    if not has_required:
        result["errors"].append(
            f"Missing required fields: {', '.join(missing_required)}"
        )
        return False, result

    # Calculate quality score
    quality_score = calculate_quality_score(data)
    result["quality_score"] = quality_score

    # Determine if valid (quality score >= 50 is acceptable for MVP)
    # But at minimum, must have required fields
    result["is_valid"] = has_required

    return result["is_valid"], result


def format_validation_report(validation_result: dict) -> str:
    """Format validation result as readable report.

    Args:
        validation_result: From validate_extracted_data()

    Returns:
        Formatted report string
    """
    report = []
    report.append(f"Quality Score: {validation_result['quality_score']}/100")

    if validation_result["missing_required"]:
        report.append(f"Missing Required: {', '.join(validation_result['missing_required'])}")

    if validation_result["errors"]:
        report.append("Errors:")
        for error in validation_result["errors"]:
            report.append(f"  - {error}")

    if validation_result["is_valid"]:
        report.append("✅ Valid")
    else:
        report.append("❌ Invalid")

    return "\n".join(report)
