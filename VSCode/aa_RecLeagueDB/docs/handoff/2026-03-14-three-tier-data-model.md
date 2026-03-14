# Handoff: Three-Tier Data Model Restructure

**Date:** 2026-03-14
**Goal:** Reorganize league data into three clear tiers — Identifiers, Structured Data, Unstructured Data — and align the database schema, extraction pipeline, quality scoring, and dedup logic to match.

---

## Context

RecSportsDB scrapes adult recreational sports league websites, extracts structured metadata via LLM (Claude), and stores it in Supabase (PostgreSQL + pgvector). The current schema has ~35 columns on `leagues_metadata` with flat organization. This handoff restructures the mental model into three tiers.

**Key files to read first:**
- `CLAUDE.md` — project router, pick the right agent context
- `docs/DATABASE_SCHEMA.md` — current schema reference
- `src/extractors/yaml_extractor.py` — LLM extraction prompt (defines what fields get pulled)
- `src/database/writer.py` — insert/update logic, field merge
- `src/database/validators.py` — quality score calculation
- `src/utils/league_id_generator.py` — dedup logic (8-field identity model)

**Database access:**
```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL"
```

---

## Tier 1: Identifiers

These fields define **what makes a league unique**. Nearly all should be extractable from any league website. Together they answer: "Which specific league offering is this?"

| Field | DB Column | Type | Notes |
|-------|-----------|------|-------|
| Organization | `organization_name` | text | Required. The org running the league. |
| Sport | `sport_name` | text | Required. e.g., "Soccer", "Ball Hockey", "3-Pitch Softball" |
| Season | `season_name` | text | Required. e.g., "Winter", "Late Winter", "Summer" |
| Season Year | `season_year` | int | Derived from `season_start_date` |
| Day of Week | `day_of_week` | text | Monday-Sunday |
| # Weeks | `num_weeks` | int | Length of season |
| Start Date | `season_start_date` | date | First game date |
| End Date | `season_end_date` | date | Last game date |
| Has Referee | `has_referee` | boolean | Ref'd or self-ref'd |
| Players per Side | `players_per_side` | int | e.g., 7 for 7v7. Extracted from NvN patterns. |
| Venue | `venue_name` | text | Where games are played. FK via `venue_id` to `venues` table. |
| Skill Level | `competition_level` | text | Recreational, Intermediate, Competitive |
| Gender Eligibility | `gender_eligibility` | text | Mens, Womens, CoEd, Other |

**Also stored but system-managed (not extracted):**
- `league_id` (UUID PK)
- `organization_id` (UUID FK, not yet fully implemented)
- `url_scraped` (text, source URL)
- `base_domain` (text, normalized domain)
- `sport_season_code` (char(3), derived from `sport_name` + `season_name` via SSS codes)
- `city` (text, extracted from URL patterns)

**Current dedup model** uses 8 of these fields: `organization_name`, `sport_season_code`, `season_year`, `venue_name`, `day_of_week`, `competition_level`, `gender_eligibility`, `num_weeks`. See `src/utils/league_id_generator.py:check_duplicate_league()`.

**Completeness tracking:** `identifying_fields_pct` measures % of identifier fields filled. Thresholds in `yaml_extractor.py:_get_completeness_status()`:
- COMPLETE: >= 80%
- ACCEPTABLE: >= 60%
- PARTIAL: >= 30%
- FAILED: < 30%

**Expectation:** For most orgs, nearly all identifier fields should be extractable. Exceptions:
- Single-league orgs may not specify skill level or gender (only one option)
- `players_per_side` only available if site uses NvN format strings
- `has_referee` sometimes not stated explicitly

---

## Tier 2: Structured Data

Quantitative/categorical data that enriches the league record but does NOT define its identity. These are "nice to have" — coverage will be spottier than Tier 1.

| Field | DB Column | Type | Notes |
|-------|-----------|------|-------|
| Team Fee | `team_fee` | numeric(10,2) | Per-team cost |
| Individual Fee | `individual_fee` | numeric(10,2) | Per-player cost |
| # Teams | `num_teams` | int | Count from standings/schedule |
| Team Capacity | — | **NEW** | Max roster size per team |
| Slots Left | `slots_left` | int | Open spots remaining |
| T-Shirts Included | — | **NEW** | boolean |
| Game Duration | `time_played_per_week` | interval | e.g., 60 min |
| Time Window | `start_time` | time | Earliest start time. **Consider:** adding `end_time` for full window (e.g., 7-11pm) |
| Registration Deadline | `registration_deadline` | date | |
| Stat Holidays | `stat_holidays` | jsonb | Dates with no games |
| Listing Type | `listing_type` | text | league, drop_in, unknown |

