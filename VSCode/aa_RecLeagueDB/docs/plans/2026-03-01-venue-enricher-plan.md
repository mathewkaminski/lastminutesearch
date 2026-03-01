# Venue Enricher Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a pipeline that resolves `venue_name` values from `leagues_metadata` into structured addresses via the Google Places API, saves them to a new `venues` table, and provides a Streamlit review UI for low-confidence lookups.

**Architecture:** `VenueEnricher` orchestrates the pipeline — it reads distinct `(venue_name, city)` pairs from `leagues_metadata`, calls `PlacesClient` for each, scores the result with `confidence_scorer`, writes to `venue_store`, and links back via `leagues_metadata.venue_id`. High-confidence results (≥75) auto-save; low-confidence results queue for human review in `venues_enricher.py`.

**Tech Stack:** Python `requests` (Places API), `difflib.SequenceMatcher` (fuzzy name match), Supabase Python client, Streamlit.

**Design doc:** `docs/plans/2026-03-01-venue-enricher-design.md`

---

## Task 1: SQL Migration

**Files:**
- Create: `migrations/002_add_venues_table.sql`

**Step 1: Write the migration file**

```sql
-- Migration: Add venues table + city/venue_id to leagues_metadata
-- Date: 2026-03-01

-- 1. Create venues table
CREATE TABLE IF NOT EXISTS public.venues (
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

-- Prevent duplicate venue+city entries
CREATE UNIQUE INDEX IF NOT EXISTS idx_venues_name_city
    ON public.venues (LOWER(venue_name), LOWER(city));

-- 2. Add venue_id + city to leagues_metadata
ALTER TABLE public.leagues_metadata
    ADD COLUMN IF NOT EXISTS venue_id UUID REFERENCES public.venues(venue_id),
    ADD COLUMN IF NOT EXISTS city TEXT;

-- 3. One-time backfill: populate city from search pipeline
UPDATE public.leagues_metadata lm
SET city = sq.city
FROM public.scrape_queue sc
JOIN public.search_results sr ON sc.source_result_id = sr.result_id
JOIN public.search_queries sq  ON sr.query_id = sq.query_id
WHERE lm.url_scraped = sc.url
  AND lm.city IS NULL;

-- 4. Indexes
CREATE INDEX IF NOT EXISTS idx_leagues_city    ON public.leagues_metadata(city);
CREATE INDEX IF NOT EXISTS idx_leagues_venue_id ON public.leagues_metadata(venue_id);
CREATE INDEX IF NOT EXISTS idx_venues_place_id  ON public.venues(google_place_id);
```

**Step 2: Run in Supabase SQL editor**

Go to Supabase dashboard → SQL Editor → paste migration → Run.

Expected: no errors. Tables `venues` created, columns `city` and `venue_id` appear on `leagues_metadata`.

**Step 3: Verify**

In Supabase Table Editor, confirm:
- `venues` table exists with all columns
- `leagues_metadata` has new columns `city` (text) and `venue_id` (uuid)
- Some `city` values backfilled from search pipeline (check with `SELECT city, COUNT(*) FROM leagues_metadata GROUP BY city`)

**Step 4: Commit**

```bash
git add migrations/002_add_venues_table.sql
git commit -m "feat: add venues table migration + city/venue_id to leagues_metadata"
```

---

## Task 2: Places API Client

**Files:**
- Create: `src/enrichers/__init__.py`
- Create: `src/enrichers/places_client.py`
- Create: `tests/test_places_client.py`

**Step 1: Write the failing tests**

