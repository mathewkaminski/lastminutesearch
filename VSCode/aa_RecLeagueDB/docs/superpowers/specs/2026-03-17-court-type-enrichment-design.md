# Court Type Enrichment — Design Spec

**Date:** 2026-03-17
**Status:** Approved

---

## Problem

The `venues` table has lat/lng and Google Places data but no classification of what kind of venue it is. For the upcoming map and analytics features, we need to know whether a venue is an indoor gym, a beach, an ice rink, etc. We also need a filtered view of enriched venues showing which leagues operate there and key pricing/scheduling data.

---

## Goals

1. Classify each enriched venue into a **broad type** (Indoor / Outdoor / Beach / Ice / Pool / Unknown) and a **specific type** (Gym/Rec Centre / Turf Field / Grass Field / Beach / Ice Rink / Tennis-Pickleball / Baseball Diamond / Swimming Pool / Other), each with a confidence score (0–100).
2. Add an **Enriched Venues tab** to the Venues Enricher page with filters (court type, province, city, sport) and per-venue league stats (# leagues, sports, avg fees, hours).

---

## Out of Scope

- Map rendering (separate feature)
- Re-classifying already-classified venues (manual override out of scope for now)
- Storing Google Places `types` as a separate column

---

## Data Model

### Migration 015 — `venues` table additions

```sql
ALTER TABLE public.venues
    ADD COLUMN IF NOT EXISTS court_type_broad      TEXT,
    ADD COLUMN IF NOT EXISTS court_type_broad_conf  INT CHECK (court_type_broad_conf BETWEEN 0 AND 100),
    ADD COLUMN IF NOT EXISTS court_type_specific    TEXT,
    ADD COLUMN IF NOT EXISTS court_type_specific_conf INT CHECK (court_type_specific_conf BETWEEN 0 AND 100);
```

### Enums (enforced in application code, not DB)

- **Broad:** `Indoor`, `Outdoor`, `Beach`, `Ice`, `Pool`, `Unknown`
- **Specific:** `Gym/Rec Centre`, `Turf Field`, `Grass Field`, `Beach`, `Ice Rink`, `Tennis-Pickleball`, `Baseball Diamond`, `Swimming Pool`, `Other`

---

## Components

### `src/enrichers/court_type_classifier.py`

Single responsibility: call Haiku and return a classification result.

```
CourtTypeClassifier(client: anthropic.Anthropic)
  .classify(venue_name, google_name, address) -> dict
      returns: {broad, broad_conf, specific, specific_conf}
```

- Uses `claude-haiku-4-5-20251001`
- Single API call per venue; prompt asks for JSON with both levels + confidence
- Raises `CourtTypeError` on API failure or unparseable response
- Validates returned values against the allowed enums; falls back to `Unknown`/`Other` if invalid

### `src/enrichers/court_type_enricher.py`

Orchestrates classification over unclassified venues.

```
CourtTypeEnricher(classifier: CourtTypeClassifier, venue_store: VenueStore)
  .run(progress_callback=None) -> {classified: int, failed: int}
```

- Calls `venue_store.get_venues_for_classification()` (enriched venues with null `court_type_broad`)
- For each: calls classifier, saves via `venue_store.save_court_type()`
- Errors per venue are caught and counted as `failed`; does not abort the run

### `VenueStore` additions

| Method | Purpose |
|---|---|
| `get_venues_for_classification()` | Venues with lat/lng but null `court_type_broad` |
| `save_court_type(venue_id, broad, broad_conf, specific, specific_conf)` | Write classification result |
| `get_enriched_venues(broad, specific, province, city, sport)` | Filtered enriched venues for tab |
| `get_league_stats_for_venues(venue_ids)` | Aggregate league data from `leagues_metadata` per venue |

**`get_league_stats_for_venues` aggregates:**
- `num_leagues` (count)
- `avg_team_fee`, `avg_individual_fee` (float, nullable)
- `hours` (sorted list of distinct `start_time` values)

`sports` and `days_of_week` are already on the venue row (populated by `link_leagues()`), so they are not re-aggregated here.

### `venues_enricher.py` — UI restructure

Two `st.tabs()`: **All Venues** (current behaviour) and **Enriched Venues** (new).

**Enriched Venues tab layout:**
1. Action row: "Classify Court Types" button + progress bar (shown only when unclassified enriched venues exist); stats label showing `X of Y classified`
2. Filter row: `court_type_broad` (selectbox), `court_type_specific` (selectbox), `province` (selectbox), city (text_input), sport (selectbox) — all populated from returned data; empty = no filter
3. `st.data_editor` table: Google Name (editable), Address, Province, Broad Type, Broad Conf, Specific Type, Specific Conf, # Leagues, Avg Team Fee, Avg Indiv. Fee, Hours — all others read-only
4. "Save Name Changes" button (same pattern as All Venues tab)

---

## Data Flow

```
[Classify button clicked]
  → get_venues_for_classification()        # VenueStore
  → for each venue:
      CourtTypeClassifier.classify(...)    # Haiku call
      save_court_type(...)                 # VenueStore

[Enriched Venues tab loaded]
  → get_enriched_venues(filters)           # VenueStore
  → get_league_stats_for_venues(ids)       # VenueStore
  → merge + render st.data_editor
```

---

## Error Handling

- Haiku API failure per venue → logged, counted as `failed`, run continues
- Invalid enum in Haiku response → fallback to `Unknown`/`Other` with conf=0
- Empty `venue_ids` list → `get_league_stats_for_venues` returns `{}` immediately

---

## Testing

- `test_court_type_classifier.py` — mock Anthropic client; test happy path, API error, invalid enum fallback
- `test_court_type_enricher.py` — mock classifier + store; test run summary, error counting, progress callback
- `test_venue_store.py` — add tests for the four new methods; fix outdated `test_save_venue_inserts_and_returns_id` (uses old upsert interface)