**New columns needed:**
- `team_capacity` (int) — max players per roster
- `tshirts_included` (boolean) — whether league provides jerseys/pinnies
- `end_time` (time) — latest game end time, to capture the "7-11pm" window

**Currently in schema but arguably Tier 2:**
- `start_time` — currently counted as an identifier field. User's model puts the time window in Tier 2. Decide whether to keep it in dedup or move it.
- `requires_insurance`, `insurance_policy_link` — currently in schema as structured fields. Could stay here or move to Tier 3 (unstructured). User seems to prefer Tier 3.

---

## Tier 3: Unstructured Data (Vector Store)

Free-text content from league websites that doesn't fit structured columns. Stored in `league_vectors` (pgvector) for semantic search/RAG.

**Target content types:**
- Awards and prizes
- Rules and regulations
- Insurance and waiver policies
- Code of conduct
- Skill level descriptions (what "Intermediate" means for this org)
- Registration instructions
- Refund policies
- Equipment requirements
- Age restrictions / eligibility details
- FAQ content
- Any other qualitative text from the website

**Current state:** `league_vectors` table exists with schema:
- `id` (UUID PK)
- `league_id` (UUID FK to leagues_metadata, CASCADE delete)
- `url_scraped` (text)
- `page_type` (text) — e.g., "rules", "registration", "about"
- `content` (text) — chunked document text
- `embedding` (vector(1536)) — OpenAI text-embedding-3-small
- `metadata` (jsonb) — flexible metadata

**What's missing:** The current extraction pipeline (`yaml_extractor.py`) only extracts structured fields. There is no pipeline to:
1. Identify unstructured content sections on scraped pages
2. Chunk the text appropriately
3. Generate embeddings
4. Store in `league_vectors` linked to the correct `league_id`

**The page content IS already captured** in two places:
- `scrapes/{domain}/` — cached YAML accessibility trees + metadata JSON
- `page_snapshots` table — YAML/HTML content stored in DB

So the raw material exists; it just needs a chunking + embedding pipeline.

---

## Current Schema → Three-Tier Mapping

### Fields that stay as-is
| Current Column | Tier | Status |
|---------------|------|--------|
| `organization_name` | 1 | OK |
| `sport_name` | 1 | OK |
| `season_name` | 1 | OK |
| `season_year` | 1 | OK (derived) |
| `day_of_week` | 1 | OK |
| `num_weeks` | 1 | OK |
| `season_start_date` | 1 | OK |
| `season_end_date` | 1 | OK |
| `has_referee` | 1 | OK |
| `players_per_side` | 1 | OK |
| `venue_name` | 1 | OK |
| `competition_level` | 1 | OK |
| `gender_eligibility` | 1 | OK |
| `team_fee` | 2 | OK |
| `individual_fee` | 2 | OK |
| `num_teams` | 2 | OK |
| `slots_left` | 2 | OK |
| `time_played_per_week` | 2 | OK |
| `start_time` | 2 | OK (move from identifier to structured) |
| `registration_deadline` | 2 | OK |
| `stat_holidays` | 2 | OK |
| `listing_type` | 2 | OK |

### New columns to add
| Column | Tier | Type | Migration needed |
|--------|------|------|-----------------|
| `team_capacity` | 2 | int | ALTER TABLE ADD |
| `tshirts_included` | 2 | boolean | ALTER TABLE ADD |
| `end_time` | 2 | time | ALTER TABLE ADD |

### Fields to move to Tier 3 (vector store)
| Current Column | Recommendation |
|---------------|---------------|
| `requires_insurance` | Move to unstructured — extract full insurance text instead |
| `insurance_policy_link` | Move to unstructured — store as metadata on vector chunk |

### System/meta columns (no tier, stay on table)
`league_id`, `organization_id`, `url_id`, `url_scraped`, `base_domain`, `sport_season_code`, `city`, `venue_id`, `quality_score`, `identifying_fields_pct`, `completeness_status`, `page_has_multi_leagues`, `pages_scraped`, `is_archived`, `manual_review_flag`, `created_at`, `updated_at`

---

## Implementation Tasks

### 1. Schema changes (DB migration)

```sql
-- Add new Tier 2 columns
ALTER TABLE leagues_metadata
  ADD COLUMN IF NOT EXISTS team_capacity INTEGER,
  ADD COLUMN IF NOT EXISTS tshirts_included BOOLEAN,
  ADD COLUMN IF NOT EXISTS end_time TIME;
```

