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


def test_save_venue_inserts_when_no_existing(store, mock_client):
    # No existing venue found by name
    mock_client.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value.data = []
    # No existing venue found by google_place_id (fallback)
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    # Insert returns new venue_id
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [{"venue_id": "uuid-new"}]

    venue_id = store.save_venue(
        venue_name="Ashbridges Bay Park",
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


def test_link_leagues_updates_matching_rows(store, mock_client):
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {}, {}
    ]
    count = store.link_leagues(
        venue_id="uuid-123",
        venue_name="Ashbridges Bay Park",
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


def test_get_unenriched_venue_names_returns_distinct_names(store, mock_client):
    mock_client.table.return_value.select.return_value.is_.return_value.not_.is_.return_value.execute.return_value.data = [
        {"venue_name": "Park A"},
        {"venue_name": "Park B"},
        {"venue_name": "Park A"},
    ]
    names = store.get_unenriched_venue_names()
    assert len(names) == 2
    assert "Park A" in names
    assert "Park B" in names


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


def test_get_leagues_for_venue_name_returns_rows(store, mock_client):
    mock_client.table.return_value.select.return_value.ilike.return_value.order.return_value.execute.return_value.data = [
        {"league_id": "lg-1", "organization_name": "Rec Co", "sport_name": "Volleyball",
         "season_name": "Winter 2026", "day_of_week": "Thursday"}
    ]
    results = store.get_leagues_for_venue_name("Community Centre")
    assert len(results) == 1
    assert results[0]["sport_name"] == "Volleyball"


def test_get_unenriched_with_counts_returns_name_and_count(store, mock_client):
    mock_client.table.return_value.select.return_value.is_.return_value.not_.is_.return_value.execute.return_value.data = [
        {"venue_name": "Park A"},
        {"venue_name": "Park A"},
        {"venue_name": "Park B"},
    ]
    results = store.get_unenriched_with_counts()
    assert len(results) == 2
    park_a = next(r for r in results if r["venue_name"] == "Park A")
    assert park_a["league_count"] == 2
    park_b = next(r for r in results if r["venue_name"] == "Park B")
    assert park_b["league_count"] == 1


def test_toggle_verified_sets_value(store, mock_client):
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    store.toggle_verified("uuid-1", True)
    payload = mock_client.table.return_value.update.call_args[0][0]
    assert payload["manually_verified"] is True

    store.toggle_verified("uuid-1", False)
    payload = mock_client.table.return_value.update.call_args[0][0]
    assert payload["manually_verified"] is False


def test_get_enriched_venues_with_season_returns_empty_when_no_match(store, mock_client):
    # Season subquery returns no venue_ids → short-circuit, return [] immediately
    mock_client.table.return_value.select.return_value.ilike.return_value.execute.return_value.data = []
    result = store.get_enriched_venues(season="Fall 2025")
    assert result == []
    # venues table should never have been queried — only leagues_metadata
    queried_tables = [c[0][0] for c in mock_client.table.call_args_list]
    assert "venues" not in queried_tables


def test_get_leagues_for_venue_returns_rows(store, mock_client):
    mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
        {
            "league_id": "lg-1",
            "organization_name": "Ottawa Rec",
            "sport_name": "Soccer",
            "season_name": "Fall 2025",
            "day_of_week": "Wednesday",
            "stat_holidays": [{"date": "2025-10-13", "reason": "Thanksgiving"}],
        }
    ]
    results = store.get_leagues_for_venue("uuid-1")
    assert len(results) == 1
    assert results[0]["sport_name"] == "Soccer"
    assert results[0]["season_name"] == "Fall 2025"


def test_save_venue_drops_google_place_id_when_belongs_to_different_venue(store):
    """Two venue names resolve to the same Google Place — don't violate unique constraint."""
    client = MagicMock()
    store = VenueStore(client=client)

    # Found by venue_name
    client.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value.data = [
        {"venue_id": "uuid-A"}
    ]
    # google_place_id belongs to a DIFFERENT venue
    client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"venue_id": "uuid-B"}
    ]
    client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []

    store.save_venue(
        venue_name="Centennial Park Field 1",
        google_name="Centennial Park",
        address="100 Main St, Toronto, ON M1A 1A1, Canada",
        lat=43.7,
        lng=-79.4,
        google_place_id="ChIJ_conflict",
        confidence_score=70,
        raw_api_response={},
    )

    update_payload = client.table.return_value.update.call_args[0][0]
    assert "google_place_id" not in update_payload
