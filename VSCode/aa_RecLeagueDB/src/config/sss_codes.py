"""SSS Code utilities for Sport & Season classification.

Format: XYY (3 digits)
- X (1st digit): Season/Seasonality (1-9)
- YY (last 2 digits): Sport code (01-99)

Reference: docs/SSS_CODES.md
"""

from typing import Optional, Dict

# Seasonality codes (1st digit)
SEASON_CODES = {
    "1": "Spring",
    "2": "Summer",
    "3": "Fall",
    "4": "Winter",
    "5": "Spring/Summer",
    "6": "Fall/Winter",
    "7": "Tournament",
    "8": "Youth",
    "9": "Other",
}

SEASON_TO_CODE = {v.lower(): k for k, v in SEASON_CODES.items()}

# Sport codes (last 2 digits)
SPORT_CODES = {
    # Field Sports
    "01": "Soccer",
    "02": "Flag Football",
    "03": "Ultimate Frisbee",
    "04": "Rugby",
    "05": "Lacrosse",
    "06": "Cricket",
    "07": "Kickball",
    "08": "Field Hockey",
    # Court Sports (Indoor)
    "10": "Basketball",
    "11": "Volleyball",
    "12": "Badminton",
    "13": "Pickleball",
    "14": "Squash",
    "15": "Racquetball",
    "16": "Table Tennis",
    # Court Sports (Outdoor)
    "20": "Beach Volleyball",
    "21": "Tennis",
    "22": "Pickleball Outdoor",
    # Ice/Rink Sports
    "30": "Ice Hockey",
    "31": "Broomball",
    "32": "Curling",
    "33": "Figure Skating",
    "34": "Speed Skating",
    "35": "Roller Hockey",
    # Diamond Sports
    "40": "Baseball",
    "41": "Softball",
    "42": "Softball Fast Pitch",
    "43": "Wiffle Ball",
    # Indoor Alternative Sports
    "50": "Dodgeball",
    "51": "Indoor Soccer",
    "52": "Floor Hockey",
    "53": "Handball",
    "54": "Cornhole",
    "55": "Darts",
    "56": "Bowling",
    "57": "Axe Throwing",
    # Water Sports
    "60": "Swimming",
    "61": "Water Polo",
    "62": "Dragon Boat",
    "63": "Kayaking",
    "64": "Stand-Up Paddleboarding",
    # Fitness/Combat Sports
    "70": "Boxing",
    "71": "Kickboxing",
    "72": "Brazilian Jiu-Jitsu",
    "73": "Wrestling",
    "74": "Martial Arts",
    "75": "CrossFit",
    "76": "Bootcamp",
    # Individual/Running Sports
    "80": "Running Club",
    "81": "Triathlon",
    "82": "Cycling",
    "83": "Track & Field",
    # Other/Multi-Sport
    "90": "Multi-Sport Social League",
    "91": "Yard Games",
    "92": "Esports",
    "93": "Chess",
    "94": "Poker League",
    "99": "Other",
}

SPORT_TO_CODE = {v.lower(): k for k, v in SPORT_CODES.items()}


def validate_sss_code(code: str) -> bool:
    """Validate if SSS code is in valid format and exists.

    Args:
        code: 3-digit SSS code (e.g., "201" for Summer Soccer)

    Returns:
        True if valid, False otherwise
    """
    if not code or len(code) != 3:
        return False

    try:
        season_digit = code[0]
        sport_digits = code[1:3]

        return season_digit in SEASON_CODES and sport_digits in SPORT_CODES
    except (IndexError, TypeError):
        return False


def get_season_name(season_code: str) -> Optional[str]:
    """Get season name from season code.

    Args:
        season_code: Single digit season code (e.g., "2" for Summer)

    Returns:
        Season name or None if not found
    """
    return SEASON_CODES.get(season_code)


def get_sport_name(sport_code: str) -> Optional[str]:
    """Get sport name from sport code.

    Args:
        sport_code: Two-digit sport code (e.g., "01" for Soccer)

    Returns:
        Sport name or None if not found
    """
    return SPORT_CODES.get(sport_code)


def build_sss_code(season: str, sport: str) -> Optional[str]:
    """Build SSS code from season and sport names.

    Args:
        season: Season name (e.g., "Summer") or code (e.g., "2")
        sport: Sport name (e.g., "Soccer") or code (e.g., "01")

    Returns:
        SSS code (e.g., "201") or None if not found
    """
    # Handle season
    if len(season) == 1 and season in SEASON_CODES:
        season_code = season
    else:
        season_code = SEASON_TO_CODE.get(season.lower())

    # Handle sport
    if len(sport) == 2 and sport in SPORT_CODES:
        sport_code = sport
    else:
        sport_code = SPORT_TO_CODE.get(sport.lower())

    if season_code and sport_code:
        return f"{season_code}{sport_code}"

    return None


def parse_sss_code(code: str) -> Optional[Dict[str, str]]:
    """Parse SSS code into components.

    Args:
        code: 3-digit SSS code (e.g., "201")

    Returns:
        Dict with 'season', 'sport', 'code' keys, or None if invalid
    """
    if not validate_sss_code(code):
        return None

    season_digit = code[0]
    sport_digits = code[1:3]

    return {
        "code": code,
        "season": get_season_name(season_digit),
        "sport": get_sport_name(sport_digits),
        "season_code": season_digit,
        "sport_code": sport_digits,
    }
