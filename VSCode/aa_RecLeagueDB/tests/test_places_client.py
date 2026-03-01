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