Decision needed: whether to drop `requires_insurance` and `insurance_policy_link` now or keep them as deprecated until the Tier 3 pipeline is built.

### 2. Update extraction prompt (`yaml_extractor.py`)

The LLM extraction prompt in `_build_yaml_extraction_prompt()` defines what fields get extracted. It needs:
- Add `team_capacity`, `tshirts_included`, `end_time` to the OUTPUT SCHEMA
- Provide extraction guidance for each new field
- Optionally: add instructions to extract unstructured text blocks separately

### 3. Update quality scoring (`validators.py`)

`calculate_quality_score()` currently penalizes missing fields equally. Restructure to:
- **Tier 1 fields missing:** Higher penalty (these should almost always be available)
- **Tier 2 fields missing:** Lower penalty (expected to be spottier)
- Update `identifying_fields_pct` calculation in `yaml_extractor.py:_calculate_identifying_completeness()` to use exactly the Tier 1 field list

### 4. Update dedup logic (`league_id_generator.py`)

Current 8-field identity model should be reviewed against the Tier 1 list. Current fields:
1. `organization_name` — Tier 1
2. `sport_season_code` — Tier 1 (derived)
3. `season_year` — Tier 1 (derived)
4. `venue_name` — Tier 1
5. `day_of_week` — Tier 1
6. `competition_level` — Tier 1
7. `gender_eligibility` — Tier 1
8. `num_weeks` — Tier 1

Consider adding `players_per_side` to dedup — a 7v7 Monday soccer league is different from an 11v11 Monday soccer league at the same venue.

Consider whether `has_referee` should factor into dedup (probably not — same league could change ref policy).

### 5. Update writer (`writer.py`)

- `_prepare_for_insert()` needs to handle new columns
- `VALID_FIELDS` list needs the new column names
- Field merge logic in `_merge_league_records()` should treat Tier 1 and Tier 2 fields the same (fill nulls from supplement)

### 6. Build Tier 3 pipeline (new)

This is the biggest new piece. Needs:
1. **Content classifier** — given a page's YAML/text, identify sections that are "unstructured" (rules, policies, FAQ, etc.) vs structured (schedule tables, registration forms)
2. **Chunker** — split identified sections into reasonable chunks (500-1000 tokens)
3. **Embedder** — generate embeddings via OpenAI `text-embedding-3-small`
4. **Writer** — store chunks in `league_vectors` with:
   - `league_id` FK (link to the league this content belongs to)
   - `page_type` label (rules, insurance, faq, etc.)
   - `content` (the chunk text)
   - `embedding` (1536-dim vector)
   - `metadata` (source URL, section heading, chunk index, etc.)
5. **Integration** — hook into the existing extraction pipeline so Tier 3 runs after Tier 1+2 extraction

### 7. Update DATABASE_SCHEMA.md

Restructure to reflect the three-tier model. Add the tier labels to each field section.

### 8. Update CLAUDE.md

Add the three-tier data model to the project CLAUDE.md so all agents understand the mental model.

---

## Files That Will Need Changes

| File | Change |
|------|--------|
| `migrations/010_*.sql` | New columns |
| `src/extractors/yaml_extractor.py` | Extraction prompt, completeness calc |
| `src/database/validators.py` | Quality score tiers |
| `src/database/writer.py` | New fields in VALID_FIELDS, prepare_for_insert |
| `src/utils/league_id_generator.py` | Review dedup fields |
| `docs/DATABASE_SCHEMA.md` | Restructure around tiers |
| `CLAUDE.md` | Add tier model summary |
| New: `src/extractors/unstructured_extractor.py` | Tier 3 chunking + embedding pipeline |
| New: `src/database/vector_writer.py` or extend `vector_store.py` | Tier 3 storage |

---

## Open Decisions for Implementer

1. **`start_time` in dedup?** Currently an identifier field. User's model puts time window in Tier 2. Removing from dedup means two leagues at the same venue/day/sport but different times would be treated as duplicates. This is probably correct (most orgs only run one league per day/venue/sport), but confirm.

2. **`insurance` columns:** Drop now or keep until Tier 3 pipeline exists? Safer to keep and deprecate.

3. **`players_per_side` in dedup?** Strong case for yes — 7v7 and 11v11 soccer on the same day are different leagues. But adds a 9th dedup field.

4. **Tier 3 scope:** Build the full chunking/embedding pipeline now, or just add the new Tier 2 columns first and defer Tier 3?

5. **Quality score rebalance:** What weights for Tier 1 vs Tier 2 missing fields? Suggestion: Tier 1 missing = -8 each, Tier 2 missing = -3 each.