```python
# tests/test_places_client.py
import pytest
from unittest.mock import patch, MagicMock
from src.enrichers.places_client import PlacesClient, PlacesAPIError


@pytest.fixture
def client():
    return PlacesClient(api_key="test-key")


def _mock_response(results: list, status: str = "OK"):
    mock = MagicMock()
    mock.json.return_value = {"results": results, "status": status}
    mock.raise_for_status.return_value = None
    return mock


SAMPLE_RESULT = {
    "place_id": "ChIJ_abc123",
    "name": "Ashbridges Bay Park",
    "formatted_address": "1561 Lake Shore Blvd E, Toronto, ON M4L 3W6, Canada",
    "geometry": {"location": {"lat": 43.6632, "lng": -79.3070}},
    "types": ["park", "point_of_interest", "establishment"],
    "user_ratings_total": 1234,
}


def test_search_returns_normalized_result(client):
    with patch("src.enrichers.places_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response([SAMPLE_RESULT])
        result = client.search("Ashbridges Bay Park", "Toronto")

    assert result["place_id"] == "ChIJ_abc123"
    assert result["name"] == "Ashbridges Bay Park"
    assert result["formatted_address"] == "1561 Lake Shore Blvd E, Toronto, ON M4L 3W6, Canada"
    assert result["lat"] == pytest.approx(43.6632)
    assert result["lng"] == pytest.approx(-79.3070)
    assert result["types"] == ["park", "point_of_interest", "establishment"]
    assert result["user_ratings_total"] == 1234
    assert "raw" in result


def test_search_returns_none_when_no_results(client):
    with patch("src.enrichers.places_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response([], status="ZERO_RESULTS")
        result = client.search("Nonexistent Venue", "Nowhere")

    assert result is None


def test_search_raises_on_api_error(client):
    with patch("src.enrichers.places_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response([], status="REQUEST_DENIED")
        with pytest.raises(PlacesAPIError):
            client.search("Any Venue", "Any City")


def test_search_query_includes_venue_and_city(client):
    with patch("src.enrichers.places_client.requests.get") as mock_get:
        mock_get.return_value = _mock_response([SAMPLE_RESULT])
        client.search("Ashbridges Bay Park", "Toronto")

    call_kwargs = mock_get.call_args
    assert "Ashbridges Bay Park Toronto" in call_kwargs.kwargs.get(
        "params", {}
    ).get("query", "")
```

**Step 2: Run tests to verify they fail**

```bash
cd /c/Users/mathe/VSCode/aa_RecLeagueDB
pytest tests/test_places_client.py -v
```

Expected: `ImportError: cannot import name 'PlacesClient'`

**Step 3: Create `src/enrichers/__init__.py`**

```python
# src/enrichers/__init__.py
```

**Step 4: Implement `src/enrichers/places_client.py`**

```python
"""Google Places API client for venue address lookup."""

import logging
import time
import requests

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"ZERO_RESULTS", "NOT_FOUND"}
ERROR_STATUSES = {"REQUEST_DENIED", "INVALID_REQUEST", "OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}


class PlacesAPIError(Exception):
    pass


class PlacesClient:
    BASE_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    MAX_RETRIES = 3

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, venue_name: str, city: str) -> dict | None:
        """Search for a venue by name and city.

        Args:
            venue_name: Venue name from leagues_metadata.
            city: City context from search pipeline.

        Returns:
            Normalized result dict, or None if no results found.

        Raises:
            PlacesAPIError: On API-level errors (bad key, quota exceeded).
        """
        query = f"{venue_name} {city}"
        params = {"query": query, "key": self.api_key}

        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.get(self.BASE_URL, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise PlacesAPIError(f"Request failed after {self.MAX_RETRIES} retries: {e}") from e
                wait = 2 ** attempt
                logger.warning(f"Places API request failed (attempt {attempt + 1}), retrying in {wait}s: {e}")
                time.sleep(wait)
                continue

            status = data.get("status")

            if status == "OK":
                return self._normalize(data["results"][0], data)

            if status in TERMINAL_STATUSES:
                logger.debug(f"No results for '{query}': {status}")
                return None

            if status in ERROR_STATUSES:
                raise PlacesAPIError(f"Places API error for '{query}': {status}")

            # Unexpected status — treat as error
            raise PlacesAPIError(f"Unexpected Places API status '{status}' for '{query}'")

        return None  # unreachable but satisfies type checker

    def _normalize(self, result: dict, raw_response: dict) -> dict:
        location = result.get("geometry", {}).get("location", {})
        return {
            "place_id": result.get("place_id"),
            "name": result.get("name"),
            "formatted_address": result.get("formatted_address"),
            "lat": location.get("lat"),
            "lng": location.get("lng"),
            "types": result.get("types", []),
            "user_ratings_total": result.get("user_ratings_total", 0),
            "raw": raw_response,
        }
```

