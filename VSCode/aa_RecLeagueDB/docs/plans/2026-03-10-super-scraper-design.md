# Super Scraper + Merge Tools — Design Doc

**Date:** 2026-03-10
**Status:** Approved

---

## Problem

The standard scraper (`smart_scraper.py`) produces thin records (quality_score < 75) when it
misses division pages, schedule tabs, or standings sections. The existing League Checker only
verifies team counts and cannot fix those thin records. There is also no workflow for cleaning up
duplicates created within the same source URL.

---

## Quality Score Bands

| Band | Range | Constant | Scraper Behavior |
|------|-------|----------|-----------------|
| Thin | 0–59 | `AUTO_REPLACE_THRESHOLD = 60` | Super scrape auto-archives old + writes new if contradicted |
| Borderline | 60–74 | `DEEP_SCRAPE_THRESHOLD = 75` | Super scrape triggered; contradictions go to review queue |
| Acceptable | 75–89 | — | Standard checker: team count verify only |
| Substantial | 90+ | — | Standard checker: team count verify only |

Constants defined once in `src/config/quality_thresholds.py`, imported everywhere.

---

## Super Scraper — Two-Pass Design

### Trigger
League Checker automatically triggers super scrape when a URL has any record with
`quality_score < DEEP_SCRAPE_THRESHOLD (75)`.

### Pass 1 — Deep YAML Crawl
Reuses `src/scraper/smart_crawler.crawl()` with aggressive settings:
- `max_index_depth=4` (vs standard 2)
- Primary link score threshold: 60 (vs standard 100)
- `force_refresh=True` (bypass 7-day cache)

Feeds into existing `src/extractors/yaml_extractor.extract_league_data_from_yaml()`.

### Pass 2 — Standings/Schedule HTML Pass
Reuses existing `src/checkers/playwright_navigator.PlaywrightNavigator` unchanged.
Keywords already cover: standings, schedule, teams, divisions.
Feeds into existing `src/checkers/team_count_extractor.TeamCountExtractor`.

### Reconciliation
For each Pass 1 league, cross-reference Pass 2 team counts + existing DB record:

```
No contradiction        → field-level merge, recalculate quality_score
Contradiction + THIN    → archive old, write new automatically
Contradiction + BORDERLINE → write to super_scrape_review queue, leave existing untouched
```

"Contradiction" = new num_teams differs by > 1 from existing, or new day_of_week/venue
differs from existing non-null value.

### Auto-Consolidation (within-URL, post-write)
After writing, group the URL's active records by the 6-field identity model
(`organization_name`, `sport_season_code`, `season_year`, `venue_name`, `day_of_week`,
`competition_level`). Auto-archive obvious duplicates (all 6 match OR 5/6 match with one null),
keeping the highest `quality_score`. Ambiguous cases (4/6 match) surfaced in URL Merge.

---

## Merge Tools Redesign

### URL Merge (rename current `merge_tool.py`)
Scoped to a single `url_scraped`. User selects URL from dropdown, sees all active records
grouped by similarity. Useful for reviewing what auto-consolidation left behind.
Same side-by-side merge/archive UI.

### League Merge (new page)
Cross-URL general deduplication using the full 6-field identity model. Surfaces records
matching across different source URLs. Same side-by-side UI pattern as URL Merge.

Both tools share the existing `_merge()` + `archive_league()` backend.

---

## Files Touched

| File | Change |
|------|--------|
| `src/config/quality_thresholds.py` | NEW — band constants |
| `src/scraper/deep_crawler.py` | NEW — aggressive crawl() wrapper |
| `src/scraper/reconciler.py` | NEW — contradiction logic + review queue write |
| `src/database/consolidator.py` | NEW — within-URL auto-dedup |
| `scripts/super_scraper.py` | NEW — full two-pass pipeline |
| `src/checkers/league_checker.py` | MODIFY — branch on quality_score |
| `src/database/leagues_reader.py` | MODIFY — add `get_duplicate_groups_for_url()` |
| `streamlit_app/pages/merge_tool.py` | MODIFY → rename to `url_merge.py`, scope to URL |
| `streamlit_app/pages/league_merge.py` | NEW — cross-URL merge page |
| `streamlit_app/app.py` | MODIFY — update nav |
| `docs/DATABASE_SCHEMA.md` | MODIFY — add quality bands section |
| `CLAUDE.md` | MODIFY — update pages list, scraper cascade |

---

## Governance Updates

`DATABASE_SCHEMA.md` gets a **Quality Score Bands** section with the four named bands and
their constants. `CLAUDE.md` pages list updated for URL Merge + League Merge.
`CLAUDE_EXTRACT.md` documents the super scraper cascade (L0 MCP → L1 standard → L1.5 super → L2 Firecrawl).
