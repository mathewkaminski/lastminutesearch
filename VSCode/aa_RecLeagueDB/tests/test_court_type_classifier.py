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
