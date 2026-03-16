"""Deterministic competition level normalization.

Maps raw competition level labels to standardized grades:
A, A+, A-, B, B+, B-, C, C+, C-, D, D+, D-

Two-pass approach:
1. Exact match against COMP_LEVEL_MAP
2. Fallback parser: detect base-level word + modifier word
"""

from typing import Optional


COMP_LEVEL_MAP = {
    # A-tier (most competitive)
    "competitive": "A", "a league": "A", "a": "A", "gold": "A",
    "premier": "A", "division 1": "A", "div 1": "A", "div a": "A",
    "elite": "A", "advanced": "A", "upper": "A", "prem": "A",
    # B-tier
    "intermediate": "B", "b league": "B", "b": "B", "silver": "B",
    "division 2": "B", "div 2": "B", "div b": "B",
    "mid": "B", "middle": "B",
    "open": "B", "all skill levels": "B", "all levels": "B",
    # C-tier
    "recreational": "C", "rec": "C", "c league": "C", "c": "C", "bronze": "C",
    "division 3": "C", "div 3": "C", "div c": "C",
    "house": "C", "social": "C",
    "beginner": "C", "lower": "C", "fun": "C",
    # D-tier
    "d league": "D", "d": "D", "division 4": "D", "div 4": "D", "div d": "D",
    "novice": "D",
    # Sentinel — no comp level found on page
    "none found": "A",
}

# Words that identify the base tier
_BASE_WORDS = {
    "competitive": "A", "elite": "A", "premier": "A", "advanced": "A",
    "intermediate": "B", "inter": "B",
    "recreational": "C", "rec": "C",
    "novice": "D", "beginner": "C",
}

# Words that push the grade up (+) or down (-)
_UP_MODIFIERS = {"high", "upper", "plus", "advanced", "competitive"}
_DOWN_MODIFIERS = {"low", "lower", "beginner", "really", "intro", "basic"}


def _fallback_parse(key: str) -> Optional[str]:
    """Parse compound labels like 'High Intermediate' -> 'B+'.

    Splits the label into words, identifies a base tier and an optional
    modifier, then combines them.
    """
    words = key.split()
    if not words:
        return None

    base = None
    modifier = None

    for word in words:
        if word in _BASE_WORDS and base is None:
            base = _BASE_WORDS[word]
        if word in _UP_MODIFIERS and modifier is None:
            modifier = "+"
        if word in _DOWN_MODIFIERS and modifier is None:
            modifier = "-"

    # Handle "rec/intermediate" style slash-separated labels
    if base is None and "/" in key:
        parts = [p.strip() for p in key.split("/")]
        bases = [_BASE_WORDS[p] for p in parts if p in _BASE_WORDS]
        if bases:
            # Take the higher tier (lower letter) and add +
            base = min(bases)
            modifier = "+"

    if base is None:
        return None

    return f"{base}{modifier}" if modifier else base


def normalize_comp_level(source_comp_level: Optional[str]) -> Optional[str]:
    """Normalize a raw competition level label to a standardized grade.

    Returns grades like A, B+, C-, D, etc.
    A = most competitive, D = least. + = high end of tier, - = low end.

    Args:
        source_comp_level: Raw label (e.g., "A League", "High Rec", "Beginner Rec")

    Returns:
        Standardized grade (e.g. "A", "B+", "C-") or None if unmappable
    """
    if not source_comp_level or not str(source_comp_level).strip():
        return None

    key = str(source_comp_level).strip().lower()

    # Pass 1: exact match
    exact = COMP_LEVEL_MAP.get(key)
    if exact is not None:
        return exact

    # Pass 2: fallback parser for compound labels
    return _fallback_parse(key)
