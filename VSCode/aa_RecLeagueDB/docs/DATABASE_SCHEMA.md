# RecSportsDB — Database Schema

**Last Updated:** 2026-03-02
**Related context:** [CLAUDE_MANAGE.md](agents/CLAUDE_MANAGE.md)

---

## leagues_metadata (Structured Data — SQL)

### Identifiers
* `league_id` (UUID, PK)
* `organization_id` (UUID, FK to organizations)
* `url_id` (UUID, FK to urls)
* `organization_name` (text)
* `url_scraped` (text)

### Sport/Season Classification
* `sport_season_code` (char(3), SSS format — see [SSS_CODES.md](SSS_CODES.md))
* `season_year` (int, derived from dates)
* `season_start_date` (date)
* `season_end_date` (date)

### Scheduling
* `day_of_week` (enum: Monday–Sunday)
* `start_time` (time)
* `num_weeks` (int)
* `time_played_per_week` (interval)
* `stat_holidays` (jsonb)

### Venue
* `venue_name` (text)

### Competition
* `competition_level` (text, e.g., Rec/Int/Comp)
* `gender_eligibility` (enum: Mens, Womens, CoEd, Other, Unsure)

### Pricing
* `team_fee` (decimal)
* `individual_fee` (decimal)
* `registration_deadline` (date)

### Capacity
* `num_teams` (int)
* `slots_left` (int)

### Policies
* `has_referee` (boolean)
* `requires_insurance` (boolean)
* `insurance_policy_link` (text)

### Quality Tracking
* `quality_score` (int, 0–100, calculated)
* `created_at`, `updated_at` (timestamps)
* `is_archived` (boolean)

---

## organizations (Structured Data — SQL)

* `organization_id` (UUID, PK)
* `organization_name` (text, canonical)
* `alternate_names` (text[])
* `website_urls` (text[])
* `contact_info` (jsonb)
* `founded_date` (date)
* `created_at`, `updated_at` (timestamps)

---

## venues (Structured Data — SQL)

* `venue_id` (UUID, PK)
* `venue_name` (text)
* `address` (text)
* `geocode` (geography)
* `created_at`, `updated_at` (timestamps)

---

## organization_venue_relationships (Structured Data — SQL)

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

## league_vectors (Unstructured Data — pgvector)

* `id` (UUID, PK)
* `league_id` (UUID, FK to leagues_metadata)
* `content` (text, chunked document)
* `embedding` (vector(1536), OpenAI text-embedding-3-small)
* `metadata` (jsonb)
* `created_at` (timestamp)

**What gets vectorized:** rulebooks, safety waivers, skill level descriptions, policy documents, qualitative website text.

---

## UUID Model

**A unique league is defined by:**
1. `organization_name`
2. `sport_season_code`
3. `season_year` (derived from max(season_start_date, season_end_date))
4. `venue_name`
5. `day_of_week`
6. `competition_level`
7. `gender_eligibility`
8. `num_weeks`

**If all 8 match → duplicate.** Keep highest `quality_score`; if tied, keep most recently scraped. Archive the other.

**ID Architecture:**

- `league_id` — one specific league offering (e.g., "TSSC Monday Night Soccer — Fall 2024 — Rec")
- `organization_id` — all leagues from the same org share this
- `url_id` — normalized URL identifier (one url → many league_ids)
- `venue_id` — **DEFERRED**, currently using `venue_name` text field
- `league_season_id` — **DEFERRED**, for year-over-year analysis

---

## search_queries (URL Discovery — SQL)

Tracks each Google search executed via Serper API.

* `query_id` (UUID, PK)
* `query_text` (text) — full query string, e.g. "Toronto adult rec soccer league"
* `city`, `sport`, `season`, `year` (text/int)
* `query_fingerprint` (text, auto-generated) — lowercase `city|state|country|sport|season|year` for dedup
* `status` (enum: PENDING/IN_PROGRESS/COMPLETED/FAILED)
* `total_results`, `valid_results` (int)
* `created_at`, `updated_at` (timestamps)

---

## search_results (URL Discovery — SQL)

All URLs returned from Google searches (both passed and failed validation).

* `result_id` (UUID, PK)
* `query_id` (UUID, FK to search_queries)
* `url_raw` (text) — raw URL from search result
* `url_canonical` (text, auto-normalized) — UTM stripped, www removed, https, lowercase
* `page_title`, `page_snippet` (text)
* `search_rank` (int)
* `city`, `sport` (text — denormalized from query)
* `validation_status` (enum: PENDING/PASSED/FAILED)
* `validation_reason` (text) — e.g. `valid_adult_rec_league`, `social_media`, `youth_organization`
* `priority` (int 1–3, nullable — set only for PASSED results)
* `added_to_scrape_queue` (boolean)
* `created_at` (timestamp)

---

## scrape_queue (Scraping — SQL)

Only validated URLs ready to scrape. Populated from `search_results` (PASSED only).

* `scrape_id` (UUID, PK)
* `url` (text, canonical)
* `priority` (int: 1=high, 2=medium, 3=low)
* `status` (enum: PENDING/IN_PROGRESS/COMPLETED/FAILED/SKIPPED)
* `created_at`, `updated_at` (timestamps)

**Dedup:** URLs already in queue or already in `leagues_metadata` are not re-added.

---

## Migrations

SQL migration files in `migrations/`:
- `create_leagues_metadata.sql` — initial schema
- `001_add_completeness_tracking.sql` — quality score fields
