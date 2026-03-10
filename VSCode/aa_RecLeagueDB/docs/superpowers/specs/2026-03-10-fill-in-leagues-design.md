# Fill In Leagues — Design Spec

**Date:** 2026-03-10
**Status:** Approved
**Replaces:** `streamlit_app/pages/league_checker.py`

---

## Overview

Replace the "League Checker" Streamlit page with "Fill In Leagues" — a multi-mode enrichment UI that patches missing data on existing `leagues_metadata` records. Three modes cover the main enrichment use cases: deep re-scrape, team count refresh, and targeted field fill.

---

## Modes

| Mode | Label | Backend | Status |
|------|-------|---------|--------|
| Deep-dive | Full re-crawl + reconcile | `scripts/super_scraper.py` | existing |
| Teams | Team count refresh from standings | `scripts/count_teams_scraper.py` | existing |
| Fill Fields | All null enrichable fields | `FieldEnricher` (new) | new |

**One mode per run.** Mode is selected via radio button before URL selection.

---

## Fill Fields Mode — Target Fields

The prompt sent to Claude is dynamically built from whichever of these fields are null on each league record. Fields not null are excluded from the prompt (no overwriting).

**Scheduling:**
- `day_of_week`
- `start_time`
- `num_weeks`
- `time_played_per_week`
- `season_start_date`
- `season_end_date`
- `stat_holidays`

**Venue:**
- `venue_name`

**Pricing:**
- `team_fee`
- `individual_fee`
- `registration_deadline`

**Competition:**
- `competition_level`
- `gender_eligibility`
- `players_per_side`

**Capacity:**
- `slots_left`

**Policies:**
- `has_referee`
- `requires_insurance`
- `insurance_policy_link`

---

## FieldEnricher Flow (per URL)

```
1. Fetch league records for URL from leagues_metadata
   → determine which fields are null per league

2. Fetch most recent snapshot(s) from page_snapshots by domain
   (ordered by created_at DESC, take most recent)

3. If snapshot exists:
   → Build targeted Claude prompt with only null fields
   → Call Claude (claude-sonnet-4-6, JSON output)
   → Parse extraction result

4. If extraction returned usable data:
   → Write back via field-level merge (writer._merge_league_records)
   → Report fields filled + source = "cache"

5. If no snapshot OR extraction returned nothing useful:
   → Firecrawl the URL (FirecrawlClient.scrape)
   → Repeat steps 3–4 with Firecrawl content
   → Report fields filled + source = "firecrawl"

6. Return per-league result: {filled_fields, source, skipped_fields}
```

"Nothing useful" = all target fields still null after extraction.

---

## New Files

### `src/enrichers/field_enricher.py`

```
class FieldEnricher:
    def enrich_url(url: str) -> list[FieldEnrichResult]
        # Orchestrates steps 1–6 above for all leagues at a URL

    def _get_null_fields(league: dict) -> list[str]
        # Returns list of enrichable field names that are None

    def _build_prompt(yaml_or_text: str, null_fields: list[str], leagues: list[dict]) -> str
        # Builds targeted extraction prompt for only the null fields

    def _extract(content: str, null_fields: list[str], leagues: list[dict]) -> list[dict]
        # Calls Claude, parses JSON, returns per-league field patches

    def _write_back(league_id: str, patch: dict) -> None
        # Direct Supabase update of only the patched fields (no full merge needed)
        # Recalculates quality_score after update

@dataclass
class FieldEnrichResult:
    league_id: str
    org_name: str
    filled_fields: list[str]   # fields that got a value
    skipped_fields: list[str]  # fields still null after both passes
    source: str                 # "cache" | "firecrawl" | "none"
    error: str | None
```

### `src/scraper/firecrawl_client.py`

```
class FirecrawlClient:
    def __init__(self, api_key: str)
    def scrape(url: str) -> str
        # POST /v1/scrape → returns markdown text
        # Raises on HTTP error or missing FIRECRAWL_API_KEY
```

Reads `FIRECRAWL_API_KEY` from env. No retry logic in v1 (keep it minimal).

### `streamlit_app/pages/fill_in_leagues.py`

**Layout:**
1. Title: "Fill In Leagues"
2. Mode radio (Deep-dive | Teams | Fill Fields)
3. Mode description (one line per mode)
4. Divider
5. URL list — checkbox per org/URL (same pattern as Venues Enricher)
   - Shows: org name, domain, league count, avg quality score
6. Run button (disabled until ≥1 URL selected)
7. Progress bar + status text while running
8. Results section

**Results per mode:**
- Deep-dive: same summary cards as current league_checker.py (leagues written, archived, etc.)
- Teams: same as current MATCH/CHANGED/NOT_FOUND display
- Fill Fields: per-URL expander → per-league row showing filled fields + source badge (Cache / Firecrawl / None)

---

## Files Changed

| File | Change |
|------|--------|
| `streamlit_app/pages/fill_in_leagues.py` | New — main page |
| `src/enrichers/field_enricher.py` | New — Fill Fields backend |
| `src/scraper/firecrawl_client.py` | New — Firecrawl API wrapper |
| `streamlit_app/app.py` | Update nav: replace "League Checker" with "Fill In Leagues" |
| `streamlit_app/pages/league_checker.py` | Delete |

---

## Out of Scope

- `num_teams` is excluded from Fill Fields (handled by Teams mode)
- `organization_id`, `url_id`, `venue_id` FK resolution — handled by separate enrichers
- Firecrawl retry logic — deferred to v2
- Caching Firecrawl responses as new snapshots — deferred to v2
