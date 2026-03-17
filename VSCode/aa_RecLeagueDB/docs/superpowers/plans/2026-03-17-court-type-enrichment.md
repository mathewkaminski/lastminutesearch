# Court Type Enrichment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify enriched venues by court type (broad + specific, each with confidence) using Claude Haiku, and add an Enriched Venues tab to the Venues Enricher page with filters and per-venue league stats.

**Architecture:** Standalone `CourtTypeClassifier` (Haiku) + `CourtTypeEnricher` orchestrator, mirroring the existing `VenueEnricher` pattern. New `VenueStore` methods handle DB reads/writes. UI is restructured into two `st.tabs()`.

**Tech Stack:** Python 3.11, Anthropic SDK (`anthropic`), Supabase Python client, Streamlit, pandas

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `migrations/015_add_court_type_to_venues.sql` | Add 4 court type columns |
| Create | `src/enrichers/court_type_classifier.py` | Haiku classification call |
| Create | `src/enrichers/court_type_enricher.py` | Orchestrate classification over all venues |
| Modify | `src/database/venue_store.py` | Add 4 new methods |
| Modify | `streamlit_app/pages/venues_enricher.py` | Restructure into tabs, add Enriched Venues tab |
| Create | `tests/test_court_type_classifier.py` | Unit tests for classifier |
| Create | `tests/test_court_type_enricher.py` | Unit tests for enricher |
| Modify | `tests/test_venue_store.py` | Fix outdated save_venue test; add tests for new methods |

---

## Task 1: Migration

**Files:**
- Create: `migrations/015_add_court_type_to_venues.sql`

- [ ] **Step 1: Write migration file**

```sql
-- migrations/015_add_court_type_to_venues.sql
-- Add court type classification columns to venues.

ALTER TABLE public.venues
    ADD COLUMN IF NOT EXISTS court_type_broad       TEXT,
    ADD COLUMN IF NOT EXISTS court_type_broad_conf  INT CHECK (court_type_broad_conf BETWEEN 0 AND 100),
    ADD COLUMN IF NOT EXISTS court_type_specific    TEXT,
    ADD COLUMN IF NOT EXISTS court_type_specific_conf INT CHECK (court_type_specific_conf BETWEEN 0 AND 100);
```

- [ ] **Step 2: Run migration**

```bash
psql "$PSQL_CONNECTION_STRING" -f migrations/015_add_court_type_to_venues.sql
```

Expected output: `ALTER TABLE`

- [ ] **Step 3: Commit**

```bash
git add migrations/015_add_court_type_to_venues.sql
git commit -m "feat: add court type columns to venues"
```

---

## Task 2: CourtTypeClassifier

**Files:**
- Create: `src/enrichers/court_type_classifier.py`
- Create: `tests/test_court_type_classifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_court_type_classifier.py
import json
import pytest
from unittest.mock import MagicMock
from src.enrichers.court_type_classifier import CourtTypeClassifier, CourtTypeError

VALID_RESPONSE = json.dumps({
    "broad": "Indoor",
    "broad_conf": 90,
    "specific": "Gym/Rec Centre",
    "specific_conf": 85,
})


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text=VALID_RESPONSE)]
    return client


@pytest.fixture
def classifier(mock_client):
    return CourtTypeClassifier(client=mock_client)


def test_classify_returns_all_fields(classifier):
    result = classifier.classify(
        venue_name="Toronto Rec Centre",
        google_name="Toronto Recreation Centre",
        address="100 Main St, Toronto, ON",
    )
    assert result["broad"] == "Indoor"
    assert result["broad_conf"] == 90
    assert result["specific"] == "Gym/Rec Centre"
    assert result["specific_conf"] == 85


def test_classify_calls_haiku_model(classifier, mock_client):
    classifier.classify("Venue", "Venue", "123 St")
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"


def test_invalid_broad_falls_back_to_unknown(mock_client):
    mock_client.messages.create.return_value.content = [
        MagicMock(text=json.dumps({"broad": "Swamp", "broad_conf": 80, "specific": "Other", "specific_conf": 50}))
    ]
    classifier = CourtTypeClassifier(client=mock_client)
    result = classifier.classify("V", "V", "A")
    assert result["broad"] == "Unknown"
    assert result["broad_conf"] == 0


def test_api_error_raises_court_type_error(mock_client):
    mock_client.messages.create.side_effect = Exception("API down")
    classifier = CourtTypeClassifier(client=mock_client)
    with pytest.raises(CourtTypeError):
        classifier.classify("V", "V", "A")


def test_unparseable_json_raises_court_type_error(mock_client):
    mock_client.messages.create.return_value.content = [MagicMock(text="not json")]
    classifier = CourtTypeClassifier(client=mock_client)
    with pytest.raises(CourtTypeError):
        classifier.classify("V", "V", "A")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /app && python -m pytest tests/test_court_type_classifier.py -v
```

