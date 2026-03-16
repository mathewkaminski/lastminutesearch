"""Verify smart_crawler returns a parent_map alongside crawled_pages."""
from unittest.mock import patch, MagicMock


def _mock_fetch(url, **kwargs):
    """Return minimal YAML and metadata for any URL."""
    yaml_content = f"title: Page at {url}\nlinks: []"
    meta = {"full_text": ""}
    return yaml_content, meta


def _mock_classify(yaml_content):
    if "sports/soccer" in str(yaml_content):
        return "LEAGUE_DETAIL"
    if "programs" in str(yaml_content):
        return "LEAGUE_INDEX"
    return "OTHER"


@patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=_mock_fetch)
@patch("src.scraper.smart_crawler.classify_page", side_effect=_mock_classify)
def test_crawl_returns_parent_map(mock_classify, mock_fetch):
    from src.scraper.smart_crawler import crawl
    pages, coverage, parent_map = crawl("https://example.com")
    assert isinstance(parent_map, dict)
    # parent_map values should be strings (parent URLs)
    for child_url, parent_url in parent_map.items():
        assert isinstance(child_url, str)
        assert isinstance(parent_url, str)