**Step 5: Run tests to verify they pass**

```bash
pytest tests/test_places_client.py -v
```

Expected: 4 passed.

**Step 6: Commit**

```bash
git add src/enrichers/__init__.py src/enrichers/places_client.py tests/test_places_client.py
git commit -m "feat: add Places API client with retry logic"
```

---

## Task 3: Confidence Scorer

**Files:**
- Create: `src/enrichers/confidence_scorer.py`
- Create: `tests/test_confidence_scorer.py`

**Step 1: Write the failing tests**

```python
# tests/test_confidence_scorer.py
from src.enrichers.confidence_scorer import score

GOOD_RESULT = {
    "name": "Ashbridges Bay Park",
    "formatted_address": "1561 Lake Shore Blvd E, Toronto, ON M4L 3W6, Canada",
    "types": ["park", "point_of_interest", "establishment"],
    "user_ratings_total": 500,
}


def test_perfect_match_scores_100():
    s = score("Ashbridges Bay Park", "Toronto", GOOD_RESULT)
    assert s == 100


def test_none_result_scores_zero():
    assert score("Any Venue", "Any City", None) == 0


def test_wrong_city_loses_city_points():
    result = {**GOOD_RESULT, "formatted_address": "123 Main St, Ottawa, ON K1A 0A9, Canada"}
    s = score("Ashbridges Bay Park", "Toronto", result)
    assert s <= 70  # lost 30 city points


def test_no_ratings_loses_quality_points():
    result = {**GOOD_RESULT, "user_ratings_total": 0}
    s = score("Ashbridges Bay Park", "Toronto", result)
    assert s == 90  # lost 10 quality points


def test_non_sports_type_loses_type_points():
    result = {**GOOD_RESULT, "types": ["restaurant", "food"]}
    s = score("Ashbridges Bay Park", "Toronto", result)
    assert s <= 80  # lost type points


def test_partial_name_match_reduces_name_score():
    s = score("Ashbridges Park", "Toronto", GOOD_RESULT)
    # Name is similar but not exact — should score less than 100 but still high
    assert 70 <= s <= 99


def test_score_is_bounded_0_to_100():
    s = score("Completely Wrong Name", "Wrong City", {
        "name": "Something Else",
        "formatted_address": "456 Other St, Different City, AB T1A 0A0, Canada",
        "types": ["restaurant"],
        "user_ratings_total": 0,
    })
    assert 0 <= s <= 100
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_confidence_scorer.py -v
```

Expected: `ImportError: cannot import name 'score'`

**Step 3: Implement `src/enrichers/confidence_scorer.py`**

```python
"""Confidence scoring for Places API venue lookup results."""

import difflib

SPORTS_TYPES = {
    "park", "stadium", "sports_complex", "gym", "health",
    "establishment", "point_of_interest",
}

AUTO_SAVE_THRESHOLD = 75


def score(venue_name: str, city: str, api_result: dict | None) -> int:
    """Calculate confidence score 0-100 for a Places API result.

    Args:
        venue_name: The venue name that was searched.
        city: The city that was searched.
        api_result: Normalized result from PlacesClient.search(), or None.

    Returns:
        Integer confidence score 0-100.
    """
    if api_result is None:
        return 0

    return (
        _name_score(venue_name, api_result.get("name", ""))
        + _city_score(city, api_result.get("formatted_address", ""))
        + _type_score(api_result.get("types", []))
        + _quality_score(api_result.get("user_ratings_total", 0))
    )


def _name_score(searched: str, returned: str) -> int:
    """0-40 points based on fuzzy name match."""
    ratio = difflib.SequenceMatcher(
        None, searched.lower(), returned.lower()
    ).ratio()
    return round(ratio * 40)


def _city_score(city: str, formatted_address: str) -> int:
    """0 or 30 points: city appears in returned address."""
    return 30 if city.lower() in formatted_address.lower() else 0


def _type_score(types: list[str]) -> int:
    """0 or 20 points: result has at least one sports-relevant type."""
    return 20 if any(t in SPORTS_TYPES for t in types) else 0


def _quality_score(user_ratings_total: int) -> int:
    """0 or 10 points: result has at least one user rating."""
    return 10 if user_ratings_total > 0 else 0
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_confidence_scorer.py -v
```

