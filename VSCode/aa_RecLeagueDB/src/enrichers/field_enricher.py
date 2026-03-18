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

import yaml as _yaml

import anthropic

from src.database.supabase_client import get_client
from src.database.snapshot_store import get_snapshots_by_domain
from src.database.validators import calculate_quality_score
from src.scraper.firecrawl_client import FirecrawlClient
from src.extractors.gap_reporter import map_fields_to_categories
from src.scraper.yaml_link_parser import extract_navigation_links, infer_link_category
from src.scraper.playwright_yaml_fetcher import fetch_page_as_yaml
from src.extractors.yaml_extractor import extract_league_data_from_yaml

logger = logging.getLogger(__name__)

# All fields that can be extracted from web content.
# num_teams is excluded — handled by Teams mode.
ENRICHABLE_FIELDS: list[str] = [
    "day_of_week", "start_time", "num_weeks", "time_played_per_week",
    "season_start_date", "season_end_date", "stat_holidays",
    "venue_name",
    "team_fee", "individual_fee", "registration_deadline",
    "source_comp_level", "gender_eligibility", "players_per_side",
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
        from src.utils.domain_extractor import extract_base_domain
        domain = extract_base_domain(url)
        snapshots = get_snapshots_by_domain(domain)
        snapshot_content = snapshots[0]["content"] if snapshots else None

        patches: list[dict] = []
        source = "none"

        if snapshot_content:
            patches = self._extract(snapshot_content, all_null_fields, leagues)
            if patches:
                source = "cache"

        # Stage 2: mini-crawl for fields still missing after snapshot
        snapshot_field_names = {
            k for p in patches for k in p.keys() if k != "league_id"
        }
        still_missing = [f for f in all_null_fields if f not in snapshot_field_names]
        mini_patches: dict = {}
        if still_missing:
            mini_patches = self._mini_crawl_for_fields(url, still_missing)

        still_missing_after_mini = [f for f in still_missing if f not in mini_patches]

        # Step 5: Firecrawl fallback if no snapshot or empty extraction and fields still missing
        if not patches and still_missing_after_mini:
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

        # Merge mini-crawl patches into patch_map
        for lg in leagues:
            lid = lg["league_id"]
            lg_null = [f for f in still_missing if lg.get(f) is None]
            mini_for_league = {f: v for f, v in mini_patches.items() if f in lg_null}
            if mini_for_league:
                if lid in patch_map:
                    patch_map[lid].update(mini_for_league)
                else:
                    patch_map[lid] = mini_for_league

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
                if k in ("league_id", "organization_name", "day_of_week", "gender_eligibility",
                         "source_comp_level", "sport_season_code", "num_teams")
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
                model="claude-haiku-4-5-20251001",
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

    def _mini_crawl_for_fields(
        self, url: str, missing_fields: list[str], max_pages_per_category: int = 2
    ) -> dict:
        """Targeted mini-crawl for specific missing fields.

        Fetches home page, scores links with lowered threshold (60), follows links
        tagged to categories matching missing fields. Uses Tier-2 extraction
        (YAML + full_text) on discovered pages.

        Args:
            url: Base URL to crawl from
            missing_fields: Fields still null after snapshot extraction
            max_pages_per_category: Max pages to fetch per missing category (default 2)

        Returns:
            Dict of {field_name: value} for any fields found
        """
        missing_categories = set(map_fields_to_categories(missing_fields).keys())
        if not missing_categories:
            return {}

        try:
            home_yaml, home_meta = fetch_page_as_yaml(url, use_cache=True)
        except Exception:
            return {}

        if not home_yaml:
            return {}

        try:
            home_tree = _yaml.safe_load(home_yaml)
            links = extract_navigation_links(home_tree, url, min_score=60)
        except Exception:
            return {}

        # Set field_category on links that lack it
        for link in links:
            if link.field_category is None:
                link.field_category = infer_link_category(link.anchor_text, link.page_type)

        category_links: dict[str, list] = {}
        for link in links:
            cat = link.field_category
            if cat and cat in missing_categories:
                category_links.setdefault(cat, []).append(link)

        found: dict = {}
        visited: set = {url}
        for cat, cat_links in category_links.items():
            for link in cat_links[:max_pages_per_category]:
                if link.url in visited:
                    continue
                visited.add(link.url)
                try:
                    page_yaml, page_meta = fetch_page_as_yaml(link.url, use_cache=True)
                    if not page_yaml:
                        continue
                    full_text = (page_meta or {}).get("full_text", "")
                    leagues = extract_league_data_from_yaml(
                        page_yaml, url=link.url, full_text=full_text
                    )
                    for league in leagues:
                        for f in missing_fields:
                            if f not in found and league.get(f) is not None:
                                found[f] = league[f]
                except Exception:
                    continue

        return found

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