Expected: ImportError or ModuleNotFoundError

- [ ] **Step 3: Implement `CourtTypeClassifier`**

```python
# src/enrichers/court_type_classifier.py
"""Haiku-based court type classifier for venues."""

import json
import logging

logger = logging.getLogger(__name__)

BROAD_TYPES = {"Indoor", "Outdoor", "Beach", "Ice", "Pool", "Unknown"}
SPECIFIC_TYPES = {
    "Gym/Rec Centre", "Turf Field", "Grass Field", "Beach",
    "Ice Rink", "Tennis-Pickleball", "Baseball Diamond", "Swimming Pool", "Other",
}

_PROMPT = """\
Classify this sports venue by court/facility type.

Venue name: {venue_name}
Google name: {google_name}
Address: {address}

Return ONLY valid JSON with these exact keys:
{{
  "broad": one of ["Indoor", "Outdoor", "Beach", "Ice", "Pool", "Unknown"],
  "broad_conf": integer 0-100,
  "specific": one of ["Gym/Rec Centre", "Turf Field", "Grass Field", "Beach", "Ice Rink", "Tennis-Pickleball", "Baseball Diamond", "Swimming Pool", "Other"],
  "specific_conf": integer 0-100
}}

Use confidence 0 if you cannot determine the type."""


class CourtTypeError(Exception):
    pass


class CourtTypeClassifier:
    MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, client):
        """Args:
            client: anthropic.Anthropic instance.
        """
        self.client = client

    def classify(
        self,
        venue_name: str,
        google_name: str | None,
        address: str | None,
    ) -> dict:
        """Classify a venue into broad and specific court types.

        Returns:
            dict with keys: broad, broad_conf, specific, specific_conf

        Raises:
            CourtTypeError: on API failure or unparseable response.
        """
        prompt = _PROMPT.format(
            venue_name=venue_name,
            google_name=google_name or venue_name,
            address=address or "unknown",
        )
        try:
            response = self.client.messages.create(
                model=self.MODEL,
                max_tokens=128,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
        except Exception as e:
            raise CourtTypeError(f"Haiku API error for '{venue_name}': {e}") from e

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise CourtTypeError(f"Unparseable response for '{venue_name}': {raw!r}") from e

        # Validate enums; fall back to Unknown/Other if invalid
        if data.get("broad") not in BROAD_TYPES:
            logger.warning(f"Invalid broad type '{data.get('broad')}' for '{venue_name}', defaulting to Unknown")
            data["broad"] = "Unknown"
            data["broad_conf"] = 0
        if data.get("specific") not in SPECIFIC_TYPES:
            logger.warning(f"Invalid specific type '{data.get('specific')}' for '{venue_name}', defaulting to Other")
            data["specific"] = "Other"
            data["specific_conf"] = 0

        return {
            "broad": data["broad"],
            "broad_conf": int(data.get("broad_conf", 0)),
            "specific": data["specific"],
            "specific_conf": int(data.get("specific_conf", 0)),
        }
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /app && python -m pytest tests/test_court_type_classifier.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add src/enrichers/court_type_classifier.py tests/test_court_type_classifier.py
git commit -m "feat: add CourtTypeClassifier (Haiku-based)"
```

---

## Task 3: CourtTypeEnricher