Expected: 7 passed.

**Step 5: Commit**

```bash
git add src/enrichers/confidence_scorer.py tests/test_confidence_scorer.py
git commit -m "feat: add venue confidence scorer"
```

---

## Task 4: Venue Store

**Files:**
- Create: `src/database/venue_store.py`
- Create: `tests/test_venue_store.py`

**Step 1: Write the failing tests**

```python
# tests/test_venue_store.py
import pytest
from unittest.mock import MagicMock, patch
from src.database.venue_store import VenueStore


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def store(mock_client):
    return VenueStore(client=mock_client)


def test_save_venue_inserts_and_returns_id(store, mock_client):
    mock_client.table.return_value.upsert.return_value.execute.return_value.data = [
        {"venue_id": "uuid-123"}
    ]
    venue_id = store.save_venue(
        venue_name="Ashbridges Bay Park",
        city="Toronto",
        address="1561 Lake Shore Blvd E, Toronto, ON",
        lat=43.6632,
        lng=-79.3070,
        google_place_id="ChIJ_abc123",
        confidence_score=95,
        raw_api_response={"results": []},
    )
    assert venue_id == "uuid-123"
    mock_client.table.return_value.upsert.assert_called_once()


def test_link_leagues_updates_matching_rows(store, mock_client):
    mock_client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {}, {}
    ]
    count = store.link_leagues(
        venue_id="uuid-123",
        venue_name="Ashbridges Bay Park",
        city="Toronto",
    )
    assert count == 2


def test_get_review_queue_returns_low_confidence_venues(store, mock_client):
    mock_client.table.return_value.select.return_value.eq.return_value.lt.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"venue_id": "uuid-1", "venue_name": "Vague Venue", "confidence_score": 50}
    ]
    results = store.get_review_queue()
    assert len(results) == 1
    assert results[0]["confidence_score"] == 50


def test_accept_venue_sets_manually_verified(store, mock_client):
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    store.accept_venue("uuid-123")
    update_call = mock_client.table.return_value.update.call_args[0][0]
    assert update_call["manually_verified"] is True


def test_get_unenriched_pairs_returns_distinct_pairs(store, mock_client):
    mock_client.table.return_value.select.return_value.is_.return_value.not_.return_value.is_.return_value.execute.return_value.data = [
        {"venue_name": "Park A", "city": "Toronto"},
        {"venue_name": "Park B", "city": "Ottawa"},
    ]
    pairs = store.get_unenriched_pairs()
    assert len(pairs) == 2
    assert ("Park A", "Toronto") in pairs
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_venue_store.py -v
```

Expected: `ImportError: cannot import name 'VenueStore'`

**Step 3: Implement `src/database/venue_store.py`**

