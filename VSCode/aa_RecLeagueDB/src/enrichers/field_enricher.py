"""FieldEnricher — patches null fields on leagues_metadata records.

Flow per URL:
  1. Fetch leagues for URL → identify null enrichable fields
  2. Pull latest page snapshot from page_snapshots by domain
  3. If snapshot: run targeted Claude extraction → write back hits
  4. If no snapshot or nothing extracted: Firecrawl URL → repeat step 3
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

import anthropic

from src.database.supabase_client import get_client
from src.database.snapshot_store import get_snapshots_by_domain
from src.database.validators import calculate_quality_score

logger = logging.getLogger(__name__)

# All fields that can be extracted from web content.
# num_teams is excluded — handled by Teams mode.
ENRICHABLE_FIELDS: list[str] = [
    "day_of_week", "start_time", "num_weeks", "time_played_per_week",
    "season_start_date", "season_end_date", "stat_holidays",
    "venue_name",
    "team_fee", "individual_fee", "registration_deadline",
    "competition_level", "gender_eligibility", "players_per_side",
    "slots_left",
    "has_referee", "requires_insurance", "insurance_policy_link",
]


@dataclass
class FieldEnrichResult:
    league_id: str
    org_name: str
    filled_fields: list[str] = field(default_factory=list)
    skipped_fields: list[str] = field(default_factory=list)
    source: str = "none"          # "cache" | "firecrawl" | "none"
    error: str | None = None


class FieldEnricher:
    """Enriches null fields on leagues_metadata using cached snapshots and Firecrawl."""

    def __init__(
        self,
        supabase_client=None,
        anthropic_api_key: str | None = None,
    ) -> None:
        self._db = supabase_client or get_client()
        self._anthropic = anthropic.Anthropic(
            api_key=anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )

    # ── public ────────────────────────────────────────────────────────────────

    def enrich_url(self, url: str) -> list[FieldEnrichResult]:
        """Enrich all leagues at a URL. Returns one result per league."""
        raise NotImplementedError("implemented in Task 5")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_null_fields(self, league: dict) -> list[str]:
        """Return ENRICHABLE_FIELDS that are None on this league record."""
        return [f for f in ENRICHABLE_FIELDS if league.get(f) is None]

    def _build_prompt(self, content: str, null_fields: list[str], leagues: list[dict]) -> str:
        raise NotImplementedError("implemented in Task 3")

    def _extract(self, content: str, null_fields: list[str], leagues: list[dict]) -> list[dict]:
        raise NotImplementedError("implemented in Task 4")

    def _write_back(self, league_id: str, patch: dict) -> None:
        raise NotImplementedError("implemented in Task 4")
