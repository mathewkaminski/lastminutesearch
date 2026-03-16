"""Unit tests for Serper API client."""

import pytest
import json
import requests
from unittest.mock import patch, MagicMock
from src.search.serper_client import SerperClient, SerperAPIError


class TestSerperClientInitialization:
    """Test SerperClient initialization and configuration."""

    def test_init_with_valid_api_key(self):
        """Test initialization with valid API key."""
        client = SerperClient(api_key="test_key_123")
        assert client.api_key == "test_key_123"
        assert client.num_results == 10
        assert client.retry_attempts == 3
        assert client.retry_backoff == 1.5

    def test_init_with_custom_parameters(self):
        """Test initialization with custom parameters."""
        client = SerperClient(
            api_key="test_key",
            num_results=25,
            retry_attempts=5,
            retry_backoff=2.0
        )
        assert client.num_results == 25
        assert client.retry_attempts == 5
        assert client.retry_backoff == 2.0

    def test_init_with_missing_api_key(self):
        """Test initialization fails without API key."""
        with pytest.raises(ValueError, match="API key is required"):
            SerperClient(api_key=None)

    def test_init_num_results_clamped(self):
        """Test num_results is clamped to valid range (1-100)."""
        # Too low
        client = SerperClient(api_key="test", num_results=0)
        assert client.num_results == 1

        # Too high
        client = SerperClient(api_key="test", num_results=500)
        assert client.num_results == 100

        # Valid
        client = SerperClient(api_key="test", num_results=50)
        assert client.num_results == 50

    def test_get_headers(self):
        """Test API headers are correctly formatted."""
        client = SerperClient(api_key="test_key_123")
        headers = client._get_headers()

        assert headers["X-API-KEY"] == "test_key_123"
        assert headers["Content-Type"] == "application/json"


