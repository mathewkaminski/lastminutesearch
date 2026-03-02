# Leagues-Only Management Views — Design Doc

**Date:** 2026-03-02
**Status:** Approved for implementation

---

## Goal

Build out the three stubbed Data Management pages (Leagues Viewer, Data Quality, Merge Tool) filtered exclusively to `listing_type = 'league'` records. Drop-ins and unknowns are excluded from these views — they belong in Org View for classification only.

---

## Context

`leagues_metadata` now has `listing_type IN ('league', 'drop_in', 'unknown')`. The Org View handles classification of all records. The three manage pages below are the operational layer for clean league data: browse, audit quality, and deduplicate.

All three pages share one foundational rule: **`WHERE listing_type = 'league' AND is_archived = FALSE`**.

---

## Pages to Build

### 1. Leagues Viewer (`leagues_viewer.py`)

**Purpose:** Paginated, filterable browse of all league records with inline detail expand and row-level actions.

**Filters (sidebar or top bar):**
- Sport/Season code (multi-select from distinct values in DB)
- Organization name (text search)
- Day of week (multi-select)
- Gender eligibility (multi-select)
- Quality score range (slider, 0–100)
- Season year (select)

**Table columns:** org name, sport code, day, start time, venue, team fee, individual fee, quality score, updated_at

**Row expand:** shows all fields for that record

**Row actions:**
- Archive (sets `is_archived = TRUE`)
- Add to re-scrape queue (inserts into `scrape_queue`)

**Bottom:** Export filtered results to CSV

---

### 2. Data Quality Dashboard (`data_quality.py`)

**Purpose:** Identify systemic gaps and surface individual records needing attention — leagues only.

**Summary metrics (top):** total leagues, avg quality score, % ≥ 70, % needing re-scrape (< 50)

**Field coverage bars:** % of leagues with each important field populated:
- day_of_week, start_time, venue_name, team_fee, individual_fee, season_start_date, season_end_date, competition_level, gender_eligibility, num_weeks

**Breakdown tables:**
- Quality by organization (org name, count, avg score, % ≥ 70)
- Quality by sport code (sport, count, avg score)

**Issue queue:** records with quality_score < 50, sortable, with "Add all to re-scrape queue" bulk action

---

### 3. Merge Tool (`merge_tool.py`)

**Purpose:** Surface suspected duplicate leagues and resolve them — leagues only.

**Dedup identity fields** (matching the UUID model): org name + sport code + season year + venue + day of week + competition level

**UI flow:**
1. "Scan for duplicates" button → runs dedup query
2. Shows count of suspected duplicate groups
3. Each group: side-by-side card showing both records, all fields, quality scores, source URLs
4. Actions per pair: **Keep Both** / **Merge** (keep higher quality score, archive other) / **Delete** (archive the erroneous one)
5. Confirmation required before Merge/Delete

---

## What Is NOT Changing

- **Org View** — unchanged. Remains the classification tool for all listing types.
- **DB schema** — no new columns needed. Existing `listing_type` + `is_archived` are sufficient.
- **app.py navigation** — pages already wired up (stubs exist), just need implementations.

---

## Shared Utility

A small `src/database/leagues_reader.py` module provides the filtered queries used by all three pages, keeping the Supabase logic out of the Streamlit layer:

```python
def get_leagues(filters: dict = None) -> list[dict]: ...
def get_quality_summary() -> dict: ...
def get_field_coverage() -> dict: ...
def get_duplicate_groups() -> list[dict]: ...
```

---

## Implementation Order

1. `leagues_reader.py` + tests (foundation for all three pages)
2. `leagues_viewer.py`
3. `data_quality.py`
4. `merge_tool.py`
5. Full test suite run