```python
"""Venue table read/write operations."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class VenueStore:
    REVIEW_THRESHOLD = 75

    def __init__(self, client):
        """Args:
            client: Supabase client instance from get_client().
        """
        self.client = client

    def save_venue(
        self,
        venue_name: str,
        city: str,
        address: str | None,
        lat: float | None,
        lng: float | None,
        google_place_id: str | None,
        confidence_score: int,
        raw_api_response: dict,
    ) -> str:
        """Upsert a venue record. Returns venue_id."""
        data = {
            "venue_name": venue_name,
            "city": city,
            "address": address,
            "lat": lat,
            "lng": lng,
            "google_place_id": google_place_id,
            "confidence_score": confidence_score,
            "raw_api_response": raw_api_response,
            "updated_at": datetime.utcnow().isoformat(),
        }
        result = (
            self.client.table("venues")
            .upsert(data, on_conflict="google_place_id")
            .execute()
        )
        return result.data[0]["venue_id"]

    def link_leagues(self, venue_id: str, venue_name: str, city: str) -> int:
        """Set venue_id on all leagues with matching venue_name + city."""
        result = (
            self.client.table("leagues_metadata")
            .update({"venue_id": venue_id})
            .eq("venue_name", venue_name)
            .eq("city", city)
            .execute()
        )
        return len(result.data)

    def get_unenriched_pairs(self) -> list[tuple[str, str]]:
        """Return distinct (venue_name, city) pairs not yet linked to a venue."""
        result = (
            self.client.table("leagues_metadata")
            .select("venue_name, city")
            .is_("venue_id", "null")
            .not_.is_("venue_name", "null")
            .not_.is_("city", "null")
            .execute()
        )
        seen = set()
        pairs = []
        for row in result.data:
            key = (row["venue_name"], row["city"])
            if key not in seen:
                seen.add(key)
                pairs.append(key)
        return pairs

    def get_enrichment_stats(self) -> dict:
        """Return counts for the Streamlit stats panel."""
        all_rows = (
            self.client.table("leagues_metadata")
            .select("venue_id, venue_name, city")
            .not_.is_("venue_name", "null")
            .execute()
        ).data

        total = len({(r["venue_name"], r.get("city")) for r in all_rows})
        enriched = len({(r["venue_name"], r.get("city")) for r in all_rows if r.get("venue_id")})

        review_queue = (
            self.client.table("venues")
            .select("venue_id", count="exact")
            .eq("manually_verified", False)
            .lt("confidence_score", self.REVIEW_THRESHOLD)
            .execute()
        ).count or 0

        return {
            "total": total,
            "enriched": enriched,
            "pending": max(total - enriched, 0),
            "needs_review": review_queue,
        }

    def get_review_queue(self, limit: int = 50) -> list[dict]:
        """Return venues needing human review (low confidence, not verified)."""
        result = (
            self.client.table("venues")
            .select("*")
            .eq("manually_verified", False)
            .lt("confidence_score", self.REVIEW_THRESHOLD)
            .order("confidence_score", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data

    def accept_venue(self, venue_id: str) -> None:
        """Mark a venue as manually verified."""
        self.client.table("venues").update(
            {"manually_verified": True, "updated_at": datetime.utcnow().isoformat()}
        ).eq("venue_id", venue_id).execute()

    def update_venue_address(
        self, venue_id: str, address: str, lat: float | None, lng: float | None
    ) -> None:
        """Correct a venue's address (used in Edit flow)."""
        self.client.table("venues").update({
            "address": address,
            "lat": lat,
            "lng": lng,
            "manually_verified": True,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("venue_id", venue_id).execute()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_venue_store.py -v
```

Expected: 5 passed.

**Step 5: Commit**

```bash
git add src/database/venue_store.py tests/test_venue_store.py
git commit -m "feat: add VenueStore for venues table CRUD"
```

---

## Task 5: Core Enricher Orchestrator

**Files:**
- Create: `src/enrichers/venue_enricher.py`
- Create: `tests/test_venue_enricher.py`

**Step 1: Write the failing tests**

