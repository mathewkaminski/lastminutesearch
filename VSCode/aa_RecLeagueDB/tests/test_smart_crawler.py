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
        patch("src.scraper.smart_crawler.has_league_data") as mock_classify,
    ):
        mock_fetch.return_value = (PRIMARY_LEAGUE_YAML, {})
        mock_classify.return_value = True

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
        # Return True for /register page (first primary), False for rest
        return "/register" in visited and visited[-1] == "https://example.com/register"

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.has_league_data", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    # All three primary pages must have been visited
    assert "https://example.com/register" in visited
    assert "https://example.com/schedule" in visited
    assert "https://example.com/standings" in visited


def test_crawl_falls_through_to_secondary_when_primary_finds_nothing():
    """If Step A finds no leagues, Step B should visit secondary links."""
    home_yaml = _make_yaml([
        ("/register", "Register"),     # primary
        ("/divisions", "Divisions"),   # secondary
    ])

    visited = []

    def fake_fetch(url, **kwargs):
        visited.append(url)
        if url == "https://example.com":
            return (home_yaml, {})
        if url == "https://example.com/divisions":
            return (PRIMARY_LEAGUE_YAML, {})
        return (NO_LEAGUE_YAML, {})

    def fake_classify(yaml):
        return yaml == PRIMARY_LEAGUE_YAML

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.has_league_data", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    assert any(url == "https://example.com/divisions" for url, _ in result)


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
        patch("src.scraper.smart_crawler.has_league_data", return_value=False),
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
        return True  # everything classifies as YES

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.has_league_data", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    urls = [url for url, _ in result]
    assert "https://example.com" in urls
    assert "https://example.com/register" in urls
    assert len(result) == 2


def test_crawl_returns_empty_when_nothing_found_within_max_depth():
    """Returns [] when max_depth is exhausted with no leagues found."""
    # Home page has one primary link; that page has one more link, etc. — all NO.
    home_yaml = _make_yaml([("/register", "Register")])
    deep_yaml = _make_yaml([("/page2", "Teams")])

    def fake_fetch(url, **kwargs):
        if url == "https://example.com":
            return (home_yaml, {})
        return (deep_yaml, {})

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.has_league_data", return_value=False),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com", max_depth=2)

    assert result == []
