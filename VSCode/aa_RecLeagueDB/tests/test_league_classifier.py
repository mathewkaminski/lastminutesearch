import pytest
from unittest.mock import MagicMock, patch


def test_has_league_data_returns_true_when_api_says_yes():
    """Classifier returns True when Haiku responds YES."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="YES")]

    with patch("src.scraper.league_classifier.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.scraper.league_classifier import has_league_data
        result = has_league_data("- role: grid\n  name: Register Now")

    assert result is True


def test_has_league_data_returns_false_when_api_says_no():
    """Classifier returns False when Haiku responds NO."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="NO")]

    with patch("src.scraper.league_classifier.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.scraper.league_classifier import has_league_data
        result = has_league_data("- role: text\n  name: Contact Us")

    assert result is False


def test_has_league_data_returns_false_on_api_error():
    """Classifier fails safe — returns False if API call raises."""
    with patch("src.scraper.league_classifier.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("network error")
        mock_client_cls.return_value = mock_client

        from src.scraper.league_classifier import has_league_data
        result = has_league_data("some yaml content")

    assert result is False


def test_has_league_data_truncates_large_input():
    """Classifier truncates YAML to MAX_CLASSIFIER_CHARS before sending."""
    from src.scraper.league_classifier import MAX_CLASSIFIER_CHARS

    captured = {}

    def fake_create(**kwargs):
        captured["content"] = kwargs["messages"][0]["content"]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="NO")]
        return mock_response

    with patch("src.scraper.league_classifier.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = fake_create
        mock_client_cls.return_value = mock_client

        from src.scraper.league_classifier import has_league_data
        big_yaml = "x" * (MAX_CLASSIFIER_CHARS + 5000)
        has_league_data(big_yaml)

    assert len(captured["content"]) <= MAX_CLASSIFIER_CHARS + 500  # prompt overhead
