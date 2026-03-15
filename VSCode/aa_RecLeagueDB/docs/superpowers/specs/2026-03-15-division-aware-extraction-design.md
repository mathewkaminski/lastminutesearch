# Division-Aware League Extraction

**Date:** 2026-03-15
**Status:** Approved
**Branch:** feat/parent-child-merge

## Problem

The LLM extraction prompt in `yaml_extractor.py` merges A/B division leagues into a single row. For example, orcks.org lists:

- Women's A League (Competitive) -- Monday
- Women's B League (Recreational) -- Monday
- Coed Volleyball -- Tuesday

But extraction produces only 2 volleyball rows (Women's Competitive Monday, Coed Recreational Tuesday), missing Women's B entirely.

Additionally, the current `competition_level` column conflates the league's own terminology with our standardized tiers. A league might call itself "Gold Division" or "A League" -- we need both the raw label and a normalized ranking.

## Design

### 1. DB Schema Change

Rename `competition_level` to `source_comp_level` and add `standardized_comp_level` in `leagues_metadata`:

| Column | Type | Description |
|--------|------|-------------|
| `source_comp_level` | text | Raw label from the page (e.g., "A League", "Gold", "Recreational", "Division 1") |
| `standardized_comp_level` | varchar(1) | Normalized letter grade: A=most competitive, B, C, D... Z=least. Null if unknown. |

**Note:** Use `varchar(1)` not `char(1)` to avoid padding issues. Post-extraction must coerce empty strings to NULL.

**Migration:**
```sql
ALTER TABLE leagues_metadata RENAME COLUMN competition_level TO source_comp_level;
ALTER TABLE leagues_metadata ADD COLUMN standardized_comp_level varchar(1);

-- Backfill using exact match (not substring) to avoid false positives
UPDATE leagues_metadata SET standardized_comp_level = 'A' WHERE LOWER(TRIM(source_comp_level)) = 'competitive';
UPDATE leagues_metadata SET standardized_comp_level = 'B' WHERE LOWER(TRIM(source_comp_level)) = 'intermediate';
UPDATE leagues_metadata SET standardized_comp_level = 'C' WHERE LOWER(TRIM(source_comp_level)) = 'recreational';
```

### 2. Extraction Prompt Changes (`src/extractors/yaml_extractor.py`)

Replace `competition_level` in the schema with:

```
"source_comp_level": "string - competition level EXACTLY as described on the page (e.g., 'A League', 'Gold Division', 'Competitive', 'Recreational'). Preserve the league's own wording.",
"standardized_comp_level": "string - single letter A-Z ranking. A=most competitive, then B, C, D descending. Map common patterns: Competitive/A/Gold/Premier/Division 1 → A, Intermediate/B/Silver → B, Recreational/C/Bronze/House → C. Use the league's own hierarchy if they define one. null if unclear."
```

Add explicit division-split instruction to INSTRUCTIONS block:

```
- CRITICAL: If a page describes multiple divisions, tiers, or skill levels for the SAME sport
  (e.g., "A League" and "B League", "Division 1" and "Division 2", "Gold" and "Silver",
  "Competitive" and "Recreational"), extract EACH division as a SEPARATE league entry.
  Each division gets its own row with its own source_comp_level and standardized_comp_level.
  Example: "Women's A League (competitive)" and "Women's B League (recreational)" on the
  same night = TWO separate league entries, not one.
```

### 3. Fallback Normalizer (`src/utils/comp_level_normalizer.py`)

Deterministic function called after extraction if `standardized_comp_level` is null but `source_comp_level` is filled. Handles common patterns:

```python
COMP_LEVEL_MAP = {
    # A-tier (most competitive)
    "competitive": "A", "a league": "A", "a": "A", "gold": "A",
    "premier": "A", "division 1": "A", "div 1": "A", "elite": "A",
    "advanced": "A", "upper": "A",
    # B-tier
    "intermediate": "B", "b league": "B", "b": "B", "silver": "B",
    "division 2": "B", "div 2": "B", "mid": "B", "middle": "B",
    # C-tier
    "recreational": "C", "c league": "C", "c": "C", "bronze": "C",
    "division 3": "C", "div 3": "C", "house": "C", "social": "C",
    "beginner": "C", "lower": "C", "fun": "C",
    # D-tier
    "d league": "D", "d": "D", "division 4": "D", "div 4": "D",
    "novice": "D",
}
```

The normalizer lowercases and trims `source_comp_level` before lookup. If no pattern matches, leave `standardized_comp_level` as null for manual review. Empty strings are coerced to null.

The LLM may also return `standardized_comp_level` directly -- validate it is exactly one uppercase letter A-Z before accepting. If invalid, fall through to the deterministic normalizer.

### 4. Code References to Update

All files referencing `competition_level` must switch to `source_comp_level`:

**Core pipeline (must change):**
- `src/utils/league_id_generator.py` -- identity key field name
- `src/extractors/yaml_extractor.py` -- prompt schema + completeness calc
- `src/database/writer.py` -- insert/merge field mapping
- `src/enrichers/field_enricher.py` -- enrichment fields
- `scripts/smart_scraper.py` -- CSV_COLUMNS
- `src/database/validators.py` -- validation rules

**Streamlit pages (must change):**
- `streamlit_app/pages/leagues_viewer.py`
- `streamlit_app/pages/league_merge.py`
- `streamlit_app/pages/url_merge.py`
- `streamlit_app/pages/fill_in_leagues.py`
- `streamlit_app/pages/scraper_ui.py`
- `streamlit_app/pages/merge_tool.py`

**Tests (must change):**
- `tests/test_parent_child_dedup.py`
- `tests/test_yaml_extractor.py`
- `tests/test_validators.py`
- `tests/test_extraction.py`
- `tests/test_consolidator.py`
- `tests/test_league_checker_branch.py`
- `tests/test_leagues_reader.py`

**Other code:**
- `src/database/leagues_reader.py`
- `src/database/consolidator.py`
- `src/checkers/league_checker.py`
- `src/extractors/gap_reporter.py`
- `src/extractors/league_extractor.py`
- `scripts/super_scraper.py`
- `scripts/test_phase_1_2.py`

**Migrations:**
- `migrations/create_leagues_metadata.sql`

**Docs (update when convenient):**
- `docs/DATABASE_SCHEMA.md`
- `docs/agents/CLAUDE_EXTRACT.md`
- `docs/agents/CLAUDE_MANAGE.md`

### 5. Identity Key Impact

`league_id_generator.py` uses `competition_level` in the 9-field identity key. This becomes `source_comp_level`. Specific changes required:

- `IDENTIFYING_FIELDS` list: `"competition_level"` → `"source_comp_level"`
- `build_uniqueness_key()`: `data.get("competition_level")` → `data.get("source_comp_level")`
- `league_display_name()`: field tuple reference update
- All internal dict keys change from `"competition_level"` to `"source_comp_level"`

The dedup logic is unchanged -- it still compares the raw value. Two leagues with different `source_comp_level` values (e.g., "A League" vs "B League") will correctly be treated as distinct leagues.

**Note:** `writer.py` has a `schema_fields` whitelist in `_prepare_for_insert()` that must include both `source_comp_level` and `standardized_comp_level`, or they will be silently dropped.

**Note:** `validators.py` `calculate_quality_score()` penalizes missing `competition_level` as a Tier 1 field. This changes to `source_comp_level`. Missing `standardized_comp_level` should NOT incur a penalty (null is valid for unknown levels).

### 6. Test Case

After implementation, running `python scripts/smart_scraper.py --url https://www.orcks.org --dry-run` should produce:

| sport_name | gender_eligibility | day_of_week | source_comp_level | standardized_comp_level |
|---|---|---|---|---|
| Volleyball | Womens | Monday | A League | A |
| Volleyball | Womens | Monday | B League | B |
| Volleyball | CoEd | Tuesday | | |
| Basketball | Mens | Wednesday | | |
| Softball | CoEd | Friday | | |

5 leagues total, 3 volleyball (up from 2).
