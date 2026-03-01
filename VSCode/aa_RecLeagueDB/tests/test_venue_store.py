# tests/test_venue_store.py
import pytest
from unittest.mock import MagicMock
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
