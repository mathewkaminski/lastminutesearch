# CLAUDE_MANAGE - Data Management Context

**Purpose:** Data validation, quality scoring, deduplication, enrichment, re-scraping triggers
**When to use:** After extraction, for data cleaning, when reviewing database quality
**Related contexts:** Use [CLAUDE_EXTRACT.md](CLAUDE_EXTRACT.md) for initial scraping/extraction
**Streamlit pages:** Leagues Viewer, Data Quality, URL Merge, League Merge (see section below)

---

## Core Responsibility

**Ensure data quality meets analytics standards before querying.**

This context handles:
- Post-extraction validation
- Quality scoring and gap detection
- Deduplication logic
- Re-scraping triggers
- Team count enrichment (Tool 2)
- Manual review workflows

---

## Data Quality Framework

### Quality Score (0-100)

**Calculation:**
- Start at 100
- Deduct for missing important fields (-5 each)
- Deduct for invalid values (-10 each)
- Deduct for suspicious data (-15 each)

**Thresholds:**
- **≥ 80:** Excellent quality, ready for analytics
- **50-79:** Good quality, minor gaps acceptable
- **30-49:** Poor quality, needs review or re-scrape
- **< 30:** Critical issues, manual intervention required

**Implementation:** `src/database/validators.py`

---

## Field Coverage Analysis

**What it measures:** % of leagues with each field populated

**Example output:**
```
Field Coverage Report:
- organization_name: 100% (required)
- sport_season_code: 100% (required)
- team_fee: 45% (important) ⚠️
- individual_fee: 62% (important)
- day_of_week: 78% (important)
- venue_name: 85% (important)
- num_teams: 12% (optional) ⚠️
```

**Interpretation:**
- `team_fee` at 45% → Systematic extraction gap, needs prompt refinement
- `num_teams` at 12% → Expected (requires Tool 2 enrichment)

---

## Validation Checks

### 1. Schema Validation

**Required fields must be present:**
- `league_id` (UUID)
- `organization_name` (text)
- `sport_season_code` (char(3))
- `url_scraped` (text)

**Test:**
```sql
SELECT * FROM leagues_metadata
WHERE organization_name IS NULL
   OR sport_season_code IS NULL
   OR url_scraped IS NULL;
```

**Action if fails:** Flag for manual review, these are critical

---

### 2. Data Type Validation

**Check proper types:**
- Dates are valid ISO format (YYYY-MM-DD)
- Times are valid (HH:MM:SS)
- Decimals are numeric (team_fee, individual_fee)
- Enums match allowed values (day_of_week, gender_eligibility)

**Test:**
```sql
SELECT * FROM leagues_metadata
WHERE season_start_date IS NOT NULL
  AND season_start_date::text !~ '^\d{4}-\d{2}-\d{2}$';
```

**Action if fails:** Re-extract with stricter validation

---

### 3. Business Logic Validation

**Suspicious patterns:**
- `season_end_date` < `season_start_date`
- `team_fee` = 0 and `individual_fee` = 0 (free league is rare)
- `num_teams` = 1 (likely extraction error)
- `num_teams` > 100 (probably wrong)
- `registration_deadline` after `season_start_date`

**Test:**
```sql
SELECT * FROM leagues_metadata
WHERE season_end_date < season_start_date
   OR (team_fee = 0 AND individual_fee = 0)
   OR num_teams = 1
   OR num_teams > 100
   OR registration_deadline > season_start_date;
```

**Action if fails:** Flag for manual review, may need re-extraction

---

### 4. Important Field Coverage

**These fields should be present for good analytics:**
- `day_of_week`
- `start_time`
- `venue_name`
- `team_fee` OR `individual_fee` (at least one)
- `season_start_date`
- `season_end_date`
- `source_comp_level`
- `gender_eligibility`

**Test:**
```sql
SELECT 
    COUNT(*) as total_leagues,
    SUM(CASE WHEN day_of_week IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as day_coverage,
    SUM(CASE WHEN start_time IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as time_coverage,
    SUM(CASE WHEN venue_name IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as venue_coverage
FROM leagues_metadata;
```

**Action if <70% coverage:** Improve extraction prompts or multi-page navigation

---

## Quality Score Thresholds → Actions

Quality bands are defined in `src/config/quality_thresholds.py`:

| Band | Score | Constant | League Checker Action |
|------|-------|----------|-----------------------|
| THIN | 0–59 | `AUTO_REPLACE_THRESHOLD = 60` | Super scrape auto-archives if contradicted |
| BORDERLINE | 60–74 | `DEEP_SCRAPE_THRESHOLD = 75` | Super scrape triggered; contradictions queued for review |
| ACCEPTABLE | 75–89 | — | Standard team count check |
| SUBSTANTIAL | 90+ | — | Standard team count check |

**League Checker branching:** When `min(quality_score) < 75` for a URL's leagues, League Checker
triggers `super_scraper.run()` (deep crawl + team count pass) instead of the standard check.

---

## League Identity Model (Deduplication)

**A unique league is defined by:**
1. `organization_name` (normalized, lowercase)
2. `sport_season_code` (SSS format)
3. `season_year` (derived from dates)
4. `venue_name` (normalized, lowercase)
5. `day_of_week`
6. `source_comp_level` (normalized)

**Deduplication logic:**
```sql
SELECT 
    LOWER(organization_name) as org,
    sport_season_code,
    season_year,
    LOWER(venue_name) as venue,
    day_of_week,
    LOWER(source_comp_level) as level,
    COUNT(*) as duplicates
FROM leagues_metadata
GROUP BY 1, 2, 3, 4, 5, 6
HAVING COUNT(*) > 1;
```

**Action if duplicates found:**
1. Keep record with highest quality_score
2. Merge unstructured data (league_vectors) into kept record
3. Delete duplicate records
4. Log merge for audit trail

**Edge cases:**
- Same league, different URLs → Keep both, mark as `same_league_id` reference
- Same org, different venues → Separate leagues
- Same everything, different times → Separate leagues (multiple sessions)

### Merge Tool Split

The old single Merge Tool has been replaced with two scoped tools:

| Tool | Page | Scope | Backend |
|------|------|-------|---------|
| **URL Merge** | `url_merge.py` | Finds duplicates within a single `url_scraped` using `find_within_url_duplicates()` | `get_duplicate_groups_for_url()` |
| **League Merge** | `league_merge.py` | Cross-URL dedup using the 6-field identity model | `get_duplicate_groups()` |

Both tools share the same `_merge()` / `archive_league()` backend.

**Confidence levels (URL Merge only):**
- `AUTO` — 5–6 identity fields match (safe to auto-archive in super scraper)
- `REVIEW` — 4 identity fields match (surfaced for manual review in URL Merge)

---

## Re-Scraping Triggers

**When to re-scrape a league:**

### Trigger 1: Quality Score Too Low
- Condition: `quality_score < 50`
- Action: Re-run Tool 1 with enhanced prompts
- Frequency: Once per week max

### Trigger 2: Important Field Missing
- Condition: `team_fee` IS NULL AND `individual_fee` IS NULL
- Action: Re-scrape with multi-page navigation enabled
- Frequency: Once per week max

### Trigger 3: Data Staleness
- Condition: `updated_at` > 30 days ago AND league is active
- Action: Re-scrape to check for updates
- Frequency: Monthly

### Trigger 4: Enrichment Opportunity
- Condition: `num_teams` IS NULL AND quality_score ≥ 50
- Action: Run Tool 2 (Team Count Enrichment)
- Frequency: On-demand

**Implementation:**
```sql
-- Find leagues needing re-scrape
SELECT league_id, url_scraped, quality_score
FROM leagues_metadata
WHERE quality_score < 50
   OR (team_fee IS NULL AND individual_fee IS NULL)
   OR (updated_at < NOW() - INTERVAL '30 days');
```

---

## Team Count Enrichment (Tool 2)

**Purpose:** Update `num_teams` field for leagues missing this data

**When to trigger:**
- `num_teams` IS NULL
- `num_teams` = 0
- `num_teams` = 1 (likely error)
- Quality score flags it as gap

**Process:**
1. Fetch league record from database
2. Navigate to standings or schedule page (inferred from league type)
3. Count unique teams in standings table
4. Update `num_teams` field in database
5. Recalculate quality_score

**Conflict resolution:**
- Tool 2 can ONLY update `num_teams`
- If Tool 2 extraction contradicts other fields, log conflict
- Never allow Tool 2 to overwrite core metadata

**Usage (future):**
```bash
python scripts/test_single_url.py <league_id> --team-count-only
```

---

## Manual Review Workflow

**When required:**
- Quality score < 30
- Deduplication conflicts
- Business logic violations (impossible dates, etc.)
- Tool 1 vs Tool 2 contradictions

