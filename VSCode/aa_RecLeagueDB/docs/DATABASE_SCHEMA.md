# RecSportsDB — Database Schema

**Last Updated:** 2026-03-14
**Related context:** [CLAUDE_MANAGE.md](agents/CLAUDE_MANAGE.md)

---

## Three-Tier Data Model

League data is organized into three tiers:

- **Tier 1 — Identifiers:** Define what makes a league unique. Nearly always extractable.
- **Tier 2 — Structured Data:** Enrichment fields. Coverage will be spottier.
- **Tier 3 — Unstructured Data:** Free-text content stored as vectors for semantic search.

---

## leagues_metadata (Tiers 1 & 2 — SQL)

### System/Meta (no tier)
* `league_id` (UUID, PK)
* `organization_id` (UUID, FK to organizations)
* `url_id` (UUID, FK to urls)
* `url_scraped` (text)
* `base_domain` (text, normalized domain)
* `sport_season_code` (char(3), SSS format — see [SSS_CODES.md](SSS_CODES.md))
* `city` (text, extracted from URL patterns)
* `quality_score` (int, 0–100, calculated)
* `identifying_fields_pct` (float, % of Tier 1 fields filled)
* `completeness_status` (text: COMPLETE/ACCEPTABLE/PARTIAL/FAILED)
* `page_has_multi_leagues` (boolean)
* `pages_scraped` (text[])
* `manual_review_flag` (text)
* `is_archived` (boolean)
* `listing_type` (text: league/drop_in/unknown)
* `created_at`, `updated_at` (timestamps)

### Tier 1 — Identifiers

| Field | Column | Type | Notes |
|-------|--------|------|-------|
| Organization | `organization_name` | text | Required |
| Sport | `sport_name` | text | Required |
| Season | `season_name` | text | Required |
| Season Year | `season_year` | int | Derived from dates |
| Day of Week | `day_of_week` | text | Monday–Sunday |
| # Weeks | `num_weeks` | int | Season length |
| Start Date | `season_start_date` | date | First game |
| End Date | `season_end_date` | date | Last game |
| Has Referee | `has_referee` | boolean | |
| Players per Side | `players_per_side` | int | From NvN patterns |
| Venue | `venue_name` | text | FK via venue_id (deferred) |
| Skill Level (raw) | `source_comp_level` | text | Raw label from page |
| Skill Level (std) | `standardized_comp_level` | varchar(1) | A/B/C/D single letter |
| Gender | `gender_eligibility` | text | Mens/Womens/CoEd/Other |

### Tier 2 — Structured Data

| Field | Column | Type | Notes |
|-------|--------|------|-------|
| Team Fee | `team_fee` | numeric(10,2) | |
| Individual Fee | `individual_fee` | numeric(10,2) | |
| # Teams | `num_teams` | int | |
| Team Capacity | `team_capacity` | int | Max roster size (NEW) |
| Slots Left | `slots_left` | int | |
| T-Shirts Included | `tshirts_included` | boolean | (NEW) |
| Game Duration | `time_played_per_week` | interval | e.g. 60 min |
| Start Time | `start_time` | time | Earliest game start |
| End Time | `end_time` | time | Latest game end (NEW) |
| Registration Deadline | `registration_deadline` | date | |
| Stat Holidays | `stat_holidays` | jsonb | [{date, reason}] |
| Listing Type | `listing_type` | text | league/drop_in/unknown |

### Tier 2 — Deprecated (kept until Tier 3 pipeline)

* `requires_insurance` (boolean)
* `insurance_policy_link` (text)

---

## Dedup Model (9-field uniqueness)

A unique league is defined by:
1. `organization_name` (normalized)
2. `sport_name` (plain text)
3. `season_year` (derived from dates)
4. `venue_name` (normalized)
5. `day_of_week`
6. `source_comp_level` (raw label from page)
7. `gender_eligibility`
8. `num_weeks`
9. `players_per_side`

Matching uses fuzzy comparison: None/empty = wildcard. Both sides need >= 3 non-empty matching fields.

**If all non-empty fields match → duplicate.** Merge records, keep highest quality_score.

---

## Quality Score Bands

