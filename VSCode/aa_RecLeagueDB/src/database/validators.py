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
    - sport_season_code
    - url_scraped

    Args:
        data: Extracted league data dictionary

    Returns:
        (is_valid, missing_fields)
        is_valid: True if all required fields present
        missing_fields: List of missing/empty field names
    """
    required_fields = ["organization_name", "sport_season_code", "url_scraped"]
    missing = []

    for field in required_fields:
        value = data.get(field)
        if not value or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)

    is_valid = len(missing) == 0
    return is_valid, missing


def calculate_quality_score(data: dict) -> int:
    """Calculate data quality score (0-100) based on field coverage and validity.

    Scoring:
    - Start at 100
    - -5 for each missing important field (dates, venue, fees)
    - -10 for invalid values (negative fees, bad dates, wrong SSS code)
    - -15 for suspicious data (num_teams=1, season_end < start)

    Important fields (for MVP):
    - season_start_date
    - season_end_date
    - day_of_week
    - start_time
    - venue_name
    - team_fee OR individual_fee (at least one)
    - competition_level
    - gender_eligibility

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

    # Check important fields (each missing = -5)
    important_fields = [
        "season_start_date",
        "season_end_date",
        "day_of_week",
        "start_time",
        "venue_name",
        "competition_level",
        "gender_eligibility",
        "num_weeks",
        "players_per_side",
        "registration_deadline",
    ]

    for field in important_fields:
        if not data.get(field):
            score -= 5
            penalties_log.append(f"missing_{field}")

    # Check pricing (need at least one)
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