```python
# tests/test_venue_enricher.py
import pytest
from unittest.mock import MagicMock, patch
from src.enrichers.venue_enricher import VenueEnricher

GOOD_RESULT = {
    "place_id": "ChIJ_abc123",
    "name": "Ashbridges Bay Park",
    "formatted_address": "1561 Lake Shore Blvd E, Toronto, ON",
    "lat": 43.6632,
    "lng": -79.3070,
    "types": ["park", "establishment"],
    "user_ratings_total": 500,
    "raw": {},
}

WEAK_RESULT = {
    "place_id": "ChIJ_xyz999",
    "name": "Generic Sports Field",
    "formatted_address": "99 Unknown Rd, Toronto, ON",
    "lat": 43.5,
    "lng": -79.4,
    "types": ["establishment"],
    "user_ratings_total": 0,
    "raw": {},
}


@pytest.fixture
def mock_places():
    return MagicMock()


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get_unenriched_pairs.return_value = [
        ("Ashbridges Bay Park", "Toronto"),
        ("Vague Field", "Toronto"),
    ]
    store.save_venue.return_value = "uuid-new"
    return store


@pytest.fixture
def enricher(mock_places, mock_store):
    return VenueEnricher(places_client=mock_places, venue_store=mock_store)


def test_high_confidence_result_auto_saves(enricher, mock_places, mock_store):
    mock_places.search.return_value = GOOD_RESULT

    summary = enricher.run()

    assert summary["auto_saved"] == 2
    assert summary["queued_review"] == 0
    mock_store.save_venue.assert_called()
    mock_store.link_leagues.assert_called()


def test_low_confidence_result_goes_to_review(enricher, mock_places, mock_store):
    mock_places.search.return_value = WEAK_RESULT

    summary = enricher.run()

    # WEAK_RESULT scores low — both should go to review queue
    assert summary["auto_saved"] == 0
    assert summary["queued_review"] == 2
    # save_venue still called (saved but not auto-linked)
    mock_store.save_venue.assert_called()
    # link_leagues NOT called for review-queue items
    mock_store.link_leagues.assert_not_called()


def test_no_api_result_counts_as_failed(enricher, mock_places, mock_store):
    mock_places.search.return_value = None

    summary = enricher.run()

    assert summary["failed"] == 2
    mock_store.save_venue.assert_not_called()


def test_progress_callback_called_for_each_pair(enricher, mock_places):
    mock_places.search.return_value = GOOD_RESULT
    calls = []
    enricher.run(progress_callback=lambda current, total: calls.append((current, total)))
    assert len(calls) == 2
    assert calls[0] == (0, 2)
    assert calls[1] == (1, 2)


def test_run_returns_summary_dict(enricher, mock_places):
    mock_places.search.return_value = GOOD_RESULT
    summary = enricher.run()
    assert "auto_saved" in summary
    assert "queued_review" in summary
    assert "failed" in summary
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_venue_enricher.py -v
```

Expected: `ImportError: cannot import name 'VenueEnricher'`

**Step 3: Implement `src/enrichers/venue_enricher.py`**

```python
"""Core venue enrichment orchestrator."""

import logging
from src.enrichers.places_client import PlacesClient, PlacesAPIError
from src.enrichers.confidence_scorer import score as confidence_score, AUTO_SAVE_THRESHOLD
from src.database.venue_store import VenueStore

logger = logging.getLogger(__name__)


class VenueEnricher:
    def __init__(self, places_client: PlacesClient, venue_store: VenueStore):
        self.places = places_client
        self.store = venue_store

    def run(self, progress_callback=None) -> dict:
        """Enrich all unenriched (venue_name, city) pairs.

        Args:
            progress_callback: Optional callable(current_index, total) for UI progress.

        Returns:
            Summary dict: {auto_saved, queued_review, failed}
        """
        pairs = self.store.get_unenriched_pairs()
        auto_saved = 0
        queued_review = 0
        failed = 0

        for i, (venue_name, city) in enumerate(pairs):
            if progress_callback:
                progress_callback(i, len(pairs))

            outcome = self._process_pair(venue_name, city)
            if outcome == "auto_saved":
                auto_saved += 1
            elif outcome == "queued":
                queued_review += 1
            else:
                failed += 1

        logger.info(
            f"Enrichment complete: {auto_saved} auto-saved, "
            f"{queued_review} queued for review, {failed} failed"
        )
        return {"auto_saved": auto_saved, "queued_review": queued_review, "failed": failed}

    def _process_pair(self, venue_name: str, city: str) -> str:
        """Process one (venue_name, city) pair. Returns 'auto_saved', 'queued', or 'failed'."""
        try:
            api_result = self.places.search(venue_name, city)
        except PlacesAPIError as e:
            logger.error(f"Places API error for '{venue_name}, {city}': {e}")
            return "failed"

        if api_result is None:
            logger.debug(f"No Places result for '{venue_name}, {city}'")
            return "failed"

        conf = confidence_score(venue_name, city, api_result)

        venue_id = self.store.save_venue(
            venue_name=venue_name,
            city=city,
            address=api_result["formatted_address"],
            lat=api_result["lat"],
            lng=api_result["lng"],
            google_place_id=api_result["place_id"],
            confidence_score=conf,
            raw_api_response=api_result["raw"],
        )

        if conf >= AUTO_SAVE_THRESHOLD:
            self.store.link_leagues(venue_id, venue_name, city)
            return "auto_saved"

        return "queued"
```

