# Spec A: Extraction & Enrichment Improvements

**Date:** 2026-03-12
**Priority:** Primary
**Goal:** Dramatically improve field coverage by making the crawler find more relevant pages, extracting deeper from league pages, and making enrichment genuinely additive.

---

## Problem Statement

The pipeline asks for the right fields but doesn't get them because:

1. **Crawler coverage (B):** Depth 2 / 20-link cap / score >= 100 threshold means schedule, registration, standings, and rules pages are often missed.
2. **Extraction depth (A):** YAML accessibility trees compress away the inline text that contains actual values (start times, game duration, fees, number of weeks). The data is on the page but not in the LLM input.
3. **Enrichment gaps (C):** Fill In Leagues re-reads the same cached snapshot that was already insufficient. It needs to discover new pages, not re-parse old ones.
4. **League Merge false positives:** A downstream symptom -- sparse records with missing distinguishing fields look like duplicates.

---

## Design

### Phase 0: Unify Crawl Paths

**Problem:** The project has two independent crawl flows:
- `scripts/extract_leagues_yaml.py` uses `playwright_yaml_fetcher.fetch_yaml_multi_page()` — depth 1, max 5 pages, min score 50. This is the **primary user-facing pipeline** run from Queue Monitor / Scraper UI.
- `scripts/smart_scraper.py` uses `smart_crawler.crawl()` — depth 2, max 20 links, page classification. More sophisticated but not used by the main pipeline.

**Fix:** Migrate `extract_leagues_yaml.py` to use `smart_crawler.crawl()` as its crawl backend instead of `fetch_yaml_multi_page()`. This ensures all Phase 1 improvements (category tagging, adaptive depth, raised link cap) apply to the primary pipeline.

`fetch_yaml_multi_page()` remains available as a utility for simple single-depth fetches (e.g., enrichment mini-crawls), but is no longer the main crawl entry point.

**Files:** `scripts/extract_leagues_yaml.py`, `src/scraper/smart_crawler.py`

---

### Phase 1: Smarter Initial Crawl

**File:** `src/scraper/smart_crawler.py`, `src/scraper/yaml_link_parser.py`

#### 1a. Field-Category Link Tagging

Replace the flat link score with category-tagged scoring. Each link gets scored AND tagged with which field categories it likely serves:

| Link text patterns | Field category | Target fields |
|----|----|----|
| schedule, standings, results, teams, matchups, scores | `SCHEDULE` | num_teams, day_of_week, start_time |
| register, signup, fees, pricing, cost, payment | `REGISTRATION` | team_fee, individual_fee, registration_deadline |
| rules, policies, insurance, waiver, referee | `POLICY` | has_referee, requires_insurance, insurance_policy_link |
| venue, location, facility, field, gym, arena | `VENUE` | venue_name |
| season, league, division, program, about | `DETAIL` | season_start_date, season_end_date, num_weeks, competition_level |

Links still get numeric scores for prioritization, but the category tag enables adaptive depth (1c) and gap-aware enrichment (Phase 4).

**Note:** `yaml_link_parser.py` already has `infer_page_type()` (returns "registration", "schedule", "standings", "rules", "teams", "league_list"). Build on this existing infrastructure rather than creating a parallel system -- extend `infer_page_type()` to return field categories alongside the existing page types. Keywords like "join", "enroll", "upcoming", "current", "calendar" that exist in the current scorer but don't map to a category should be assigned to `DETAIL` (general league info).

#### 1b. Raise Detail Link Cap

Change `MAX_DETAIL_LINKS` from 20 to 30 in `smart_crawler.py`. Many league sites have 10+ divisions and 20 truncates the tail.

#### 1c. Adaptive Depth for Missing Categories

After completing depth 2 crawl, compute which field categories have zero page coverage (no pages collected that were tagged to that category). For each uncovered category, allow depth 3 for links tagged to that category only.

This is NOT a global depth increase -- it's a targeted extension. If fees pages are at depth 3 behind a "Registration" index page, the crawler will now find them.

#### 1d. Track Pages-Per-Category

Return a `category_coverage` dict from the crawler alongside the collected pages:
```python
{
    "SCHEDULE": ["https://example.com/standings"],
    "REGISTRATION": [],  # gap -- no registration pages found
    "POLICY": [],
    "VENUE": ["https://example.com/location"],
    "DETAIL": ["https://example.com/league/monday-coed"]
}
```