**Files:**
- Create: `src/enrichers/court_type_enricher.py`
- Create: `tests/test_court_type_enricher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_court_type_enricher.py
import pytest
from unittest.mock import MagicMock
from src.enrichers.court_type_enricher import CourtTypeEnricher
from src.enrichers.court_type_classifier import CourtTypeError

CLASSIFICATION = {
    "broad": "Outdoor",
    "broad_conf": 80,
    "specific": "Grass Field",
    "specific_conf": 75,
}

VENUES = [
    {"venue_id": "uuid-1", "venue_name": "Ashbridges Bay", "google_name": "Ashbridges Bay Park", "address": "1561 Lake Shore Blvd E, Toronto, ON"},
    {"venue_id": "uuid-2", "venue_name": "Riverdale Arena", "google_name": "Riverdale Arena", "address": "270 Broadview Ave, Toronto, ON"},
]


@pytest.fixture
def mock_classifier():
    c = MagicMock()
    c.classify.return_value = CLASSIFICATION
    return c


@pytest.fixture
def mock_store():
    s = MagicMock()
    s.get_venues_for_classification.return_value = VENUES
    return s


@pytest.fixture
def enricher(mock_classifier, mock_store):
    return CourtTypeEnricher(classifier=mock_classifier, venue_store=mock_store)


def test_run_returns_summary(enricher):
    result = enricher.run()
    assert result["classified"] == 2
    assert result["failed"] == 0


def test_run_calls_save_for_each_venue(enricher, mock_store):
    enricher.run()
    assert mock_store.save_court_type.call_count == 2


def test_classifier_error_counts_as_failed(mock_classifier, mock_store):
    mock_classifier.classify.side_effect = CourtTypeError("API down")
    enricher = CourtTypeEnricher(classifier=mock_classifier, venue_store=mock_store)
    result = enricher.run()
    assert result["classified"] == 0
    assert result["failed"] == 2
    mock_store.save_court_type.assert_not_called()


def test_progress_callback_called_for_each_venue(enricher):
    calls = []
    enricher.run(progress_callback=lambda i, t: calls.append((i, t)))
    assert len(calls) == 2
    assert calls[0] == (0, 2)
    assert calls[1] == (1, 2)


def test_empty_venues_returns_zero_summary(mock_classifier, mock_store):
    mock_store.get_venues_for_classification.return_value = []
    enricher = CourtTypeEnricher(classifier=mock_classifier, venue_store=mock_store)
    result = enricher.run()
    assert result == {"classified": 0, "failed": 0}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /app && python -m pytest tests/test_court_type_enricher.py -v
```

Expected: ImportError

- [ ] **Step 3: Implement `CourtTypeEnricher`**

```python
# src/enrichers/court_type_enricher.py
"""Orchestrates court type classification over all unclassified venues."""

import logging
from src.enrichers.court_type_classifier import CourtTypeClassifier, CourtTypeError
from src.database.venue_store import VenueStore

logger = logging.getLogger(__name__)


class CourtTypeEnricher:
    def __init__(self, classifier: CourtTypeClassifier, venue_store: VenueStore):
        self.classifier = classifier
        self.store = venue_store

    def run(self, progress_callback=None) -> dict:
        """Classify all enriched venues missing court_type_broad.

        Args:
            progress_callback: Optional callable(current_index, total).

        Returns:
            {classified: int, failed: int}
        """
        venues = self.store.get_venues_for_classification()
        classified = 0
        failed = 0

        for i, venue in enumerate(venues):
            if progress_callback:
                progress_callback(i, len(venues))
            try:
                result = self.classifier.classify(
                    venue_name=venue["venue_name"],
                    google_name=venue.get("google_name"),
                    address=venue.get("address"),
                )
                self.store.save_court_type(
                    venue_id=venue["venue_id"],
                    broad=result["broad"],
                    broad_conf=result["broad_conf"],
                    specific=result["specific"],
                    specific_conf=result["specific_conf"],
                )
                classified += 1
            except CourtTypeError as e:
                logger.error(f"Court type classification failed for '{venue['venue_name']}': {e}")
                failed += 1

        logger.info(f"Court type enrichment: {classified} classified, {failed} failed")
        return {"classified": classified, "failed": failed}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /app && python -m pytest tests/test_court_type_enricher.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add src/enrichers/court_type_enricher.py tests/test_court_type_enricher.py
git commit -m "feat: add CourtTypeEnricher orchestrator"
```

---

## Task 4: VenueStore — new methods + fix outdated test

**Files:**
- Modify: `src/database/venue_store.py`
- Modify: `tests/test_venue_store.py`

- [ ] **Step 1: Write failing tests for new methods**

Add to `tests/test_venue_store.py` (append, do not replace existing tests):