**Step 4: Run all tests**

```bash
pytest tests/test_places_client.py tests/test_confidence_scorer.py tests/test_venue_store.py tests/test_venue_enricher.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add src/enrichers/venue_enricher.py tests/test_venue_enricher.py
git commit -m "feat: add VenueEnricher orchestrator"
```

---

## Task 6: Streamlit Page

**Files:**
- Create: `streamlit_app/pages/venues_enricher.py`

No unit tests for UI — the underlying functions (VenueEnricher, VenueStore) are already tested.

**Step 1: Implement `streamlit_app/pages/venues_enricher.py`**

```python
"""Venues Enricher — trigger enrichment and review low-confidence results."""

import os
import streamlit as st
from src.database.supabase_client import get_client
from src.database.venue_store import VenueStore
from src.enrichers.places_client import PlacesClient
from src.enrichers.venue_enricher import VenueEnricher


def _get_enricher() -> VenueEnricher:
    client = get_client()
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        st.error("GOOGLE_PLACES_API_KEY not set in .env")
        st.stop()
    return VenueEnricher(
        places_client=PlacesClient(api_key=api_key),
        venue_store=VenueStore(client=client),
    )


def _get_store() -> VenueStore:
    return VenueStore(client=get_client())


def render():
    st.title("📍 Venues Enricher")
    st.markdown("Resolve venue names to structured addresses via Google Places API.")

    store = _get_store()
    stats = store.get_enrichment_stats()

    # ── Stats panel ──────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Venues", stats["total"])
    col2.metric("Enriched", stats["enriched"])
    col3.metric("Pending", stats["pending"])
    col4.metric("Needs Review", stats["needs_review"])

    st.divider()

    # ── Trigger enrichment ───────────────────────────────────────
    if stats["pending"] == 0:
        st.success("All venues are enriched.")
    else:
        st.info(f"{stats['pending']} venue(s) pending enrichment.")
        if st.button("▶ Run Enrichment", type="primary"):
            enricher = _get_enricher()
            progress_bar = st.progress(0)
            status_text = st.empty()

            def on_progress(current, total):
                progress_bar.progress((current + 1) / total)
                status_text.text(f"Processing {current + 1} of {total}...")

            with st.spinner("Running..."):
                summary = enricher.run(progress_callback=on_progress)

            progress_bar.empty()
            status_text.empty()
            st.success(
                f"Done — {summary['auto_saved']} auto-saved, "
                f"{summary['queued_review']} queued for review, "
                f"{summary['failed']} failed (no result)."
            )
            st.rerun()

    # ── Review queue ─────────────────────────────────────────────
    st.subheader("Review Queue")
    queue = store.get_review_queue()

    if not queue:
        st.write("No items to review.")
        return

    for venue in queue:
        conf = venue.get("confidence_score", 0)
        label = f"**{venue['venue_name']}**, {venue.get('city', '?')} — confidence: {conf}/100"

        with st.expander(label):
            st.write(f"**Returned address:** {venue.get('address', 'N/A')}")
            if venue.get("lat") and venue.get("lng"):
                maps_url = (
                    f"https://www.google.com/maps/search/?api=1"
                    f"&query={venue['lat']},{venue['lng']}"
                )
                st.markdown(f"[Open in Google Maps ↗]({maps_url})")
            st.write(f"**Google Place ID:** {venue.get('google_place_id', 'N/A')}")

            col_a, col_b, col_c = st.columns(3)

            with col_a:
                if st.button("✓ Accept", key=f"accept_{venue['venue_id']}"):
                    store.accept_venue(venue["venue_id"])
                    store.link_leagues(venue["venue_id"], venue["venue_name"], venue.get("city", ""))
                    st.rerun()

            with col_b:
                new_address = st.text_input(
                    "Corrected address",
                    value=venue.get("address", ""),
                    key=f"edit_{venue['venue_id']}",
                )
                if st.button("💾 Save edit", key=f"save_{venue['venue_id']}"):
                    store.update_venue_address(venue["venue_id"], new_address, None, None)
                    store.link_leagues(venue["venue_id"], venue["venue_name"], venue.get("city", ""))
                    st.rerun()

            with col_c:
                if st.button("⏭ Skip", key=f"skip_{venue['venue_id']}"):
                    st.rerun()  # Simply skip for now — stays in queue
```

