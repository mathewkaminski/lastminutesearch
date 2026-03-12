# Spec B: Code Cleanup & Streamlit Reorganization

**Date:** 2026-03-12
**Priority:** Secondary (after Spec A)
**Goal:** Remove dead code from the legacy HTML extraction path, reorganize Streamlit tabs, and upgrade Leagues Viewer.

---

## Problem Statement

1. Legacy HTML extraction path (GPT-4o) is dead code -- the YAML path replaced it. Several files are unused.
2. Streamlit has 10+ tabs, some retired or rarely used. Navigation is confusing.
3. Leagues Viewer is read-only and doesn't group by URL.
4. URL Merge page is no longer needed.

---

## Design

### Part 1: Code Cleanup (Remove Legacy HTML Path)

**Delete these files:**

| File | Reason |
|------|--------|
| `src/extractors/league_extractor.py` | GPT-4o HTML extraction, replaced by yaml_extractor.py |
| `src/scraper/html_aggregator.py` | HTML multi-page aggregation, replaced by YAML fetcher |
| `src/scraper/page_classifier.py` | Old page classifier, replaced by page_type_classifier.py |
| `src/scraper/link_discoverer.py` | Old link extraction, replaced by yaml_link_parser.py |
| `streamlit_app/pages/url_merge.py` | User request: no longer needed |
| `src/extractors/html_preprocessor.py` | Only imported by league_extractor.py (being deleted); no other consumers |

**Note:** `streamlit_app/pages/league_checker.py` was already removed in commit `724d5f4`. Do not attempt to delete.

**Keep (enrichment & fallback):**
- `src/enrichers/*` -- all enrichment tools
- `src/checkers/*` -- team count verification (used by Fill In Leagues Teams mode)
- `src/scraper/firecrawl_client.py` -- L2 fallback
- `src/scraper/deep_crawler.py` -- used by super_scraper

**Cleanup imports (known breakage from deletions):**

These files import from deleted modules and MUST be updated:

| File | Broken import | Fix |
|------|--------------|-----|
| `src/scraper/multi_page_navigator.py` | imports `page_classifier`, `link_discoverer`, `html_aggregator` | Review if this file is still used. If dead code (replaced by smart_crawler), delete it too. If used, refactor to use `page_type_classifier` and `yaml_link_parser`. |
| `src/database/vector_store.py` | imports `_clean_html` from `league_extractor` | Inline or extract the `_clean_html` utility function into a shared utils module |
| `scripts/extract_pipeline.py` | imports `extract_league_data` from `league_extractor` | This is the old HTML pipeline entry point. Delete if fully replaced by `extract_leagues_yaml.py` |
| `tests/test_extraction.py` | imports from `league_extractor` | Delete (tests for deleted code) |
| `tests/test_link_discoverer.py` | imports from `link_discoverer` | Delete (tests for deleted code) |

Also grep for any other references and fix.

**Test:** Run the Streamlit app, verify all remaining pages load. Run the extraction pipeline on a test URL to confirm YAML path still works end-to-end.

---

### Part 2: Streamlit Reorganization

**Current navigation (app.py):** Flat list of 10+ pages.

**New navigation structure:**

```
--- Core Workflow ---
Campaign Manager        # Search for league URLs
Queue Monitor           # Manage scrape queue
Scraper UI              # Run batch extraction
Fill In Leagues         # Enrich incomplete records
Leagues Viewer          # Browse & edit league data
League Merge            # Cross-URL deduplication
Venues Enricher         # Resolve venue names

--- Diagnostics ---
Data Quality            # Quality score dashboard
Org View                # Browse by domain
```

**Implementation:**
- Streamlit supports `st.sidebar` sections. Use `st.sidebar.header()` or `st.sidebar.divider()` to create visual separation between Core Workflow and Diagnostics.
- Remove URL Merge and League Checker from navigation entirely.
- Order pages by workflow sequence (search → queue → scrape → enrich → view → merge → venues).

---

### Part 3: Leagues Viewer Upgrade

**File:** `streamlit_app/pages/leagues_viewer.py`

#### 3a. Inline Database Writes

Add editable columns to the data table. When a user edits a cell:
1. Validate the new value (type check, range check for scores/fees)
2. Call Supabase client directly: `supabase.table("leagues_metadata").update({field: new_value}).eq("league_id", league_id).execute()` (or add an `update_league()` function to `writer.py` if it doesn't exist)
3. Show success/error toast

**Editable fields:** All 23 league data fields. Metadata fields (quality_score, completeness_status, etc.) remain read-only as they're computed.

**Implementation:** Use `st.data_editor()` with `disabled` parameter for read-only columns. On change, diff the edited dataframe against the original to find modified cells.

#### 3b. Group-by-URL Toggle

Add a toggle/checkbox: "Group by URL"

When enabled:
- Query `leagues_metadata` ordered by `url_scraped`
- Display with `st.expander()` per unique URL, showing the URL as header and all leagues under it as a sub-table
- Or use Streamlit's native row grouping if `st.dataframe` supports it via column config

When disabled:
- Current flat table view (default)

---

## Files Modified

| File | Change |
|------|--------|
| `src/extractors/league_extractor.py` | DELETE |
| `src/extractors/html_preprocessor.py` | DELETE |
| `src/scraper/html_aggregator.py` | DELETE |
| `src/scraper/page_classifier.py` | DELETE |
| `src/scraper/link_discoverer.py` | DELETE |
| `src/scraper/multi_page_navigator.py` | DELETE if dead code; refactor if still used |
| `streamlit_app/pages/url_merge.py` | DELETE |
| `scripts/extract_pipeline.py` | DELETE (old HTML pipeline entry point) |
| `tests/test_extraction.py` | DELETE (tests deleted code) |
| `tests/test_link_discoverer.py` | DELETE (tests deleted code) |
| `src/database/vector_store.py` | Extract `_clean_html` to utils, remove league_extractor import |
| `streamlit_app/app.py` | Reorganize navigation, add sections, remove deleted page references |
| `streamlit_app/pages/leagues_viewer.py` | Inline edits, group-by-URL |

---

## Success Criteria

- All deleted files removed, no broken imports
- Streamlit app launches cleanly with reorganized navigation
- Leagues Viewer supports inline edits that persist to database
- Leagues Viewer groups by URL when toggle is enabled
- Extraction pipeline (scripts/extract_leagues_yaml.py) runs successfully on a test URL
- Fill In Leagues (all 3 modes) still works