```python
def test_get_venues_for_classification_filters_correctly(store, mock_client):
    mock_client.table.return_value.select.return_value.not_.is_.return_value.is_.return_value.execute.return_value.data = [
        {"venue_id": "uuid-1", "venue_name": "Park A", "google_name": "Park A", "address": "1 Main St"}
    ]
    results = store.get_venues_for_classification()
    assert len(results) == 1
    assert results[0]["venue_id"] == "uuid-1"


def test_save_court_type_updates_all_four_fields(store, mock_client):
    store.save_court_type("uuid-1", "Outdoor", 80, "Grass Field", 75)
    update_call = mock_client.table.return_value.update.call_args[0][0]
    assert update_call["court_type_broad"] == "Outdoor"
    assert update_call["court_type_broad_conf"] == 80
    assert update_call["court_type_specific"] == "Grass Field"
    assert update_call["court_type_specific_conf"] == 75


def test_get_league_stats_returns_empty_for_no_ids(store, mock_client):
    result = store.get_league_stats_for_venues([])
    assert result == {}
    mock_client.table.assert_not_called()


def test_get_league_stats_aggregates_correctly(store, mock_client):
    mock_client.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"venue_id": "uuid-1", "team_fee": 100.0, "individual_fee": None, "start_time": "7:00 PM", "day_of_week": "Monday"},
        {"venue_id": "uuid-1", "team_fee": 200.0, "individual_fee": None, "start_time": "8:00 PM", "day_of_week": "Wednesday"},
    ]
    stats = store.get_league_stats_for_venues(["uuid-1"])
    assert stats["uuid-1"]["num_leagues"] == 2
    assert stats["uuid-1"]["avg_team_fee"] == 150.0
    assert stats["uuid-1"]["avg_individual_fee"] is None
    assert "7:00 PM" in stats["uuid-1"]["hours"]
```

- [ ] **Step 2: Fix the outdated `test_save_venue_inserts_and_returns_id` test**

The current test uses the old `upsert` interface. Replace it with one that matches the new select-then-insert flow:

In `tests/test_venue_store.py`, replace `test_save_venue_inserts_and_returns_id` with:

```python
def test_save_venue_inserts_when_no_existing(store, mock_client):
    # No existing venue found by name+city
    mock_client.table.return_value.select.return_value.ilike.return_value.ilike.return_value.limit.return_value.execute.return_value.data = []
    # Insert returns new venue_id
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [{"venue_id": "uuid-new"}]

    venue_id = store.save_venue(
        venue_name="Ashbridges Bay Park",
        city="Toronto",
        google_name="Ashbridges Bay Park",
        address="1561 Lake Shore Blvd E, Toronto, ON M4L 3W6, Canada",
        lat=43.6632,
        lng=-79.3070,
        google_place_id="ChIJ_abc123",
        confidence_score=95,
        raw_api_response={"results": []},
    )
    assert venue_id == "uuid-new"
    mock_client.table.return_value.insert.assert_called_once()
```

- [ ] **Step 3: Run tests to confirm new ones fail, fixed one passes**

```bash
cd /app && python -m pytest tests/test_venue_store.py -v
```

Expected: new tests FAIL (methods not yet added), `test_save_venue_inserts_when_no_existing` PASSES

- [ ] **Step 4: Add the four new methods to `VenueStore`**

In `src/database/venue_store.py`, add after `update_google_name`:

