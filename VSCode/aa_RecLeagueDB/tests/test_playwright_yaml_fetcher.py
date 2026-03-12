"""Tests for playwright_yaml_fetcher full_text capture."""
import pytest
from unittest.mock import patch, MagicMock


def _make_pw_mock(mock_page):
    """Build a sync_playwright mock that wires up browser/context/page correctly."""
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser.new_context.return_value = mock_context

    mock_p = MagicMock()
    mock_p.chromium.launch.return_value = mock_browser

    mock_pw = MagicMock()
    mock_pw.return_value.__enter__.return_value = mock_p
    mock_pw.return_value.__exit__.return_value = False
    return mock_pw


class TestFullTextCapture:
    def test_fetch_page_as_yaml_returns_full_text_in_metadata(self):
        """fetch_page_as_yaml() includes full_text in returned metadata."""
        mock_page = MagicMock()
        # First evaluate() is _click_best_sports_tab (expects list); second is accessibility tree
        mock_page.evaluate.side_effect = [[], {"role": "main", "name": "Test"}]
        mock_page.frames = []  # no iframes
        mock_page.inner_text.return_value = "Monday Volleyball 7:00 PM 10-week season $150/team"

        with patch("src.scraper.playwright_yaml_fetcher.sync_playwright", _make_pw_mock(mock_page)):
            with patch("src.scraper.playwright_yaml_fetcher.save_yaml_to_cache"):
                with patch("src.scraper.playwright_yaml_fetcher.tiktoken"):
                    from src.scraper.playwright_yaml_fetcher import fetch_page_as_yaml
                    yaml_str, meta = fetch_page_as_yaml(
                        "https://example.com", use_cache=False
                    )

        assert "full_text" in meta
        assert "Monday Volleyball" in meta["full_text"]

    def test_full_text_truncated_at_max_chars(self):
        """full_text is truncated to max_full_text_chars."""
        mock_page = MagicMock()
        mock_page.evaluate.side_effect = [[], {"role": "main", "name": "x"}]
        mock_page.frames = []
        mock_page.inner_text.return_value = "x" * 20000

        with patch("src.scraper.playwright_yaml_fetcher.sync_playwright", _make_pw_mock(mock_page)):
            with patch("src.scraper.playwright_yaml_fetcher.save_yaml_to_cache"):
                with patch("src.scraper.playwright_yaml_fetcher.tiktoken"):
                    from src.scraper.playwright_yaml_fetcher import fetch_page_as_yaml
                    _yaml_str, meta = fetch_page_as_yaml(
                        "https://example.com",
                        use_cache=False,
                        max_full_text_chars=15000,
                    )

        assert len(meta["full_text"]) <= 15000
