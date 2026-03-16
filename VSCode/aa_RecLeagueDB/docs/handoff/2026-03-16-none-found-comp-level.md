# Handoff: "None Found" default for source_comp_level

**Date:** 2026-03-16
**From:** Division-aware extraction (v1.6)
**Branch:** `feat/parent-child-merge`

---

## Context

v1.6 introduced `source_comp_level` (raw label) and `standardized_comp_level` (single letter A-D). Currently, when a page doesn't mention a competition level, both fields are left null/empty.

## Requirements

### 1. Default "None Found" instead of empty

When extraction finds no competition level for a league, set:
- `source_comp_level` = `"None Found"`
- `standardized_comp_level` = `"A"` (baseline assumption: if a league doesn't advertise tiers, treat it as the top/only tier)

This applies in two places:
- **Post-extraction in `yaml_extractor.py`:** After the normalization fallback block (~line 132-144), if `source_comp_level` is still null/empty, set it to `"None Found"` and `standardized_comp_level` to `"A"`.
- **Backfill existing DB rows:** Write a migration to update `leagues_metadata` where `source_comp_level IS NULL` to `"None Found"` / `"A"`.

### 2. Flag duplicate "None Found" leagues

When multiple leagues share all of these fields but each has `source_comp_level = "None Found"`:
- `organization_name`
- `sport_name`
- `day_of_week`
- `gender_eligibility`
- `venue_name`
- `season_year`

...they are likely duplicates extracted from overlapping pages (e.g., home + detail page both producing the same league). These should be flagged for review rather than silently inserted.

**Suggested approach:** In `deduplicate_batch()` (`league_id_generator.py`), when two leagues match on the fields above and both have `source_comp_level = "None Found"`, merge them (same as current dedup behavior -- this should already work since `source_comp_level` is part of the identity key and both would match on `"None Found"`).

The concern is cross-URL dedup (different scrape runs). In `check_duplicate_league()`, the same logic applies -- two DB rows with identical identity keys including `source_comp_level = "None Found"` should match as duplicates.

**Verify:** Run a dry-run on a site that doesn't list comp levels (e.g., a simple single-league page) and confirm:
- `source_comp_level` shows `"None Found"` (not empty)
- `standardized_comp_level` shows `"A"`
- Re-running the same site doesn't create duplicate rows

## Files to change

- `src/extractors/yaml_extractor.py` — add "None Found" default after normalization block
- `src/utils/comp_level_normalizer.py` — add `"none found": "A"` to `COMP_LEVEL_MAP`
- `tests/test_comp_level_normalizer.py` — add test for "None Found" -> "A"
- `tests/test_yaml_extractor.py` — add test for null comp level -> "None Found" / "A"
- `migrations/008_backfill_none_found.sql` — backfill existing null rows

## Not in scope

- Changing dedup logic -- the current identity key matching should handle "None Found" matches correctly since it's now a concrete value rather than null (which is treated as wildcard).