```python
def get_venues_for_classification(self) -> list[dict]:
    """Return enriched venues (has lat) that have not yet been classified."""
    result = (
        self.client.table("venues")
        .select("venue_id, venue_name, google_name, address")
        .not_.is_("lat", "null")
        .is_("court_type_broad", "null")
        .execute()
    )
    return result.data

def save_court_type(
    self,
    venue_id: str,
    broad: str,
    broad_conf: int,
    specific: str,
    specific_conf: int,
) -> None:
    """Write court type classification result for a venue."""
    self.client.table("venues").update({
        "court_type_broad": broad,
        "court_type_broad_conf": broad_conf,
        "court_type_specific": specific,
        "court_type_specific_conf": specific_conf,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("venue_id", venue_id).execute()

def get_enriched_venues(
    self,
    broad: str | None = None,
    specific: str | None = None,
    province: str | None = None,
    city: str | None = None,
    sport: str | None = None,
) -> list[dict]:
    """Return enriched venues (has lat/lng), optionally filtered."""
    query = (
        self.client.table("venues")
        .select(
            "venue_id, venue_name, google_name, city, province, address, "
            "confidence_score, manually_verified, sports, days_of_week, "
            "court_type_broad, court_type_broad_conf, "
            "court_type_specific, court_type_specific_conf"
        )
        .not_.is_("lat", "null")
    )
    if broad:
        query = query.eq("court_type_broad", broad)
    if specific:
        query = query.eq("court_type_specific", specific)
    if province:
        query = query.eq("province", province)
    if city:
        query = query.ilike("city", f"%{city}%")
    if sport:
        query = query.contains("sports", [sport])
    return query.order("city").order("venue_name").execute().data

def get_league_stats_for_venues(self, venue_ids: list[str]) -> dict:
    """Aggregate league data from leagues_metadata for a list of venue_ids.

    Returns dict keyed by venue_id with:
        num_leagues, avg_team_fee, avg_individual_fee, hours (sorted list)
    """
    if not venue_ids:
        return {}
    result = (
        self.client.table("leagues_metadata")
        .select("venue_id, team_fee, individual_fee, start_time, day_of_week")
        .in_("venue_id", venue_ids)
        .execute()
    )
    stats: dict = {}
    for row in result.data:
        vid = row["venue_id"]
        if vid not in stats:
            stats[vid] = {
                "num_leagues": 0,
                "team_fees": [],
                "individual_fees": [],
                "hours": set(),
            }
        s = stats[vid]
        s["num_leagues"] += 1
        if row.get("team_fee") is not None:
            s["team_fees"].append(float(row["team_fee"]))
        if row.get("individual_fee") is not None:
            s["individual_fees"].append(float(row["individual_fee"]))
        if row.get("start_time"):
            s["hours"].add(row["start_time"])

    return {
        vid: {
            "num_leagues": s["num_leagues"],
            "avg_team_fee": round(sum(s["team_fees"]) / len(s["team_fees"]), 2) if s["team_fees"] else None,
            "avg_individual_fee": round(sum(s["individual_fees"]) / len(s["individual_fees"]), 2) if s["individual_fees"] else None,
            "hours": sorted(s["hours"]),
        }
        for vid, s in stats.items()
    }
```

- [ ] **Step 5: Run all venue_store tests**

```bash
cd /app && python -m pytest tests/test_venue_store.py -v
```

Expected: all tests PASSED

- [ ] **Step 6: Commit**

```bash
git add src/database/venue_store.py tests/test_venue_store.py
git commit -m "feat: add VenueStore methods for court type + league stats"
```

---

## Task 5: Venues Enricher UI

**Files:**
- Modify: `streamlit_app/pages/venues_enricher.py`

This task has no unit tests (Streamlit UI). Verify by running the app.

- [ ] **Step 1: Rewrite `venues_enricher.py`**

Replace the entire file with:

