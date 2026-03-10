"""Reconciliation logic: compare new extraction vs existing DB record."""
from __future__ import annotations
from enum import Enum
from src.config.quality_thresholds import AUTO_REPLACE_THRESHOLD, DEEP_SCRAPE_THRESHOLD


class ReconcileAction(str, Enum):
    MERGE   = "MERGE"    # No contradiction, or existing is high quality — merge normally
    REPLACE = "REPLACE"  # Contradiction + existing is THIN — auto-archive and write new
    REVIEW  = "REVIEW"   # Contradiction + existing is BORDERLINE — queue for manual review


def _contradictions(extracted: dict, existing: dict) -> list[str]:
    """Return list of field names that contradict between extracted and existing."""
    issues = []

    # num_teams: contradiction if difference > 1
    new_t = extracted.get("num_teams")
    old_t = existing.get("num_teams")
    if new_t is not None and old_t is not None and abs(new_t - old_t) > 1:
        issues.append("num_teams")

    # day_of_week / venue_name: contradiction if both non-null and differ
    for field in ("day_of_week", "venue_name"):
        new_v = extracted.get(field)
        old_v = existing.get(field)
        if new_v and old_v and new_v.lower() != old_v.lower():
            issues.append(field)

    return issues


def reconcile(
    extracted: dict,
    existing: dict,
) -> tuple[ReconcileAction, str]:
    """Decide what to do with a new extraction vs an existing DB record.

    Returns:
        (ReconcileAction, reason_string)
    """
    contradictions = _contradictions(extracted, existing)

    if not contradictions:
        return ReconcileAction.MERGE, "no contradiction"

    reason = f"contradictions: {', '.join(contradictions)}"
    existing_score = existing.get("quality_score") or 0

    if existing_score < AUTO_REPLACE_THRESHOLD:
        return ReconcileAction.REPLACE, reason
    if existing_score < DEEP_SCRAPE_THRESHOLD:
        return ReconcileAction.REVIEW, reason

    # Acceptable or Substantial — never auto-replace
    return ReconcileAction.MERGE, f"existing quality sufficient ({existing_score}) — {reason}"
