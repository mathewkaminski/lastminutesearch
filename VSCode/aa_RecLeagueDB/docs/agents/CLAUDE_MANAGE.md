# CLAUDE_MANAGE - Data Management Context

**Purpose:** Data validation, quality scoring, deduplication, enrichment, re-scraping triggers
**When to use:** After extraction, for data cleaning, when reviewing database quality
**Related contexts:** Use [CLAUDE_EXTRACT.md](CLAUDE_EXTRACT.md) for initial scraping/extraction

---

## Quality Framework

**Implementation:** `src/database/validators.py`, `src/config/quality_thresholds.py`

| Band | Score | Constant | Action |
|------|-------|----------|--------|
| THIN | 0–59 | `AUTO_REPLACE_THRESHOLD = 60` | Super scrape auto-archives if contradicted |
| BORDERLINE | 60–74 | `DEEP_SCRAPE_THRESHOLD = 75` | Super scrape triggered; contradictions queued for review |
| ACCEPTABLE | 75–89 | — | Standard team count check |
| SUBSTANTIAL | 90+ | — | Standard team count check |

**Required fields:** `league_id`, `organization_name`, `sport_season_code`, `url_scraped`

**Important fields** (scored for quality): `day_of_week`, `start_time`, `venue_name`, `team_fee` OR `individual_fee`, `season_start_date`, `season_end_date`, `source_comp_level`, `gender_eligibility`

**Business logic flags:** `season_end_date < season_start_date`, both fees = 0, `num_teams` = 1, `num_teams` > 100

---

## League Identity Model (Deduplication)

**Unique league defined by 6 fields:**
1. `organization_name` (normalized, lowercase)
2. `sport_season_code` (SSS format)
3. `season_year` (derived from dates)
4. `venue_name` (normalized, lowercase)
5. `day_of_week`
6. `source_comp_level` (normalized)

**Edge cases:** Same league + different URLs → keep both. Same org + different venues → separate leagues. Same everything + different times → separate leagues (multiple sessions).

### Merge Tools

| Tool | Page | Scope | Backend |
|------|------|-------|---------|
| **URL Merge** | `url_merge.py` | Duplicates within a single `url_scraped` | `get_duplicate_groups_for_url()` |
| **League Merge** | `league_merge.py` | Cross-URL dedup via 6-field identity model | `get_duplicate_groups()` |

Both use `_merge()` / `archive_league()` backend.

**Confidence (URL Merge only):** `AUTO` = 5–6 fields match (safe to auto-archive) · `REVIEW` = 4 fields match (surfaced for manual review)

---

## Streamlit Pages

Five pages in `streamlit_app/pages/` — all read/write `leagues_metadata` via Supabase.

| Page | Purpose | Key modules |
|------|---------|-------------|
| `leagues_viewer.py` | Browse/filter leagues, export CSV | `src/database/leagues_reader.py` |
| `data_quality.py` | Quality score distribution, field coverage dashboard | `src/database/validators.py` |
| `url_merge.py` | Dedup within a single `url_scraped` | `src/database/consolidator.py` |
| `league_merge.py` | Cross-URL dedup using 6-field identity model | `src/database/writer.py` |
| `merge_tool.py` | Surface and resolve suspected duplicate records | `src/database/writer.py` |
| `venues_enricher.py` | Resolve venue names via Google Places API | `src/enrichers/venue_enricher.py`, `src/enrichers/places_client.py`, `src/database/venue_store.py` |
| `fill_in_leagues.py` | Multi-mode enrichment: Fill Fields / Teams / Deep-dive | See below |

### fill_in_leagues.py — Modes & Backends

| Mode | What it does | Backend |
|------|-------------|---------|
| Fill Fields | Snapshot → mini-crawl → Firecrawl cascade to fill null fields | `src/enrichers/field_enricher.py` |
| Teams | Navigate standings pages to populate `num_teams`; triggers super scraper if `quality_score < 75` | `src/checkers/league_checker.py`, `src/checkers/team_count_extractor.py` |
| Deep-dive | Full re-crawl + reconciliation against existing records | `scripts/super_scraper.py` |

---

## Validation Commands

```bash
# Quality / enrichment tests
pytest tests/test_quality_thresholds.py tests/test_consolidator.py tests/test_field_enricher.py -v

# Extraction tests
pytest tests/test_yaml_extractor.py tests/test_validators.py -v

# Check a URL via CLI
python scripts/smart_scraper.py --url <url> --dry-run
```

---

**After validation:** good quality → [CLAUDE_QUERY.md](CLAUDE_QUERY.md) · poor quality → [CLAUDE_EXTRACT.md](CLAUDE_EXTRACT.md) for re-scraping
