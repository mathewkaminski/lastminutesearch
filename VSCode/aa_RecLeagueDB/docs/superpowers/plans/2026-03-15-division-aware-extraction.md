# Division-Aware League Extraction Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract A/B/C division leagues as separate rows, replacing `competition_level` with `source_comp_level` + `standardized_comp_level`.

**Architecture:** Rename DB column, update LLM extraction prompt to split divisions, add deterministic fallback normalizer, update all code references. The identity key field name changes but dedup logic stays the same.

**Tech Stack:** Python, Supabase (PostgreSQL), Claude Sonnet (extraction LLM), pytest

**Spec:** `docs/superpowers/specs/2026-03-15-division-aware-extraction-design.md`

---

## Chunk 1: Normalizer + Core Pipeline

### Task 1: Create comp_level_normalizer with tests

**Files:**
- Create: `src/utils/comp_level_normalizer.py`
- Create: `tests/test_comp_level_normalizer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_comp_level_normalizer.py
"""Tests for competition level normalization."""
from src.utils.comp_level_normalizer import normalize_comp_level


class TestNormalizeCompLevel:
    def test_competitive_maps_to_a(self):
        assert normalize_comp_level("Competitive") == "A"

    def test_a_league_maps_to_a(self):
        assert normalize_comp_level("A League") == "A"

    def test_gold_maps_to_a(self):
        assert normalize_comp_level("Gold") == "A"

    def test_intermediate_maps_to_b(self):
        assert normalize_comp_level("Intermediate") == "B"

    def test_b_league_maps_to_b(self):
        assert normalize_comp_level("B League") == "B"

    def test_recreational_maps_to_c(self):
        assert normalize_comp_level("Recreational") == "C"

    def test_house_maps_to_c(self):
        assert normalize_comp_level("House") == "C"

    def test_division_1_maps_to_a(self):
        assert normalize_comp_level("Division 1") == "A"

    def test_unknown_returns_none(self):
        assert normalize_comp_level("Super Elite Pro") is None

    def test_none_returns_none(self):
        assert normalize_comp_level(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_comp_level("") is None

    def test_case_insensitive(self):
        assert normalize_comp_level("RECREATIONAL") == "C"

    def test_whitespace_trimmed(self):
        assert normalize_comp_level("  Competitive  ") == "A"

    def test_single_letter_a(self):
        assert normalize_comp_level("A") == "A"

    def test_single_letter_b(self):
        assert normalize_comp_level("B") == "B"

    def test_premier_maps_to_a(self):
        assert normalize_comp_level("Premier") == "A"

    def test_novice_maps_to_d(self):
        assert normalize_comp_level("Novice") == "D"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/mathe/VSCode/aa_RecLeagueDB && python -m pytest tests/test_comp_level_normalizer.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Write implementation**

```python
# src/utils/comp_level_normalizer.py
"""Deterministic competition level normalization.

Maps raw competition level labels to standardized single-letter grades:
A = most competitive, B, C, D... descending.
"""

from typing import Optional


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