This feeds Phase 3 (gap report) and Phase 4 (targeted enrichment).

---

### Phase 2: Two-Tier Extraction (Deep Extract)

**Files:** `src/scraper/playwright_yaml_fetcher.py`, `src/extractors/yaml_extractor.py`

#### 2a. Capture Full Rendered Text

When Playwright fetches a page, also capture `page.inner_text()` (full visible text). Store it alongside the YAML tree in the page result. This is essentially free -- Playwright already rendered the page.

Return structure becomes:
```python
{
    "url": "...",
    "yaml_tree": "...",
    "full_text": "...",  # NEW
    "page_type": "LEAGUE_DETAIL"
}
```

#### 2b. Tier 1 / Tier 2 Extraction Split

- **Tier 1 (all pages):** YAML-only extraction for classification and structural data. Current behavior, unchanged. Used for LEAGUE_INDEX and OTHER pages.
- **Tier 2 (LEAGUE_DETAIL and SCHEDULE pages only):** Send BOTH the YAML tree AND the full rendered text to Claude Sonnet. Updated prompt:

```
You are extracting structured league data. You have two inputs:

1. YAML ACCESSIBILITY TREE - shows page structure, headings, links, form elements
2. FULL PAGE TEXT - contains the actual text content visible to users

Use the YAML tree to understand page layout and navigation.
Extract ALL field values from the full page text. Look carefully for:
- Specific times ("7:00 PM", "games start at 8pm")
- Durations ("10-week season", "60-minute games", "12 games")
- Dates ("Season runs Jan 6 - Mar 24", "Registration closes Dec 15")
- Fees ("$150/player", "$1200/team")
- Venue details ("Games played at Greenwood Arena")
- Format details ("6v6", "refereed games", "insurance required")

These values are often in paragraph text, list items, or table cells.
Do NOT return null if the information appears anywhere in the text.

[existing output schema with all 23 fields including insurance_policy_link]
```

#### 2c. Token Budget Control

Only Tier 2 pages (LEAGUE_DETAIL/SCHEDULE) get full text. Typical breakdown per URL:
- 2-8 detail/schedule pages: Tier 2 (YAML + full text, ~8-15K tokens each — YAML is 1-5K, `inner_text()` can add 5-15K for content-heavy pages)
- 5-20 index/other pages: Tier 1 (YAML only, ~1-2K tokens each)

Add a `max_full_text_chars` parameter (default 15,000) to truncate very large pages. Budget ~15K tokens per Tier 2 page worst case.

---

### Phase 3: Post-Extraction Gap Report

**File:** `src/extractors/yaml_extractor.py` (or new `src/extractors/gap_reporter.py`)

After extraction completes for a URL, compute a field coverage report:

```python
def compute_field_coverage(leagues: list[dict]) -> dict:
    """Which of the 23 league data fields are populated across all extracted leagues."""
    all_fields = [... 23 fields ...]
    covered = set()
    for league in leagues:
        for field in all_fields:
            if league.get(field) is not None:
                covered.add(field)
    missing = set(all_fields) - covered
    return {
        "covered": sorted(covered),
        "missing": sorted(missing),
        "coverage_pct": len(covered) / len(all_fields) * 100,
        "missing_categories": map_fields_to_categories(missing)  # uses Phase 1 category mapping
    }
```

Store in `page_snapshots.metadata` as a `gap_report` key (the enricher already reads from `page_snapshots` via `get_snapshots_by_domain()`, so this is the natural location). This tells Fill In Leagues exactly what to target.

---

### Phase 4: Targeted Enrichment (Field Enricher Upgrade)

**File:** `src/enrichers/field_enricher.py`

#### 4a. Page Discovery Mode

When enriching, instead of only re-reading the cached snapshot:

1. Look at which fields are null across leagues for this URL
2. Map null fields to page-type categories (using Phase 1 mapping)
3. Do a **targeted mini-crawl** of the domain:
   - Use `yaml_link_parser.score_links()` with lowered threshold (score >= 60) filtered to relevant categories
   - Fetch only 1-3 pages per missing category
   - Use Tier 2 extraction (full text) on discovered pages
4. Merge newly extracted field values into existing records

#### 4b. Enrichment Cascade

The enrichment order becomes:
1. **Cached snapshot re-extraction** (free, fast) -- current behavior
2. **Targeted mini-crawl** (cheap, ~2-5 Playwright fetches + 1-3 Claude calls) -- NEW
3. **Firecrawl** (paid, last resort) -- current behavior, unchanged

