import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_yaml(links: list[tuple[str, str]]) -> str:
    """Build a minimal YAML snippet that yaml_link_parser can extract links from."""
    lines = ["- role: nav", "  children:"]
    for url, text in links:
        lines += [
            f"  - role: a",
            f"    name: {text}",
            f"    url: {url}",
        ]
    return "\n".join(lines)


NO_LEAGUE_YAML = _make_yaml([])
PRIMARY_LEAGUE_YAML = "- role: grid\n  name: Upcoming Leagues\n- role: row\n  name: Monday Volleyball"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_crawl_returns_home_page_when_home_has_leagues():
    """If home page itself has leagues, it should be returned."""
    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml") as mock_fetch,
        patch("src.scraper.smart_crawler.classify_page") as mock_classify,
    ):
        mock_fetch.return_value = (PRIMARY_LEAGUE_YAML, {})
        mock_classify.return_value = "LEAGUE_DETAIL"

        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    assert len(result) == 1
    assert result[0][0] == "https://example.com"


def test_crawl_visits_all_primary_links_regardless_of_early_yes():
    """Step A must visit ALL primary links even after the first YES."""
    home_yaml = _make_yaml([
        ("/register", "Register"),
        ("/schedule", "Schedule"),
        ("/standings", "Standings"),
    ])

    visited = []

    def fake_fetch(url, **kwargs):
        visited.append(url)
        if url == "https://example.com":
            return (home_yaml, {})
        return (NO_LEAGUE_YAML, {})

    def fake_classify(yaml):
        # Return LEAGUE_DETAIL for /register page (first primary), OTHER for rest
        return "LEAGUE_DETAIL" if ("/register" in visited and visited[-1] == "https://example.com/register") else "OTHER"

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    # All three primary pages must have been visited
    assert "https://example.com/register" in visited
    assert "https://example.com/schedule" in visited
    assert "https://example.com/standings" in visited


def test_crawl_does_not_visit_same_url_twice():
    """Deduplication: same URL appearing in multiple link lists is only fetched once."""
    home_yaml = _make_yaml([
        ("/register", "Register"),
        ("/register", "Register Now"),  # duplicate
    ])

    visited = []

    def fake_fetch(url, **kwargs):
        visited.append(url)
        if url == "https://example.com":
            return (home_yaml, {})
        return (NO_LEAGUE_YAML, {})

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.classify_page", return_value="OTHER"),
    ):
        from src.scraper.smart_crawler import crawl
        crawl("https://example.com")

    assert visited.count("https://example.com/register") == 1


def test_crawl_returns_home_and_primary_when_both_have_leagues():
    """When home AND a primary link both have leagues, both are returned."""
    home_yaml = _make_yaml([("/register", "Register")])

    def fake_fetch(url, **kwargs):
        if url == "https://example.com":
            return (home_yaml, {})
        return (PRIMARY_LEAGUE_YAML, {})

    def fake_classify(yaml):
        return "LEAGUE_DETAIL"  # everything classifies as LEAGUE_DETAIL

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    urls = [url for url, _ in result]
    assert "https://example.com" in urls
    assert "https://example.com/register" in urls
    assert len(result) == 2


def test_crawl_returns_empty_when_all_pages_are_other():
    """Returns [] when home and all primary pages classify as OTHER."""
    home_yaml = _make_yaml([("/register", "Register")])

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml",
              return_value=(home_yaml, {})),
        patch("src.scraper.smart_crawler.classify_page", return_value="OTHER"),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    assert result == []


# ---------------------------------------------------------------------------
# New tests: LEAGUE_INDEX following
# ---------------------------------------------------------------------------

def test_crawl_follows_detail_links_from_league_index():
    """When a primary page is LEAGUE_INDEX, its internal links are fetched and classified."""
    home_yaml = _make_yaml([("/season", "Current Season")])
    index_yaml = _make_yaml([
        ("/detail-a", "Division A"),
        ("/detail-b", "Division B"),
    ])
    detail_yaml = PRIMARY_LEAGUE_YAML

    def fake_fetch(url, **kwargs):
        if url == "https://example.com":
            return (home_yaml, {})
        if url == "https://example.com/season":
            return (index_yaml, {})
        return (detail_yaml, {})

    def fake_classify(yaml):
        if yaml == index_yaml:
            return "LEAGUE_INDEX"
        if yaml == detail_yaml:
            return "LEAGUE_DETAIL"
        return "OTHER"

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    urls = [url for url, _ in result]
    assert "https://example.com/detail-a" in urls
    assert "https://example.com/detail-b" in urls
    assert "https://example.com/season" in urls  # index page itself is also collected


def test_crawl_index_following_respects_max_index_depth():
    """LEAGUE_INDEX recursion stops at max_index_depth=1."""
    home_yaml = _make_yaml([("/season", "Current Season")])
    index_yaml = _make_yaml([("/sub-index", "Sub Index")])
    sub_index_yaml = _make_yaml([("/detail", "Detail")])
    detail_yaml = PRIMARY_LEAGUE_YAML

    def fake_fetch(url, **kwargs):
        if url == "https://example.com":
            return (home_yaml, {})
        if url == "https://example.com/season":
            return (index_yaml, {})
        if url == "https://example.com/sub-index":
            return (sub_index_yaml, {})
        return (detail_yaml, {})

    def fake_classify(yaml):
        if yaml in (index_yaml, sub_index_yaml):
            return "LEAGUE_INDEX"
        if yaml == detail_yaml:
            return "LEAGUE_DETAIL"
        return "OTHER"

    visited = []
    original_fetch = fake_fetch
    def tracking_fetch(url, **kwargs):
        visited.append(url)
        return original_fetch(url, **kwargs)

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=tracking_fetch),
        patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        crawl("https://example.com", max_index_depth=1)

    # sub-index should be visited (depth 1), but /detail inside it should NOT
    assert "https://example.com/sub-index" in visited
    assert "https://example.com/detail" not in visited


def test_crawl_skips_other_primary_pages():
    """Primary pages classified as OTHER are not added to results."""
    home_yaml = _make_yaml([
        ("/about", "About"),
        ("/leagues", "Leagues"),
    ])

    def fake_fetch(url, **kwargs):
        if url == "https://example.com":
            return (home_yaml, {})
        if url == "https://example.com/leagues":
            return (PRIMARY_LEAGUE_YAML, {})
        return (NO_LEAGUE_YAML, {})

    def fake_classify(yaml):
        if yaml == PRIMARY_LEAGUE_YAML:
            return "LEAGUE_DETAIL"
        return "OTHER"

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    urls = [url for url, _ in result]
    assert "https://example.com/about" not in urls
    assert "https://example.com/leagues" in urls
