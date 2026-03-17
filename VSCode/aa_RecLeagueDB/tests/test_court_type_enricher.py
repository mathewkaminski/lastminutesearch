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