`quality_score` (0–100) calculated by `src/database/validators.calculate_quality_score()`.

**Penalty weights:**
- Required field missing: -20
- Tier 1 field missing: -8
- Tier 2 field missing: -3
- Both fees missing: -8
- Invalid values: -10
- Suspicious data: -15
- Staleness (>1yr): -20, (>2yr): -30

| Band | Range | Constant | Behavior |
|------|-------|----------|----------|
| Thin | 0–59 | `AUTO_REPLACE_THRESHOLD = 60` | Auto-archives on contradiction |
| Borderline | 60–74 | `DEEP_SCRAPE_THRESHOLD = 75` | Super scrape; contradictions flagged |
| Acceptable | 75–89 | — | Team count verify only |
| Substantial | 90+ | — | Team count verify only |

---

## league_vectors (Tier 3 — pgvector)

* `id` (UUID, PK)
* `league_id` (UUID, FK to leagues_metadata, CASCADE)
* `url_scraped` (text)
* `page_type` (text — rules, registration, about, etc.)
* `content` (text, chunked document)
* `embedding` (vector(1536), OpenAI text-embedding-3-small)
* `metadata` (jsonb)
* `created_at` (timestamp)

**Target content:** Awards, rules, insurance/waivers, code of conduct, skill level descriptions, FAQ, refund policies, equipment requirements, eligibility details.

**Status:** Table exists. Chunking/embedding pipeline not yet built (deferred).

---

## organizations (SQL)

* `organization_id` (UUID, PK)
* `organization_name` (text, canonical)
* `alternate_names` (text[])
* `website_urls` (text[])
* `contact_info` (jsonb)
* `founded_date` (date)
* `created_at`, `updated_at` (timestamps)

---

## venues (SQL)

* `venue_id` (UUID, PK)
* `venue_name` (text)
* `address` (text)
* `geocode` (geography)
* `created_at`, `updated_at` (timestamps)

---

## organization_venue_relationships (SQL)

* `id` (UUID, PK)
* `organization_id` (UUID, FK)
* `venue_id` (UUID, FK)
* `contact_info` (jsonb)
* `cost_structure` (jsonb)
* `availability` (jsonb)
* `date_limitations` (jsonb)
* `created_at`, `updated_at` (timestamps)
* Unique constraint on (organization_id, venue_id)

---

## search_queries (URL Discovery — SQL)

* `query_id` (UUID, PK)
* `query_text` (text)
* `city`, `sport`, `season`, `year` (text/int)
* `query_fingerprint` (text, auto-generated)
* `status` (enum: PENDING/IN_PROGRESS/COMPLETED/FAILED)
* `total_results`, `valid_results` (int)
* `created_at`, `updated_at` (timestamps)

---

## search_results (URL Discovery — SQL)

* `result_id` (UUID, PK)
* `query_id` (UUID, FK)
* `url_raw` (text)
* `url_canonical` (text, normalized)
* `page_title`, `page_snippet` (text)
* `search_rank` (int)
* `city`, `sport` (text)
* `validation_status` (enum: PENDING/PASSED/FAILED)
* `validation_reason` (text)
* `priority` (int 1–3, nullable)
* `added_to_scrape_queue` (boolean)
* `created_at` (timestamp)

---

## scrape_queue (Scraping — SQL)

* `scrape_id` (UUID, PK)
* `url` (text, canonical)
* `priority` (int: 1=high, 2=medium, 3=low)
* `status` (enum: PENDING/IN_PROGRESS/COMPLETED/FAILED/SKIPPED)
* `created_at`, `updated_at` (timestamps)

---

## ID Architecture

- `league_id` — one specific league offering
- `organization_id` — all leagues from same org
- `url_id` — normalized URL identifier (one url → many league_ids)
- `venue_id` — **DEFERRED**, using `venue_name` text field
- `league_season_id` — **DEFERRED**, for year-over-year analysis

---

## Migrations

SQL files in `migrations/`:
- `create_leagues_metadata.sql` — initial schema
- `001_add_completeness_tracking.sql` — quality score fields
- `006_add_sport_season_name.sql` — sport_name, season_name columns
- `010_three_tier_columns.sql` — team_capacity, tshirts_included, end_time
