# tests/test_venue_enricher.py
import pytest
from unittest.mock import MagicMock
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
        ("Ashbridges Bay", "Toronto"),
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
    assert summary["auto_saved"] == 0
    assert summary["queued_review"] == 2
    mock_store.save_venue.assert_called()
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
