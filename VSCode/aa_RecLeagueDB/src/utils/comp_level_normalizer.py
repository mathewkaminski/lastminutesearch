"""Deterministic competition level normalization.

Maps raw competition level labels to standardized single-letter grades:
A = most competitive, B, C, D... descending.
"""

from typing import Optional


COMP_LEVEL_MAP = {
    # A-tier (most competitive)
    "competitive": "A", "a league": "A", "a": "A", "gold": "A",
    "premier": "A", "division 1": "A", "div 1": "A", "elite": "A",
    "advanced": "A", "upper": "A",
    # B-tier
    "intermediate": "B", "b league": "B", "b": "B", "silver": "B",
    "division 2": "B", "div 2": "B", "mid": "B", "middle": "B",
    # C-tier
    "recreational": "C", "c league": "C", "c": "C", "bronze": "C",
    "division 3": "C", "div 3": "C", "house": "C", "social": "C",
    "beginner": "C", "lower": "C", "fun": "C",
    # D-tier
    "d league": "D", "d": "D", "division 4": "D", "div 4": "D",
    "novice": "D",
}


def normalize_comp_level(source_comp_level: Optional[str]) -> Optional[str]:
    """Normalize a raw competition level label to a single letter A-Z.

    Args:
        source_comp_level: Raw label (e.g., "A League", "Recreational", "Gold")

    Returns:
        Single uppercase letter (A=most competitive) or None if unmappable
    """
    if not source_comp_level or not str(source_comp_level).strip():
        return None

    key = str(source_comp_level).strip().lower()
    return COMP_LEVEL_MAP.get(key)
