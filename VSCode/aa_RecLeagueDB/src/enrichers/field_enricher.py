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
from src.scraper.firecrawl_client import FirecrawlClient

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
        """Enrich all leagues at a URL. Returns one result per league.

        Flow:
          1. Fetch league records for URL
          2. Build union of null fields across all leagues
          3. Short-circuit if nothing to fill
          4. Try extraction from cached snapshot
          5. Firecrawl fallback if no snapshot or extraction returned nothing
          6. Write back hits; record skipped fields
        """
        # Step 1: fetch leagues
        response = (
            self._db.table("leagues_metadata")
            .select("*")
            .eq("url_scraped", url)
            .eq("is_archived", False)
            .execute()
        )
        leagues = response.data or []

        if not leagues:
            logger.warning("No active leagues found for %s", url)
            return []

        # Step 2: null fields per league (union across all leagues)
        all_null_fields: list[str] = []
        league_null_map: dict[str, list[str]] = {}
        for lg in leagues:
            nf = self._get_null_fields(lg)
            league_null_map[lg["league_id"]] = nf
            for f in nf:
                if f not in all_null_fields:
                    all_null_fields.append(f)

        # Step 3: short-circuit if nothing to fill
        if not all_null_fields:
            return [
                FieldEnrichResult(
                    league_id=lg["league_id"],
                    org_name=lg.get("organization_name", ""),
                    skipped_fields=[],
                    source="none",
                )
                for lg in leagues
            ]

        # Step 4: try extraction from cached snapshot
        domain = urlparse(url).netloc
        snapshots = get_snapshots_by_domain(domain)
        snapshot_content = snapshots[0]["content"] if snapshots else None

        patches: list[dict] = []
        source = "none"

        if snapshot_content:
            patches = self._extract(snapshot_content, all_null_fields, leagues)
            if patches:
                source = "cache"

        # Step 5: Firecrawl fallback if no snapshot or empty extraction
        if not patches:
            api_key = os.environ.get("FIRECRAWL_API_KEY", "")
            try:
                fc = FirecrawlClient(api_key=api_key)
                fc_content = fc.scrape(url)
                patches = self._extract(fc_content, all_null_fields, leagues)
                if patches:
                    source = "firecrawl"
            except Exception as exc:
                logger.warning("Firecrawl fallback failed for %s: %s", url, exc)
                return [
                    FieldEnrichResult(
                        league_id=lg["league_id"],
                        org_name=lg.get("organization_name", ""),
                        skipped_fields=league_null_map.get(lg["league_id"], []),
                        source="none",
                        error=str(exc),
                    )
                    for lg in leagues
                ]

        # Step 6: write back and build results
        patch_map: dict[str, dict] = {p.get("league_id", ""): p for p in patches}

        results = []
        for lg in leagues:
            lid = lg["league_id"]
            patch = {k: v for k, v in patch_map.get(lid, {}).items() if k != "league_id"}
            null_fields_for_league = league_null_map.get(lid, [])

            if patch:
                self._write_back(lid, patch)
                filled = [f for f in patch if f in null_fields_for_league]
                skipped = [f for f in null_fields_for_league if f not in patch]
            else:
                filled = []
                skipped = null_fields_for_league

            results.append(FieldEnrichResult(
                league_id=lid,
                org_name=lg.get("organization_name", ""),
                filled_fields=filled,
                skipped_fields=skipped,
                source=source if patch else "none",
            ))

        return results

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_null_fields(self, league: dict) -> list[str]:
        """Return ENRICHABLE_FIELDS that are None on this league record."""
        return [f for f in ENRICHABLE_FIELDS if league.get(f) is None]

    def _build_prompt(self, content: str, null_fields: list[str], leagues: list[dict]) -> str:
        """Build a targeted extraction prompt for only the null fields."""
        # Build league context block
        context_lines = []
        for i, lg in enumerate(leagues, 1):
            known = {
                k: v for k, v in lg.items()
                if k in ("organization_name", "day_of_week", "gender_eligibility",
                         "competition_level", "sport_season_code", "num_teams")
                and v is not None
            }
            context_lines.append(f"  League {i}: {json.dumps(known)}")
        league_context = "\n".join(context_lines) or "  (no context available)"

        # Build output schema — only null fields
        schema_lines = [f'      "{f}": <value or null>' for f in null_fields]
        schema = ",\n".join(schema_lines)

        return f"""You are a data extraction specialist for recreational sports leagues.

TASK: Extract ONLY the fields listed in the OUTPUT SCHEMA from the page content below.
Do not invent or guess values. Return null for any field not clearly stated on the page.

KNOWN LEAGUE CONTEXT (already in database — use to match divisions):
{league_context}

OUTPUT SCHEMA — return a JSON array with one object per league:
[
  {{
    "league_id": "<copy from context above>",
{schema}
  }}
]

Return ONLY valid JSON. No other text.

PAGE CONTENT:
{content}

JSON Output:"""

    def _extract(self, content: str, null_fields: list[str], leagues: list[dict]) -> list[dict]:
        """Call Claude to extract null fields from page content.

        Returns list of patch dicts with only non-null extracted values.
        Returns [] on any parse error.
        """
        prompt = self._build_prompt(content, null_fields, leagues)
        try:
            message = self._anthropic.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()

            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            patches = json.loads(raw)
            if isinstance(patches, dict):
                patches = [patches]

            # Strip null values — don't overwrite existing data with null
            return [
                {k: v for k, v in patch.items() if v is not None}
                for patch in patches
            ]
        except Exception as exc:
            logger.warning("Extraction failed: %s", exc)
            return []

    def _write_back(self, league_id: str, patch: dict) -> None:
        """Write extracted fields back to leagues_metadata.

        Fetches current record, merges patch, recalculates quality_score,
        updates patched fields + quality_score + updated_at.
        """
        from datetime import datetime, timezone

        result = (
            self._db.table("leagues_metadata")
            .select("*")
            .eq("league_id", league_id)
            .execute()
        )
        if not result.data:
            logger.warning("_write_back: league %s not found", league_id)
            return

        current = result.data[0]
        merged = {**current, **patch}
        new_quality = calculate_quality_score(merged)

        update_payload = {
            **patch,
            "quality_score": new_quality,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._db.table("leagues_metadata").update(update_payload).eq("league_id", league_id).execute()
        logger.info("Updated league %s: fields=%s quality=%d", league_id, list(patch.keys()), new_quality)