class TestSerperSearch:
    """Test search execution and result normalization."""

    @patch('requests.post')
    def test_search_success(self, mock_post):
        """Test successful search returns normalized results."""
        # Mock Serper API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic": [
                {
                    "position": 0,
                    "title": "Toronto Soccer League",
                    "link": "https://tssc.ca/soccer",
                    "snippet": "Join Toronto's premier soccer league"
                },
                {
                    "position": 1,
                    "title": "Toronto FC",
                    "link": "https://torontofc.ca",
                    "snippet": "Professional soccer team"
                }
            ]
        }
        mock_post.return_value = mock_response

        client = SerperClient(api_key="test_key")
        results = client.search("Toronto soccer league")

        assert len(results) == 2
        assert results[0]["url_raw"] == "https://tssc.ca/soccer"
        assert results[0]["page_title"] == "Toronto Soccer League"
        assert results[0]["search_rank"] == 1  # position 0 -> rank 1
        assert results[1]["search_rank"] == 2  # position 1 -> rank 2

    @patch('requests.post')
    def test_search_empty_results(self, mock_post):
        """Test search with no results returns empty list."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"organic": []}
        mock_post.return_value = mock_response

        client = SerperClient(api_key="test_key")
        results = client.search("obscure query with no results")

        assert results == []

    @patch('requests.post')
    def test_search_http_error(self, mock_post):
        """Test search fails gracefully with HTTP errors."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection timeout")

        client = SerperClient(api_key="test_key", retry_attempts=1)

        with pytest.raises(SerperAPIError, match="after 1 attempt"):
            client.search("Toronto soccer league")

    @patch('requests.post')
    def test_search_retry_logic(self, mock_post):
        """Test search retries on failure and succeeds on 3rd attempt."""
        # First 2 attempts fail, 3rd succeeds
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic": [
                {"position": 0, "title": "Result", "link": "https://example.com", "snippet": "Test"}
            ]
        }

        mock_post.side_effect = [
            requests.exceptions.ConnectionError("Connection failed"),
            requests.exceptions.Timeout("Timeout"),
            mock_response  # Success on 3rd attempt
        ]

        client = SerperClient(api_key="test_key", retry_attempts=3, retry_backoff=0.1)
        results = client.search("Toronto soccer league")

        assert len(results) == 1
        assert mock_post.call_count == 3  # Called 3 times

    @patch('requests.post')
    def test_search_max_retries_exceeded(self, mock_post):
        """Test search fails after max retries exhausted."""
        mock_post.side_effect = requests.exceptions.RequestException("API Error")

        client = SerperClient(api_key="test_key", retry_attempts=3)

        with pytest.raises(SerperAPIError):
            client.search("Toronto soccer league")

        # Should have tried 3 times
        assert mock_post.call_count == 3

    @patch('requests.post')
    def test_search_validates_http_response(self, mock_post):
        """Test search validates HTTP response status."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_post.return_value = mock_response

        client = SerperClient(api_key="test_key", retry_attempts=1)

        with pytest.raises(SerperAPIError):
            client.search("Toronto soccer league")


class TestResultNormalization:
    """Test Serper API response normalization."""

    def test_normalize_result_complete(self):
        """Test normalizing a complete result."""
        client = SerperClient(api_key="test_key")
        result = {
            "position": 0,
            "title": "Toronto Soccer League",
            "link": "https://tssc.ca",
            "snippet": "Premier recreational soccer league"
        }

        normalized = client._normalize_result(result)

        assert normalized["url_raw"] == "https://tssc.ca"
        assert normalized["page_title"] == "Toronto Soccer League"
        assert normalized["page_snippet"] == "Premier recreational soccer league"
        assert normalized["search_rank"] == 1  # position 0 -> rank 1

    def test_normalize_result_position_conversion(self):
        """Test position to search_rank conversion (0-indexed to 1-indexed)."""
        client = SerperClient(api_key="test_key")

        # Test various positions
        test_cases = [
            (0, 1),   # First result
            (1, 2),   # Second result
            (4, 5),   # Fifth result
            (9, 10),  # Tenth result
        ]

        for position, expected_rank in test_cases:
            result = {
                "position": position,
                "title": f"Result {position}",
                "link": f"https://example{position}.com",
                "snippet": "Test"
            }
            normalized = client._normalize_result(result)
            assert normalized["search_rank"] == expected_rank

    def test_normalize_result_missing_link(self):
        """Test normalization fails if URL is missing."""
        client = SerperClient(api_key="test_key")
        result = {
            "position": 0,
            "title": "Title",
            # Missing 'link' field
        }

        with pytest.raises(ValueError, match="missing 'link'"):
            client._normalize_result(result)

    def test_normalize_result_missing_position(self):
        """Test normalization fails if position is missing."""
        client = SerperClient(api_key="test_key")
        result = {
            "title": "Title",
            "link": "https://example.com",
            # Missing 'position' field
        }

        with pytest.raises(ValueError, match="missing 'position'"):
            client._normalize_result(result)

    def test_normalize_result_optional_fields(self):
        """Test normalization with minimal required fields only."""
        client = SerperClient(api_key="test_key")
        result = {
            "position": 0,
            "link": "https://example.com",
            # No title or snippet
        }

        normalized = client._normalize_result(result)

        assert normalized["url_raw"] == "https://example.com"
        assert normalized["page_title"] == ""  # Default empty string
        assert normalized["page_snippet"] == ""  # Default empty string
        assert normalized["search_rank"] == 1

    @patch('requests.post')
    def test_normalize_multiple_results_with_malformed(self, mock_post):
        """Test normalizing multiple results with one malformed result."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic": [
                {
                    "position": 0,
                    "title": "Good Result",
                    "link": "https://good.com",
                    "snippet": "Valid"
                },
                {
                    "position": 1,
                    # Missing 'link' field - malformed
                    "title": "Bad Result",
                    "snippet": "Invalid"
                },
                {
                    "position": 2,
                    "title": "Another Good Result",
                    "link": "https://also-good.com",
                    "snippet": "Valid"
                }
            ]
        }
        mock_post.return_value = mock_response

        client = SerperClient(api_key="test_key")
        results = client.search("test query")

        # Should have 2 results (malformed one skipped)
        assert len(results) == 2
        assert results[0]["url_raw"] == "https://good.com"
        assert results[1]["url_raw"] == "https://also-good.com"


class TestIntegration:
    """Integration tests for SerperClient."""

    @patch('requests.post')
    def test_realistic_search_campaign(self, mock_post):
        """Test a realistic search campaign with 2 queries."""
        # Mock responses for 2 searches
        mock_response_1 = MagicMock()
        mock_response_1.json.return_value = {
            "organic": [
                {
                    "position": 0,
                    "title": "TSSC - Soccer",
                    "link": "https://tssc.ca/soccer",
                    "snippet": "Toronto Sport & Social Club soccer league"
                },
                {
                    "position": 1,
                    "title": "Toronto Soccer Community",
                    "link": "https://torontosoccer.com",
                    "snippet": "Community soccer programs"
                }
            ]
        }

        mock_response_2 = MagicMock()
        mock_response_2.json.return_value = {
            "organic": [
                {
                    "position": 0,
                    "title": "Chicago Basketball League",
                    "link": "https://chicagobasketball.com",
                    "snippet": "Premier basketball league"
                }
            ]
        }

        mock_post.side_effect = [mock_response_1, mock_response_2]

        client = SerperClient(api_key="test_key")

        # Execute 2 searches
        results_1 = client.search("Toronto soccer league")
        results_2 = client.search("Chicago basketball league")

        # Verify results
        assert len(results_1) == 2
        assert len(results_2) == 1

        # Verify first search results
        assert results_1[0]["url_raw"] == "https://tssc.ca/soccer"
        assert results_1[0]["search_rank"] == 1
        assert results_1[1]["search_rank"] == 2

        # Verify second search results
        assert results_2[0]["url_raw"] == "https://chicagobasketball.com"
        assert results_2[0]["search_rank"] == 1

        # Verify API was called twice
        assert mock_post.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