#### 4c. Enrichment Tracking

Track which enrichment tier succeeded per field for diagnostics:
```python
{
    "team_fee": {"source": "mini_crawl", "page": "https://example.com/register"},
    "venue_name": {"source": "cached_snapshot"},
    "num_teams": {"source": "teams_mode"}  # separate
}
```

---

### Phase 5: Minor Fixes

#### 5a. Add `insurance_policy_link` to YAML Extractor

Add to the output schema in `yaml_extractor.py` prompt:
```
"insurance_policy_link": "string (URL to insurance/waiver policy page) or null"
```

#### 5b. Quality Score Tuning

In `src/database/validators.py`:
- Add `num_weeks`, `players_per_side`, and `registration_deadline` to `important_fields` list
- These use the existing flat -5 penalty per missing field (same as other important_fields)
- All three help distinguish leagues and reduce merge false positives

---

## Baseline Measurement

Before starting implementation, run these queries to establish baselines:
```sql
-- Average identifying_fields_pct
SELECT AVG(identifying_fields_pct) FROM leagues_metadata WHERE is_archived = false;

-- Average quality_score
SELECT AVG(quality_score) FROM leagues_metadata WHERE is_archived = false;

-- Field-level null rates
SELECT
  COUNT(*) as total,
  COUNT(*) FILTER (WHERE day_of_week IS NULL) as missing_day,
  COUNT(*) FILTER (WHERE start_time IS NULL) as missing_time,
  COUNT(*) FILTER (WHERE venue_name IS NULL) as missing_venue,
  COUNT(*) FILTER (WHERE team_fee IS NULL AND individual_fee IS NULL) as missing_fees,
  COUNT(*) FILTER (WHERE num_weeks IS NULL) as missing_weeks,
  COUNT(*) FILTER (WHERE season_start_date IS NULL) as missing_start,
  COUNT(*) FILTER (WHERE num_teams IS NULL) as missing_teams
FROM leagues_metadata WHERE is_archived = false;
```

Record these values before any changes.

---

## Data Flow (After)

```
1. Crawl URL (smart_crawler — now used by extract_leagues_yaml.py)
   - Classify pages (Tier 1, YAML, Haiku)
   - Tag links by field category
   - Adaptive depth 3 for uncovered categories
   - Return pages + category_coverage

2. Extract (yaml_extractor)
   - Tier 1: YAML-only for INDEX/OTHER pages
   - Tier 2: YAML + full text for DETAIL/SCHEDULE pages
   - Compute gap report (covered/missing fields)

3. Store (writer)
   - Insert/update with quality scoring
   - Store gap report alongside scrape result

4. Enrich (field_enricher, when invoked)
   - Read gap report
   - Try cached snapshot re-extraction
   - Try targeted mini-crawl for missing categories
   - Try Firecrawl as last resort
   - Patch null fields

5. Verify (teams mode, when invoked)
   - Playwright navigation for num_teams
```

---

## Success Criteria

- Average `identifying_fields_pct` increases from current baseline to 75%+
- Average `quality_score` increases by 10+ points
- League Merge false positive rate drops (more distinguishing fields populated)
- Fill In Leagues success rate improves (targeted mini-crawl finds data that snapshots missed)

---

## Files Modified

| File | Change |
|------|--------|
| `scripts/extract_leagues_yaml.py` | Switch from `fetch_yaml_multi_page()` to `smart_crawler.crawl()`, wire up gap report |
| `src/scraper/yaml_link_parser.py` | Field-category tagging via extended `infer_page_type()` |
| `src/scraper/smart_crawler.py` | Adaptive depth, raised link cap, category_coverage tracking, return full_text |
| `src/scraper/playwright_yaml_fetcher.py` | Capture `page.inner_text()` alongside YAML in `fetch_page_as_yaml()` |
| `src/extractors/yaml_extractor.py` | Two-tier extraction, add insurance_policy_link, updated prompt |
| `src/extractors/gap_reporter.py` | NEW: field coverage computation |
| `src/enrichers/field_enricher.py` | Page discovery mode, enrichment cascade, tracking |
| `src/database/validators.py` | Quality score weight additions (num_weeks, players_per_side, registration_deadline) |
| `src/database/snapshot_store.py` | Store gap_report in page_snapshots.metadata |