**Review process:**
1. Pull league record + raw HTML from `Scrapes/`
2. Manually inspect website
3. Determine correct values
4. Update record directly in database
5. Mark as `manually_reviewed = TRUE`
6. Add notes to `review_notes` field

**Review queue:**
```sql
SELECT league_id, organization_name, url_scraped, quality_score
FROM leagues_metadata
WHERE quality_score < 30
   OR manually_reviewed IS NULL
ORDER BY quality_score ASC
LIMIT 50;
```

---

## Field Coverage Gaps

**Systematic gaps indicate extraction issues:**

### Gap 1: team_fee coverage < 60%
**Possible causes:**
- Fees on separate pricing page (need multi-page nav)
- Fees in PDF (need PDF extraction)
- Fees behind login (may need manual entry)

**Action:** Enhance extraction prompt or add pricing page navigation

---

### Gap 2: num_teams coverage < 30%
**Possible causes:**
- Standings page not linked from main page
- Requires separate Tool 2 enrichment

**Action:** Expected gap, use Tool 2 when needed

---

### Gap 3: venue_name coverage < 70%
**Possible causes:**
- Venue info on schedule page, not main page
- Venue in dropdown or hidden element

**Action:** Add schedule page navigation to extraction

---

### Gap 4: season dates coverage < 70%
**Possible causes:**
- Dates in calendar format (need parsing)
- Dates in text ("Early Spring 2024")

**Action:** Improve LLM prompt to parse natural language dates

---

## Data Cleaning Utilities

### Normalize Organization Names
```python
def normalize_org_name(name: str) -> str:
    """Standardize org names for deduplication."""
    return name.lower().strip().replace("  ", " ")
```

### Normalize Venue Names
```python
def normalize_venue(venue: str) -> str:
    """Standardize venue names."""
    # Remove city if present
    # Normalize abbreviations (e.g., "Ctr" → "Center")
    # Lowercase, strip whitespace
    return venue.lower().strip()
```

### Infer Season Year
```python
def infer_season_year(start_date: date, end_date: date) -> int:
    """Derive season_year from max(start_date, end_date)."""
    return max(start_date, end_date).year if start_date and end_date else None
```

---

## Validation Commands

### Run Extraction Tests
```bash
pytest tests/test_yaml_extractor.py tests/test_validators.py -v
```

### Run Quality / Enrichment Tests
```bash
pytest tests/test_quality_thresholds.py tests/test_consolidator.py tests/test_field_enricher.py -v
```

### Check a Specific URL via CLI
```bash
python scripts/smart_scraper.py --url <url> --dry-run
```

---

## Database Maintenance

### Recalculate Quality Scores
```sql
-- Run this after manual edits to update scores
UPDATE leagues_metadata
SET quality_score = calculate_quality_score(league_id);
```

### Archive Stale Leagues
```sql
-- Mark leagues as inactive if season ended >1 year ago
UPDATE leagues_metadata
SET is_active = FALSE
WHERE season_end_date < NOW() - INTERVAL '1 year';
```

### Vacuum & Analyze
```sql
VACUUM ANALYZE leagues_metadata;
VACUUM ANALYZE league_vectors;
```

---

## Success Metrics

**Database is healthy when:**
- ✅ Average quality_score ≥ 70
- ✅ Important field coverage ≥ 70%
- ✅ <5% of records flagged for manual review
- ✅ Zero duplicate league_ids
- ✅ All required fields 100% populated

**Database needs attention when:**
- ⚠️ Average quality_score < 60
- ⚠️ Important field coverage < 60%
- ⚠️ >10% of records needing re-scrape
- ⚠️ Duplicate records found

---

## Streamlit Data Management Pages

Five pages in `streamlit_app/pages/` serve this context. All read/write `leagues_metadata` via Supabase.

### 1. leagues_viewer.py — Browse & Filter Leagues

**Purpose:** Paginated browse of `leagues_metadata` with filters.

**Features to build:**
- Filter by: sport_season_code, organization_name, city, quality_score range, is_archived
- Sortable columns: quality_score, created_at, updated_at, season_start_date
- Row-level view: expand any league to see all fields
- Quick actions: mark as archived, trigger re-scrape (add to scrape_queue)
- Export filtered results to CSV

**Key query:**
```sql
SELECT * FROM leagues_metadata
WHERE is_archived = FALSE
ORDER BY quality_score ASC, created_at DESC
LIMIT 50 OFFSET :offset;
```

---

### 2. data_quality.py — Quality Dashboard