**Step 2: Verify it renders without errors**

```bash
cd /c/Users/mathe/VSCode/aa_RecLeagueDB
streamlit run streamlit_app/app.py
```

Navigate to "📍 Venues Enricher" in the sidebar. Expected: page loads, stats show (may all be 0), Run Enrichment button visible.

**Step 3: Commit**

```bash
git add streamlit_app/pages/venues_enricher.py
git commit -m "feat: add venues enricher Streamlit page"
```

---

## Task 7: Wire Navigation + Add Env Var

**Files:**
- Modify: `streamlit_app/app.py`
- Modify: `.env` (manual — add key)
- Modify: `docs/agents/CLAUDE_MANAGE.md` (add venues enricher to page list)

**Step 1: Add `GOOGLE_PLACES_API_KEY` to `.env`**

Add this line to `.env`:
```
GOOGLE_PLACES_API_KEY=<your-key-from-google-cloud-console>
```

Get from: Google Cloud Console → APIs & Services → Enable "Places API" → Credentials → Create API Key.

**Step 2: Add to app.py navigation**

In `streamlit_app/app.py`, add `"📍 Venues Enricher"` to the Data Management section:

```python
    st.caption("── Data Management ──")
    for label in ["🗂️ Leagues Viewer", "📊 Data Quality", "🔀 Merge Tool", "📍 Venues Enricher"]:
```

And add to the `PAGES` dict:

```python
    "📍 Venues Enricher":        ("manage",  "venues_enricher"),
```

And add the routing case:

```python
elif module_name == "venues_enricher":
    from pages import venues_enricher
    venues_enricher.render()
```

**Step 3: Update CLAUDE_MANAGE.md**

In `docs/agents/CLAUDE_MANAGE.md`, add to the Streamlit pages section:

```markdown
### 4. venues_enricher.py — Venue Address Lookup

**Purpose:** Resolve venue_name + city pairs to structured addresses via Google Places API.

**Features:** Run enrichment (batch), review queue for confidence < 75, Accept/Edit/Skip actions.

**Key modules:** `src/enrichers/venue_enricher.py`, `src/enrichers/places_client.py`, `src/database/venue_store.py`

**New env var required:** `GOOGLE_PLACES_API_KEY`
```

**Step 4: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all existing tests + new tests pass.

**Step 5: Final commit**

```bash
git add streamlit_app/app.py docs/agents/CLAUDE_MANAGE.md
git commit -m "feat: wire venues enricher into app navigation"
```