def normalize_comp_level(source_comp_level: Optional[str]) -> Optional[str]:
    """Normalize a raw competition level label to a single letter A-Z.

    Args:
        source_comp_level: Raw label (e.g., "A League", "Recreational", "Gold")

    Returns:
        Single uppercase letter (A=most competitive) or None if unmappable
    """
    if not source_comp_level or not str(source_comp_level).strip():
        return None

    key = str(source_comp_level).strip().lower()
    return COMP_LEVEL_MAP.get(key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/Users/mathe/VSCode/aa_RecLeagueDB && python -m pytest tests/test_comp_level_normalizer.py -v`
Expected: All 17 tests PASS

- [ ] **Step 5: Commit**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add src/utils/comp_level_normalizer.py tests/test_comp_level_normalizer.py
git commit -m "feat: add comp_level_normalizer with deterministic A-D mapping"
```

---

### Task 2: Update league_id_generator (identity key rename)

**Files:**
- Modify: `src/utils/league_id_generator.py` (lines 127-137, 222, 260-264, 393-396, docstrings)
- Modify: `tests/test_parent_child_dedup.py` (lines 17, 27, 56, 58)

- [ ] **Step 1: Rename all `competition_level` references in league_id_generator.py**

Use `replace_all` to change every occurrence of `competition_level` to `source_comp_level` in the file. This covers:

- `IDENTIFYING_FIELDS` list (line 262)
- `build_uniqueness_key` dict key + `data.get()` (line 133)
- `league_display_name` field tuple (line 222)
- `format_uniqueness_key` key reference (line 466)
- `_DEDUP_FIELDS` SQL select string in `check_duplicate_league` (line 395) -- **CRITICAL: this is a DB column name used in Supabase `.select()`, will break after migration if not renamed**
- All docstrings referencing `competition_level` (lines 9, 114, 375)

- [ ] **Step 2: Update test fixtures**

In `tests/test_parent_child_dedup.py`:

Line 17: `"competition_level": "Recreational"` → `"source_comp_level": "Recreational"`
Line 27: `merged["competition_level"]` → `merged["source_comp_level"]`
Lines 56, 58: `"competition_level": "Rec"` → `"source_comp_level": "Rec"`

- [ ] **Step 3: Run tests**

Run: `cd C:/Users/mathe/VSCode/aa_RecLeagueDB && python -m pytest tests/test_parent_child_dedup.py -v`
Expected: All 3 tests PASS

- [ ] **Step 4: Commit**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add src/utils/league_id_generator.py tests/test_parent_child_dedup.py
git commit -m "refactor: rename competition_level to source_comp_level in identity key"
```

---

### Task 3: Update validators (quality score)

**Files:**
- Modify: `src/database/validators.py` (line 88)
- Modify: `tests/test_validators.py` (line 15)

- [ ] **Step 1: Update tier1_fields in calculate_quality_score**

In `src/database/validators.py` line 88, change `"competition_level"` to `"source_comp_level"` in `tier1_fields` list. Do NOT add `standardized_comp_level` -- null is a valid state for it.

- [ ] **Step 2: Update test fixture**

In `tests/test_validators.py` line 15, change:
```python
"competition_level": "Recreational",
```
to:
```python
"source_comp_level": "Recreational",
```

- [ ] **Step 3: Run tests**

Run: `cd C:/Users/mathe/VSCode/aa_RecLeagueDB && python -m pytest tests/test_validators.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add src/database/validators.py tests/test_validators.py
git commit -m "refactor: rename competition_level to source_comp_level in quality score"
```

---

### Task 4: Update writer.py (schema_fields whitelist + insert)

**Files:**
- Modify: `src/database/writer.py` (line 347)

- [ ] **Step 1: Update schema_fields**

In `src/database/writer.py` line 347, change:
```python
"competition_level",
```
to:
```python
"source_comp_level",
"standardized_comp_level",
```

- [ ] **Step 2: Commit**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add src/database/writer.py
git commit -m "refactor: update writer schema_fields for comp level rename"
```

---

### Task 5: Update extraction prompt + post-processing

**Files:**
- Modify: `src/extractors/yaml_extractor.py` (lines 225, 243-260, 466-499)

- [ ] **Step 1: Update schema in _build_extraction_prompt**

In `src/extractors/yaml_extractor.py` line 225, replace:
```python
      "competition_level": "string (e.g., Recreational, Intermediate, Competitive) or null",
```
with:
```python
      "source_comp_level": "string - competition level EXACTLY as described on the page (e.g., 'A League', 'Gold Division', 'Competitive', 'Recreational'). Preserve the league's own wording. null if not specified.",
      "standardized_comp_level": "string - single letter A-Z ranking. A=most competitive, then B, C, D descending. Map: Competitive/A/Gold/Premier/Division 1 → A, Intermediate/B/Silver → B, Recreational/C/Bronze/House → C. Use the league's own hierarchy. null if unclear.",
```

- [ ] **Step 2: Add division-split instruction**

After line 247 (the line about "extract both as separate leagues"), add:
```python
- CRITICAL: If a page describes multiple divisions, tiers, or skill levels for the SAME sport (e.g., "A League" and "B League", "Division 1" and "Division 2", "Gold" and "Silver", "Competitive" and "Recreational"), extract EACH division as a SEPARATE league entry. Each gets its own source_comp_level and standardized_comp_level. Example: "Women's A League (competitive)" and "Women's B League (recreational)" on the same night = TWO separate league entries.
```

- [ ] **Step 3: Update _calculate_identifying_completeness docstring**

In `_calculate_identifying_completeness` (line 476), change `6. competition_level` to `6. source_comp_level` in the docstring.

- [ ] **Step 4: Add post-extraction normalization fallback**

In `extract_league_data_from_yaml`, after the line that sets `identifying_fields_pct` for each league (around line 135-145 in the post-processing loop), add normalization:

```python
# Normalize standardized_comp_level via fallback if LLM didn't set it
from src.utils.comp_level_normalizer import normalize_comp_level  # import outside loop
for league in leagues:
    # Coerce empty strings to None
    if league.get("standardized_comp_level") in ("", None):
        league["standardized_comp_level"] = None
    # Validate LLM output: must be single uppercase A-Z letter
    std = league.get("standardized_comp_level")
    if std and (len(str(std)) != 1 or not str(std).isalpha()):
        league["standardized_comp_level"] = None
    elif std:
        league["standardized_comp_level"] = str(std).upper()
    # Fallback: derive from source_comp_level if still null
    if league.get("standardized_comp_level") is None and league.get("source_comp_level"):
        league["standardized_comp_level"] = normalize_comp_level(league["source_comp_level"])
```

- [ ] **Step 5: Update test fixture and add normalizer fallback tests**

In `tests/test_yaml_extractor.py`, update `_STUB_LEAGUE_JSON` (line 46): change `"competition_level": null` to:
```python
    "source_comp_level": null,
    "standardized_comp_level": null,
```

Add new test class for normalizer fallback behavior:

```python
class TestCompLevelNormalization:
    def test_fallback_fills_standardized_from_source(self):
        """When LLM returns source_comp_level but null standardized, fallback fills it."""
        stub_json = _STUB_LEAGUE_JSON.replace(
            '"source_comp_level": null',
            '"source_comp_level": "Recreational"'
        )
        captured = {}
        import src.extractors.yaml_extractor as mod
        mock = _make_fake_anthropic(captured)
        mock_content = MagicMock()
        mock_content.text = stub_json
        mock.Anthropic.return_value.messages.create.return_value.content = [mock_content]

        with patch.object(mod, "anthropic", mock):
            leagues = mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        assert leagues[0]["source_comp_level"] == "Recreational"
        assert leagues[0]["standardized_comp_level"] == "C"

    def test_invalid_standardized_gets_cleared_and_fallback_runs(self):
        """When LLM returns invalid standardized (e.g., 'XY'), it gets cleared."""
        stub_json = _STUB_LEAGUE_JSON.replace(
            '"source_comp_level": null, "standardized_comp_level": null',
            '"source_comp_level": "Competitive", "standardized_comp_level": "XY"'
        )
        captured = {}
        import src.extractors.yaml_extractor as mod
        mock = _make_fake_anthropic(captured)
        mock_content = MagicMock()
        mock_content.text = stub_json
        mock.Anthropic.return_value.messages.create.return_value.content = [mock_content]

        with patch.object(mod, "anthropic", mock):
            leagues = mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        assert leagues[0]["standardized_comp_level"] == "A"

    def test_valid_single_letter_accepted(self):
        """When LLM returns valid single letter, it's accepted as-is."""
        stub_json = _STUB_LEAGUE_JSON.replace(
            '"standardized_comp_level": null',
            '"standardized_comp_level": "B"'
        )
        captured = {}
        import src.extractors.yaml_extractor as mod
        mock = _make_fake_anthropic(captured)
        mock_content = MagicMock()
        mock_content.text = stub_json
        mock.Anthropic.return_value.messages.create.return_value.content = [mock_content]

        with patch.object(mod, "anthropic", mock):
            leagues = mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        assert leagues[0]["standardized_comp_level"] == "B"
```

- [ ] **Step 6: Run tests**

Run: `cd C:/Users/mathe/VSCode/aa_RecLeagueDB && python -m pytest tests/test_yaml_extractor.py -v`
Expected: All 6 tests PASS (3 existing + 3 new)

- [ ] **Step 7: Commit**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add src/extractors/yaml_extractor.py tests/test_yaml_extractor.py
git commit -m "feat: division-aware extraction prompt with source/standardized comp levels"
```

---

### Task 6: Update smart_scraper.py CSV columns

**Files:**
- Modify: `scripts/smart_scraper.py` (line 37)

- [ ] **Step 1: Update CSV_COLUMNS**

Replace `"competition_level"` with `"source_comp_level", "standardized_comp_level"` in the CSV_COLUMNS list.

- [ ] **Step 2: Commit**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add scripts/smart_scraper.py
git commit -m "refactor: update CSV columns for comp level rename"
```

---

## Chunk 2: Remaining Code References

### Task 7: Bulk rename competition_level across remaining files

All remaining Python files that reference `competition_level` need a find-and-replace to `source_comp_level`. These are non-core files (Streamlit pages, enrichers, readers, checkers, other tests).

**Files to modify (find `competition_level` → replace `source_comp_level`):**

- `src/enrichers/field_enricher.py`
- `src/database/leagues_reader.py`
- `src/database/consolidator.py`
- `src/checkers/league_checker.py`
- `src/extractors/gap_reporter.py`
- `src/extractors/league_extractor.py`
- `scripts/super_scraper.py`
- `scripts/test_phase_1_2.py`
- `streamlit_app/pages/leagues_viewer.py`
- `streamlit_app/pages/league_merge.py`
- `streamlit_app/pages/url_merge.py`
- `streamlit_app/pages/fill_in_leagues.py`
- `streamlit_app/pages/scraper_ui.py`
- `streamlit_app/pages/merge_tool.py`
- `tests/test_extraction.py`
- `tests/test_consolidator.py`
- `tests/test_league_checker_branch.py`
- `tests/test_leagues_reader.py`

- [ ] **Step 1: For each file, replace all occurrences of `competition_level` with `source_comp_level`**

Use find-and-replace. Do NOT add `standardized_comp_level` references unless the code specifically needs to display/filter by standardized level.

- [ ] **Step 2: Run full test suite**

Run: `cd C:/Users/mathe/VSCode/aa_RecLeagueDB && python -m pytest tests/ -v --tb=short 2>&1 | tail -40`
Expected: All tests PASS (some may skip if they need DB)

- [ ] **Step 3: Commit**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add src/ tests/ scripts/ streamlit_app/
git commit -m "refactor: bulk rename competition_level to source_comp_level across codebase"
```

---

### Task 8: Update migration SQL and docs

**Files:**
- Modify: `migrations/create_leagues_metadata.sql` (line 31)
- Create: `migrations/007_rename_competition_level.sql`
- Modify: `docs/DATABASE_SCHEMA.md`

- [ ] **Step 1: Create migration file**

```sql
-- Migration 007: Rename competition_level to source_comp_level, add standardized_comp_level
-- Date: 2026-03-15

ALTER TABLE leagues_metadata RENAME COLUMN competition_level TO source_comp_level;
ALTER TABLE leagues_metadata ADD COLUMN standardized_comp_level VARCHAR(1);

-- Backfill standardized values from existing source data
UPDATE leagues_metadata SET standardized_comp_level = 'A' WHERE LOWER(TRIM(source_comp_level)) = 'competitive';
UPDATE leagues_metadata SET standardized_comp_level = 'B' WHERE LOWER(TRIM(source_comp_level)) = 'intermediate';
UPDATE leagues_metadata SET standardized_comp_level = 'C' WHERE LOWER(TRIM(source_comp_level)) = 'recreational';

COMMENT ON COLUMN public.leagues_metadata.source_comp_level IS 'Raw competition level label from the source page';
COMMENT ON COLUMN public.leagues_metadata.standardized_comp_level IS 'Normalized single-letter grade: A=most competitive, B, C, D descending';
```

- [ ] **Step 2: Update create_leagues_metadata.sql**

Line 31: change `competition_level TEXT,` to:
```sql
    source_comp_level TEXT,
    standardized_comp_level VARCHAR(1),
```

- [ ] **Step 3: Update docs**

Find `competition_level` references and update to reflect both new columns in:
- `docs/DATABASE_SCHEMA.md`
- `docs/agents/CLAUDE_EXTRACT.md`
- `docs/agents/CLAUDE_MANAGE.md`

- [ ] **Step 4: Commit**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add migrations/007_rename_competition_level.sql migrations/create_leagues_metadata.sql docs/
git commit -m "docs: add migration and update schema docs for comp level rename"
```

---

### Task 9: Run migration on Supabase + version bump

- [ ] **Step 1: Run migration on Supabase**

Execute `migrations/007_rename_competition_level.sql` on the Supabase SQL editor.

- [ ] **Step 2: Verify migration**

```sql
SELECT column_name FROM information_schema.columns
WHERE table_name = 'leagues_metadata'
AND column_name IN ('source_comp_level', 'standardized_comp_level', 'competition_level');
```

Expected: `source_comp_level` and `standardized_comp_level` present, `competition_level` absent.

- [ ] **Step 3: Bump version in streamlit footer**

In `streamlit_app/app.py` line 132, change `v1.5` to `v1.6`.

- [ ] **Step 4: Commit and tag**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
git add streamlit_app/app.py
git commit -m "v1.6: division-aware extraction with source/standardized comp levels"
git tag v1.6
```

---

### Task 10: Validate with orcks.org dry-run

- [ ] **Step 1: Clear orcks.org cache**

```bash
rm -rf C:/Users/mathe/VSCode/aa_RecLeagueDB/scrapes/www.orcks.org/
```

- [ ] **Step 2: Run dry-run**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
python scripts/smart_scraper.py --url https://www.orcks.org --dry-run
```

- [ ] **Step 3: Verify CSV output**

Open `dry_run_orcks.org.csv` and verify:
- 5 rows total (3 volleyball, 1 basketball, 1 softball)
- Volleyball rows include: Women's A (standardized A), Women's B (standardized B), CoEd
- `source_comp_level` shows raw labels from the page
- `standardized_comp_level` shows A/B/null as appropriate