```python
"""Venues Enricher — enrich, classify, and review venue records."""

import os
import pandas as pd
import streamlit as st
from anthropic import Anthropic
from src.database.supabase_client import get_client
from src.database.venue_store import VenueStore
from src.enrichers.places_client import PlacesClient
from src.enrichers.venue_enricher import VenueEnricher
from src.enrichers.court_type_classifier import CourtTypeClassifier
from src.enrichers.court_type_enricher import CourtTypeEnricher


def _get_venue_enricher() -> VenueEnricher:
    client = get_client()
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        st.error("GOOGLE_PLACES_API_KEY not set in .env")
        st.stop()
    return VenueEnricher(
        places_client=PlacesClient(api_key=api_key),
        venue_store=VenueStore(client=client),
    )


def _get_court_enricher() -> CourtTypeEnricher:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY not set in .env")
        st.stop()
    return CourtTypeEnricher(
        classifier=CourtTypeClassifier(client=Anthropic(api_key=api_key)),
        venue_store=VenueStore(client=get_client()),
    )


def _get_store() -> VenueStore:
    return VenueStore(client=get_client())


def _render_all_venues(store: VenueStore) -> None:
    venues = store.get_all_venues()
    if not venues:
        st.write("No venues yet.")
        return

    df = pd.DataFrame(venues)
    for col in ("sports", "days_of_week"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: ", ".join(v) if isinstance(v, list) else (v or "")
            )

    edited = st.data_editor(
        df,
        column_config={
            "venue_id": None,
            "venue_name": st.column_config.TextColumn("Scraped Name", disabled=True),
            "google_name": st.column_config.TextColumn("Google Name", width="medium"),
            "city": st.column_config.TextColumn("City", disabled=True, width="small"),
            "province": st.column_config.TextColumn("Prov.", disabled=True, width="small"),
            "address": st.column_config.TextColumn("Address", disabled=True, width="large"),
            "confidence_score": st.column_config.NumberColumn("Conf.", disabled=True, width="small"),
            "manually_verified": st.column_config.CheckboxColumn("Verified", disabled=True, width="small"),
            "sports": st.column_config.TextColumn("Sports", disabled=True, width="medium"),
            "days_of_week": st.column_config.TextColumn("Days", disabled=True, width="medium"),
        },
        hide_index=True,
        use_container_width=True,
        key="all_venues_table",
    )

    if st.button("💾 Save Name Changes", key="save_all"):
        orig = df.set_index("venue_id")["google_name"]
        updated = edited.set_index("venue_id")["google_name"]
        changed = orig[orig != updated].index.tolist()
        if changed:
            for vid in changed:
                store.update_google_name(vid, updated[vid] or None)
            st.success(f"Saved {len(changed)} name change(s).")
            st.rerun()
        else:
            st.info("No changes detected.")


def _render_enriched_venues(store: VenueStore) -> None:
    # ── Classify button ───────────────────────────────────────────
    unclassified = store.get_venues_for_classification()
    total_enriched = len(store.get_enriched_venues())
    classified_count = total_enriched - len(unclassified)

    st.caption(f"{classified_count} of {total_enriched} venues classified")

    if unclassified:
        st.info(f"{len(unclassified)} venue(s) not yet classified.")
        if st.button("▶ Classify Court Types", type="primary"):
            enricher = _get_court_enricher()
            progress_bar = st.progress(0)
            status_text = st.empty()

            def on_progress(current, total):
                progress_bar.progress((current + 1) / total)
                status_text.text(f"Classifying {current + 1} of {total}...")

            with st.spinner("Running..."):
                summary = enricher.run(progress_callback=on_progress)

            progress_bar.empty()
            status_text.empty()
            st.success(
                f"Done — {summary['classified']} classified, {summary['failed']} failed."
            )
            st.rerun()

    st.divider()

    # ── Filters ───────────────────────────────────────────────────
    all_venues = store.get_enriched_venues()
    if not all_venues:
        st.write("No enriched venues yet.")
        return

    df_all = pd.DataFrame(all_venues)

    broad_options = [""] + sorted(df_all["court_type_broad"].dropna().unique().tolist())
    specific_options = [""] + sorted(df_all["court_type_specific"].dropna().unique().tolist())
    province_options = [""] + sorted(df_all["province"].dropna().unique().tolist())
    sport_options = [""] + sorted({
        s for row in df_all["sports"].dropna()
        for s in (row if isinstance(row, list) else row.split(", "))
        if s
    })

    fc1, fc2, fc3, fc4, fc5 = st.columns([1, 1, 1, 1, 1])
    broad_filter = fc1.selectbox("Broad Type", broad_options, key="f_broad")
    specific_filter = fc2.selectbox("Specific Type", specific_options, key="f_specific")
    province_filter = fc3.selectbox("Province", province_options, key="f_province")
    city_filter = fc4.text_input("City", key="f_city")
    sport_filter = fc5.selectbox("Sport", sport_options, key="f_sport")

    venues = store.get_enriched_venues(
        broad=broad_filter or None,
        specific=specific_filter or None,
        province=province_filter or None,
        city=city_filter.strip() or None,
        sport=sport_filter or None,
    )

    if not venues:
        st.write("No venues match the current filters.")
        return

    # ── League stats ──────────────────────────────────────────────
    venue_ids = [v["venue_id"] for v in venues]
    league_stats = store.get_league_stats_for_venues(venue_ids)

    df = pd.DataFrame(venues)
    df["# Leagues"] = df["venue_id"].map(lambda vid: league_stats.get(vid, {}).get("num_leagues", 0))
    df["Avg Team Fee"] = df["venue_id"].map(lambda vid: league_stats.get(vid, {}).get("avg_team_fee"))
    df["Avg Indiv. Fee"] = df["venue_id"].map(lambda vid: league_stats.get(vid, {}).get("avg_individual_fee"))
    df["Hours"] = df["venue_id"].map(
        lambda vid: ", ".join(league_stats.get(vid, {}).get("hours", []))
    )

    for col in ("sports", "days_of_week"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: ", ".join(v) if isinstance(v, list) else (v or "")
            )

    st.caption(f"{len(df)} venue(s) shown")

    edited = st.data_editor(
        df,
        column_config={
            "venue_id": None,
            "venue_name": None,
            "manually_verified": None,
            "google_name": st.column_config.TextColumn("Google Name", width="medium"),
            "city": st.column_config.TextColumn("City", disabled=True, width="small"),
            "province": st.column_config.TextColumn("Prov.", disabled=True, width="small"),
            "address": st.column_config.TextColumn("Address", disabled=True, width="large"),
            "confidence_score": st.column_config.NumberColumn("Conf.", disabled=True, width="small"),
            "court_type_broad": st.column_config.TextColumn("Broad", disabled=True, width="small"),
            "court_type_broad_conf": st.column_config.NumberColumn("B.Conf", disabled=True, width="small"),
            "court_type_specific": st.column_config.TextColumn("Specific", disabled=True, width="medium"),
            "court_type_specific_conf": st.column_config.NumberColumn("S.Conf", disabled=True, width="small"),
            "sports": st.column_config.TextColumn("Sports", disabled=True, width="medium"),
            "days_of_week": st.column_config.TextColumn("Days", disabled=True, width="medium"),
            "# Leagues": st.column_config.NumberColumn("# Leagues", disabled=True, width="small"),
            "Avg Team Fee": st.column_config.NumberColumn("Avg Team $", disabled=True, format="$%.0f", width="small"),
            "Avg Indiv. Fee": st.column_config.NumberColumn("Avg Indiv. $", disabled=True, format="$%.0f", width="small"),
            "Hours": st.column_config.TextColumn("Hours", disabled=True, width="medium"),
        },
        hide_index=True,
        use_container_width=True,
        key="enriched_venues_table",
    )

    if st.button("💾 Save Name Changes", key="save_enriched"):
        orig = df.set_index("venue_id")["google_name"]
        updated = edited.set_index("venue_id")["google_name"]
        changed = orig[orig != updated].index.tolist()
        if changed:
            for vid in changed:
                store.update_google_name(vid, updated[vid] or None)
            st.success(f"Saved {len(changed)} name change(s).")
            st.rerun()
        else:
            st.info("No changes detected.")


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

    # ── Trigger address enrichment ────────────────────────────────
    if stats["pending"] == 0:
        st.success("All venues are enriched.")
    else:
        st.info(f"{stats['pending']} venue(s) pending enrichment.")
        if st.button("▶ Run Enrichment", type="primary"):
            enricher = _get_venue_enricher()
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

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────
    tab_all, tab_enriched = st.tabs(["All Venues", "Enriched Venues"])

    with tab_all:
        _render_all_venues(store)

    with tab_enriched:
        _render_enriched_venues(store)
```

- [ ] **Step 2: Verify app runs without import errors**

```bash
cd /app && python -c "from streamlit_app.pages import venues_enricher; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/venues_enricher.py
git commit -m "feat: venues enricher — tabs, court type classify button, enriched venues with filters + league stats"
```

---

## Task 6: Full test run + version bump

- [ ] **Step 1: Run all venue-related tests**

```bash
cd /app && python -m pytest tests/test_court_type_classifier.py tests/test_court_type_enricher.py tests/test_venue_store.py tests/test_venue_enricher.py -v
```

Expected: all PASSED

- [ ] **Step 2: Bump version in `streamlit_app/app.py`**

Find the footer line (near end of file):
```python
'<div style="text-align: center; color: #666; font-size: 0.8rem;">RecSportsDB | 2026 | v1.11</div>',
```
Increment the version (e.g. `v1.11` → `v1.12`, or whatever current version + 1).

- [ ] **Step 3: Final commit**

```bash
git add streamlit_app/app.py
git commit -m "v1.XX: court type enrichment + enriched venues tab"
git push
```