**Purpose:** Identify systemic data issues and individual records needing attention.

**Features to build:**
- Summary metrics: avg quality_score, % records ≥70, % needing re-scrape
- Field coverage chart: % populated per important field (team_fee, venue_name, dates, etc.)
- Issue queue: records with quality_score < 50, ordered by score ascending
- Breakdown by organization and sport — surfaces which orgs have poor data
- Re-scrape trigger: button to add flagged records back to scrape_queue

**Key queries:**
```sql
-- Coverage report
SELECT
    COUNT(*) as total,
    AVG(quality_score) as avg_score,
    SUM(CASE WHEN team_fee IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as fee_coverage,
    SUM(CASE WHEN venue_name IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as venue_coverage,
    SUM(CASE WHEN day_of_week IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as day_coverage
FROM leagues_metadata WHERE is_archived = FALSE;

-- Issue queue
SELECT league_id, organization_name, url_scraped, quality_score, sport_season_code
FROM leagues_metadata
WHERE quality_score < 50 AND is_archived = FALSE
ORDER BY quality_score ASC;
```

---

### 3. merge_tool.py — Deduplication & Merge

**Purpose:** Identify suspected duplicate leagues and resolve them (keep/merge/delete).

**Features:**
- Runs dedup query to surface suspected duplicates (same org + sport + year + venue + day + level)
- Side-by-side comparison of duplicate pairs: all fields, quality scores, source URLs
- Actions per pair:
  - **Keep both** — they're legitimately different
  - **Merge** — keep higher quality_score record, copy non-null fields from the other, archive duplicate
  - **Delete** — remove clearly erroneous record
- Audit log: every merge/delete action logged with timestamp and rationale

**Dedup query:**
```sql
SELECT
    LOWER(organization_name) as org,
    sport_season_code,
    season_year,
    LOWER(COALESCE(venue_name, '')) as venue,
    day_of_week,
    LOWER(COALESCE(source_comp_level, '')) as level,
    COUNT(*) as duplicates,
    array_agg(league_id) as league_ids,
    array_agg(quality_score) as scores
FROM leagues_metadata
WHERE is_archived = FALSE
GROUP BY 1, 2, 3, 4, 5, 6
HAVING COUNT(*) > 1
ORDER BY duplicates DESC;
```

### 4. venues_enricher.py — Venue Address Lookup

**Purpose:** Resolve venue_name + city pairs to structured addresses via Google Places API.

**Features:** Run enrichment (batch), review queue for confidence < 75, Accept/Edit/Skip actions.

**Key modules:** `src/enrichers/venue_enricher.py`, `src/enrichers/places_client.py`, `src/database/venue_store.py`

**New env var required:** `GOOGLE_PLACES_API_KEY`

---

### 5. fill_in_leagues.py — Multi-Mode League Enrichment

**Purpose:** Enrich existing league records in three modes selectable per URL batch.

**Modes:**
- **Fill Fields** — `FieldEnricher.enrich_url()` runs snapshot → mini-crawl → Firecrawl cascade to fill null fields
- **Teams** — `LeagueChecker._standard_check()` navigates standings pages to populate `num_teams`; auto-triggers `super_scraper.run()` when `quality_score < 75`
- **Deep-dive** — Runs `scripts/super_scraper.py` full re-crawl + reconciliation against existing records

**Key modules:**
| Module | Purpose |
|--------|---------|
| `src/enrichers/field_enricher.py` | Fill Fields backend — orchestrates snapshot → mini-crawl → Firecrawl cascade |
| `src/checkers/league_checker.py` | Teams mode backend — `_standard_check()` + super scraper trigger |
| `src/checkers/team_count_extractor.py` | Extracts team counts from standings/schedule pages |
| `src/checkers/playwright_navigator.py` | Playwright navigation for checker flows |
| `src/enrichers/confidence_scorer.py` | Scores enrichment confidence for each field |
| `scripts/super_scraper.py` | Deep-dive backend |

---

## Integration with Other Contexts

**After validation:**
- If quality is good → Ready for [CLAUDE_QUERY.md](CLAUDE_QUERY.md) analytics
- If quality is poor → Return to [CLAUDE_EXTRACT.md](CLAUDE_EXTRACT.md) for re-scraping
- If gaps are systematic → Refactor extraction prompts in [CLAUDE_EXTRACT.md](CLAUDE_EXTRACT.md)

---

**Key takeaway: Data quality determines analytics quality. Never skip validation.**
