"""Tests for FirecrawlClient."""
import pytest
from unittest.mock import patch, MagicMock
from src.scraper.firecrawl_client import FirecrawlClient


def test_scrape_returns_markdown():
    """Successful scrape returns markdown string from API response."""
    client = FirecrawlClient(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "data": {"markdown": "# Ottawa Volley Sixes\nTeam fee: $875"}
    }
    with patch("requests.post", return_value=mock_response) as mock_post:
        result = client.scrape("https://example.com/register")

    assert result == "# Ottawa Volley Sixes\nTeam fee: $875"
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test-key"
    assert call_kwargs[1]["json"]["url"] == "https://example.com/register"


def test_scrape_raises_on_http_error():
    """HTTP error raises RuntimeError."""
    client = FirecrawlClient(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="Firecrawl request failed"):
            client.scrape("https://example.com")


def test_scrape_raises_on_missing_markdown():
    """API success=False raises RuntimeError."""
    client = FirecrawlClient(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"success": False, "error": "blocked"}
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="Firecrawl returned no markdown"):
            client.scrape("https://example.com")


def test_missing_api_key_raises():
    """Constructor raises if api_key is empty."""
    with pytest.raises(ValueError, match="api_key"):
        FirecrawlClient(api_key="")
