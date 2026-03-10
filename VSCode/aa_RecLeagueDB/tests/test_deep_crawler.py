from unittest.mock import patch
from src.scraper.deep_crawler import deep_crawl


def test_deep_crawl_calls_crawl_with_aggressive_settings():
    with patch("src.scraper.deep_crawler.crawl") as mock_crawl:
        mock_crawl.return_value = [("https://example.com/leagues", "yaml: content")]
        result = deep_crawl("https://example.com")
        mock_crawl.assert_called_once_with(
            "https://example.com",
            max_index_depth=4,
            primary_link_min_score=60,
            force_refresh=True,
        )
        assert result == [("https://example.com/leagues", "yaml: content")]


def test_deep_crawl_returns_empty_list_on_failure():
    with patch("src.scraper.deep_crawler.crawl", side_effect=Exception("network error")):
        result = deep_crawl("https://example.com")
        assert result == []
