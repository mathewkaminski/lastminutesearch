# Venue Enricher — Design Document

**Date:** 2026-03-01
**Status:** Approved, ready for implementation planning
**Related context:** [CLAUDE_MANAGE.md](../agents/CLAUDE_MANAGE.md)

---

## Problem

`leagues_metadata` stores `venue_name` as a free-text field extracted from league pages (e.g., "Ashbridges Bay Park"). There is no structured address, geocode, or canonical venue record. This blocks any venue-level analytics (utilization, capacity planning, geographic clustering).

---

## Solution

A venue enrichment pipeline that:
1. Reads distinct `(venue_name, city)` pairs from `leagues_metadata`
2. Resolves each to a structured address + lat/lng via the Google Places API
3. Saves results to a new `venues` table
4. Links back to `leagues_metadata` via `venue_id`
5. Routes low-confidence lookups to a human review queue in Streamlit

---

## Architecture

### Two phases per run

**Phase 1 — Collect & Lookup**
- Query all distinct `(venue_name, city)` pairs in `leagues_metadata` where `venue_id IS NULL` and `city IS NOT NULL`
- Deduplicate: one Places API call per unique pair (not per league record)
- For each pair: call Places API text search → parse result → calculate confidence score
- `confidence_score ≥ 75`: auto-save to `venues` table, bulk-update `leagues_metadata.venue_id`
- `confidence_score < 75`: save to `venues` table with `manually_verified = FALSE`, surface in review queue
- `confidence_score = 0` (no result): log to failures list, skip

**Phase 2 — Review Queue**
- Streamlit page shows all venues with `confidence_score < 75` and `manually_verified = FALSE`
- Human reviews each: Accept / Edit / Skip
- Accept sets `manually_verified = TRUE` and links leagues
- Edit corrects address then saves and links leagues
- Skip leaves in queue for later

---

## Database Schema

### New table: `venues`

```sql
CREATE TABLE public.venues (
    venue_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_name        TEXT NOT NULL,
    city              TEXT,
    address           TEXT,
    lat               DECIMAL(10,7),
    lng               DECIMAL(10,7),
    google_place_id   TEXT UNIQUE,
    confidence_score  INT CHECK (confidence_score BETWEEN 0 AND 100),
    manually_verified BOOLEAN DEFAULT FALSE,
    raw_api_response  JSONB,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX ON venues (LOWER(venue_name), LOWER(city));
```

### Additions to `leagues_metadata`

```sql
ALTER TABLE leagues_metadata
    ADD COLUMN IF NOT EXISTS venue_id UUID REFERENCES venues(venue_id),
    ADD COLUMN IF NOT EXISTS city TEXT;
```

### One-time city backfill

```sql
UPDATE leagues_metadata lm
SET city = sq.city
FROM scrape_queue sc
JOIN search_results sr ON sc.source_result_id = sr.result_id
JOIN search_queries sq  ON sr.query_id = sq.query_id
WHERE lm.url_scraped = sc.url
  AND lm.city IS NULL;
```

Records that can't be backfilled (e.g. scraped via MCP agent outside search pipeline) will have `city = NULL` and are skipped by the enricher. The UI surfaces a count of these.

### Going forward

Extraction pipeline must write `city` to `leagues_metadata` when saving a new league. City is available at scrape time from the `scrape_queue` record (via `source_result_id → search_results → search_queries.city`).

---

## Confidence Scoring (0–100)

| Component | Max Points | Logic |
|-----------|-----------|-------|
| Name match | 40 | Fuzzy ratio: searched `venue_name` vs Places API `name` |
| City match | 30 | `formatted_address` contains searched city string |
| Place type | 20 | Types include: `park`, `stadium`, `sports_complex`, `gym`, `establishment` |
| Result quality | 10 | Result exists and `user_ratings_total > 0` |

**Thresholds:**
- `≥ 75` → auto-save, link to leagues
- `< 75` → save, queue for human review
- `= 0` (no result) → log failure, skip entirely

**Duplicate `google_place_id`:** two venue names resolved to same place → keep first, log collision.

---

## Streamlit Page: `venues_enricher.py`

### Top panel — Stats & Trigger

Metrics row:
- Total unique (venue_name, city) pairs
- Already enriched
- Pending lookup
- Needs review (confidence < 75, not yet verified)

"Run Enrichment" button: processes all pending pairs, shows progress bar. Post-run summary: X auto-saved, Y queued for review.

### Bottom panel — Review Queue

Paginated table of `venues` where `confidence_score < 75` and `manually_verified = FALSE`.

Expand any row to see:
- Searched: `"Ashbridges Bay Park, Toronto"`
- Returned: address, place type, Google Maps link
- Confidence breakdown by component
- Actions: **Accept** / **Edit** (text field) / **Skip**

---

## Error Handling

| Error | Behaviour |
|-------|-----------|
| No Places API result | Log to failures list, skip (don't queue) |
| API rate limit / 429 | Exponential backoff, 3 retries, then fail gracefully — resume from last position on next run |
| `city IS NULL` for record | Skip enrichment, count surfaced in UI as "missing city — cannot enrich" |
| Duplicate `google_place_id` | Keep first record, log collision for manual review |

---

## New Environment Variable

```bash
GOOGLE_PLACES_API_KEY=   # Google Cloud Console → Places API
```

---

## Files to Create

```
migrations/
    002_add_venues_table.sql          # venues table + leagues_metadata.venue_id + city
src/
    database/
        venue_store.py                # Venues table read/write operations
    enrichers/
        venue_enricher.py             # Core enrichment logic: lookup, score, save
        places_client.py              # Google Places API wrapper
streamlit_app/pages/
    venues_enricher.py                # Streamlit UI: trigger + review queue
```

`app.py` navigation updated to add "📍 Venues Enricher" under Data Management.

---

## Out of Scope

- Venues table normalization into `organization_venue_relationships` (Parking Lot)
- Venue capacity / availability data (Parking Lot)
- Geocoding via anything other than Google Places API
- Scraping the league URL pages for address hints (venue_name from leagues_metadata is sufficient seed)
