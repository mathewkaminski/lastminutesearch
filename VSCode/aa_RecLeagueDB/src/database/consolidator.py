"""Within-URL duplicate detection and auto-consolidation."""
from __future__ import annotations
from dataclasses import dataclass

_IDENTITY_FIELDS = (
    "organization_name",
    "sport_season_code",
    "season_year",
    "venue_name",
    "day_of_week",
    "source_comp_level",
)


@dataclass
class ConsolidationGroup:
    keep_id: str
    archive_id: str
    confidence: str   # "AUTO" (auto-archive) or "REVIEW" (surface in UI)
    matched_fields: int


def _count_matching_fields(a: dict, b: dict) -> int:
    """Count how many identity fields match, treating null as wildcard."""
    count = 0
    for f in _IDENTITY_FIELDS:
        av, bv = a.get(f), b.get(f)
        if av is None or bv is None:
            count += 1  # null = compatible
        elif str(av).lower() == str(bv).lower():
            count += 1
    return count


def find_within_url_duplicates(rows: list[dict]) -> list[ConsolidationGroup]:
    """Find duplicate pairs within a list of league records from the same URL.

    Args:
        rows: League records, all from the same url_scraped.

    Returns:
        List of ConsolidationGroup — one per duplicate pair found.
        confidence="AUTO"   → 5 or 6 fields match (safe to auto-archive lower quality)
        confidence="REVIEW" → 4 fields match (surface in URL Merge UI)
    """
    groups: list[ConsolidationGroup] = []
    used: set[str] = set()

    # Sort descending by quality so we always keep the better record
    sorted_rows = sorted(rows, key=lambda r: r.get("quality_score") or 0, reverse=True)

    for i, a in enumerate(sorted_rows):
        if a["league_id"] in used:
            continue
        for b in sorted_rows[i + 1:]:
            if b["league_id"] in used:
                continue
            matched = _count_matching_fields(a, b)
            if matched >= 5:
                confidence = "AUTO"
            elif matched == 4:
                confidence = "REVIEW"
            else:
                continue

            groups.append(ConsolidationGroup(
                keep_id=a["league_id"],
                archive_id=b["league_id"],
                confidence=confidence,
                matched_fields=matched,
            ))
            used.add(b["league_id"])
            break  # each record can only be in one pair

    return groups
