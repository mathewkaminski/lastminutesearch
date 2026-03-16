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
        pages, _, _ = crawl("https://example.com/")

    assert len(pages) == 1
    assert pages[0][0] == "https://example.com/"


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
        if url == "https://example.com/":
            return (home_yaml, {})
        return (PRIMARY_LEAGUE_YAML, {})

    def fake_classify(yaml):
        return "LEAGUE_DETAIL"  # everything classifies as LEAGUE_DETAIL

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
    ):
        from src.scraper.smart_crawler import crawl
        pages, _, _ = crawl("https://example.com/")

    urls = [url for url, _yaml, _ft in pages]
    assert "https://example.com/" in urls
    assert "https://example.com/register" in urls
    assert len(pages) == 2


def test_crawl_collects_high_scoring_other_pages():
    """High-scoring primary links classified as OTHER are still collected.

    The crawler always collects the start URL, and also collects OTHER pages
    whose link anchor scored >= 100 (e.g. "Register") since the link text
    is a stronger signal than the classifier for borderline pages.
    """
    home_yaml = _make_yaml([("/register", "Register")])

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml",
              return_value=(home_yaml, {})),
        patch("src.scraper.smart_crawler.classify_page", return_value="OTHER"),
    ):
        from src.scraper.smart_crawler import crawl
        pages, _, _ = crawl("https://example.com/")

    urls = [url for url, _yaml, _ft in pages]
    assert len(pages) == 2
    assert "https://example.com/" in urls
    assert "https://example.com/register" in urls


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
        pages, _, _ = crawl("https://example.com")

    urls = [url for url, _yaml, _ft in pages]
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
        pages, _, _ = crawl("https://example.com")

    urls = [url for url, _yaml, _ft in pages]
    assert "https://example.com/about" not in urls
    assert "https://example.com/leagues" in urls


def test_crawl_deduplicates_hash_fragment_variants():
    """URLs differing only in hash fragment (#section) are treated as the same page."""
    # Home has two links to the same page — one with hash fragment, one without
    home_yaml = _make_yaml([
        ("/leagues", "Leagues"),
        ("/leagues#section", "Leagues Section"),
    ])
    visited_urls = []

    def fake_fetch(url, **kwargs):
        visited_urls.append(url)
        if url == "https://example.com":
            return (home_yaml, {})
        return (PRIMARY_LEAGUE_YAML, {})

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.classify_page", return_value="LEAGUE_DETAIL"),
    ):
        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    # /leagues should only be fetched once (not once for /leagues and once for /leagues#section)
    fetched_without_fragments = [u.split("#")[0] for u in visited_urls]
    assert fetched_without_fragments.count("https://example.com/leagues") == 1


# ---------------------------------------------------------------------------
# New tests: MAX_DETAIL_LINKS cap and category_coverage return value
# ---------------------------------------------------------------------------

class TestLinkCapAndCategoryCoverage:
    def test_max_detail_links_is_30(self):
        from src.scraper import smart_crawler
        assert smart_crawler.MAX_DETAIL_LINKS == 30

    def test_crawl_returns_category_coverage(self):
        """crawl() returns (pages, category_coverage) tuple where pages are (url, yaml, full_text) triples."""
        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml") as mock_fetch,
            patch("src.scraper.smart_crawler.classify_page") as mock_classify,
        ):
            mock_fetch.return_value = ("- role: main\n  name: Leagues", {"full_text": ""})
            mock_classify.return_value = "LEAGUE_DETAIL"

            from src.scraper.smart_crawler import crawl
            result = crawl("https://example.com")

        assert isinstance(result, tuple)
        assert len(result) == 3
        pages, coverage, parent_map = result
        assert isinstance(pages, list)
        assert len(pages[0]) == 3  # (url, yaml, full_text) triples
        assert isinstance(coverage, dict)
        assert set(coverage.keys()) == {"SCHEDULE", "REGISTRATION", "POLICY", "VENUE", "DETAIL"}

    def test_category_coverage_populated_for_visited_pages(self):
        """Pages with tagged links contribute to category_coverage."""
        home_yaml = _make_yaml([("/schedule", "Schedule"), ("/register", "Register")])

        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml") as mock_fetch,
            patch("src.scraper.smart_crawler.classify_page") as mock_classify,
        ):
            def fetch_side_effect(url, **kw):
                if url == "https://example.com":
                    return (home_yaml, {"full_text": ""})
                return ("- role: main\n  name: League Detail", {"full_text": ""})

            mock_fetch.side_effect = fetch_side_effect
            mock_classify.return_value = "LEAGUE_DETAIL"

            from src.scraper.smart_crawler import crawl
            _pages, coverage, _ = crawl("https://example.com")

        assert "https://example.com/schedule" in coverage["SCHEDULE"]
        assert "https://example.com/register" in coverage["REGISTRATION"]


# ---------------------------------------------------------------------------
# New tests: Adaptive depth-3 for uncovered categories
# ---------------------------------------------------------------------------

class TestAdaptiveDepth:
    def test_adaptive_depth_follows_category_links_when_uncovered(self):
        """When REGISTRATION has zero pages after depth-2, crawl follows reg links at depth-3."""
        home_yaml = _make_yaml([
            ("/register", "Registration"),  # would score < 100 normally
        ])
        register_yaml = "- role: main\n  name: Register for leagues"

        call_count = {"n": 0}

        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml") as mock_fetch,
            patch("src.scraper.smart_crawler.classify_page") as mock_classify,
        ):
            def fetch_side(url, **kw):
                call_count["n"] += 1
                if url == "https://example.com/":
                    return (home_yaml, {"full_text": ""})
                return (register_yaml, {"full_text": ""})

            mock_fetch.side_effect = fetch_side
            mock_classify.return_value = "LEAGUE_DETAIL"

            from src.scraper.smart_crawler import crawl
            pages, coverage, _ = crawl(
                "https://example.com/",
                primary_link_min_score=200,  # force /register to be skipped in normal pass
            )

        # The adaptive pass should have fetched /register
        fetched_urls = [p[0] for p in pages]
        assert "https://example.com/register" in fetched_urls
        assert "https://example.com/register" in coverage["REGISTRATION"]

    def test_adaptive_depth_skips_already_covered_categories(self):
        """If SCHEDULE is already covered, no extra depth-3 fetch for schedule links."""
        home_yaml = _make_yaml([
            ("/schedule", "Schedule"),
            ("/schedule2", "More Schedule"),
        ])

        fetch_calls = []

        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml") as mock_fetch,
            patch("src.scraper.smart_crawler.classify_page") as mock_classify,
        ):
            def fetch_side(url, **kw):
                fetch_calls.append(url)
                return ("- role: main\n  name: Page", {"full_text": ""})

            mock_fetch.side_effect = fetch_side
            mock_classify.return_value = "SCHEDULE"

            from src.scraper.smart_crawler import crawl
            crawl("https://example.com/", primary_link_min_score=50)

        # /schedule2 should not be fetched in an extra adaptive pass
        # (SCHEDULE is already covered by /schedule from the normal pass)
        schedule2_count = fetch_calls.count("https://example.com/schedule2")
        assert schedule2_count <= 1  # at most once from normal pass, not extra adaptive pass


# ---------------------------------------------------------------------------
# New tests: 5-way decision matrix
# ---------------------------------------------------------------------------

class TestDecisionMatrix:
    def test_league_detail_collected_regardless_of_score(self):
        """LEAGUE_DETAIL pages are always collected, even with low link scores."""
        home_yaml = _make_yaml([("/info", "Some Info")])  # low score anchor
        detail_yaml = "- role: main\n  name: League fees and registration"

        def fake_fetch(url, **kwargs):
            if url == "https://example.com":
                return (home_yaml, {})
            return (detail_yaml, {})

        def fake_classify(yaml):
            if yaml == home_yaml:
                return "LEAGUE_INDEX"
            return "LEAGUE_DETAIL"

        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
            patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
        ):
            from src.scraper.smart_crawler import crawl
            pages, _, _ = crawl("https://example.com")

        urls = [url for url, _y, _ft in pages]
        assert "https://example.com/info" in urls

    def test_league_detail_with_high_score_recurses(self):
        """LEAGUE_DETAIL pages with score >= 100 get their links followed."""
        home_yaml = _make_yaml([("/volleyball", "Court Volleyball")])  # sport keyword = 100
        detail_yaml = _make_yaml([("/event/monday", "Monday League")])
        event_yaml = "- role: main\n  name: Monday league details"

        def fake_fetch(url, **kwargs):
            if url == "https://example.com":
                return (home_yaml, {})
            if url == "https://example.com/volleyball":
                return (detail_yaml, {})
            return (event_yaml, {})

        def fake_classify(yaml):
            if yaml == home_yaml:
                return "LEAGUE_INDEX"
            return "LEAGUE_DETAIL"

        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
            patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
        ):
            from src.scraper.smart_crawler import crawl
            pages, _, _ = crawl("https://example.com")

        urls = [url for url, _y, _ft in pages]
        assert "https://example.com/volleyball" in urls
        assert "https://example.com/event/monday" in urls

    def test_medium_detail_stored_not_collected(self):
        """MEDIUM_DETAIL pages are stored via _store_scrape_detail, not in collected_pages."""
        home_yaml = _make_yaml([("/standings", "Standings")])

        def fake_fetch(url, **kwargs):
            if url == "https://example.com":
                return (home_yaml, {})
            return ("- role: main\n  name: Team Standings", {})

        def fake_classify(yaml):
            if "Standings" in str(yaml) and "Team" in str(yaml):
                return "MEDIUM_DETAIL"
            return "LEAGUE_INDEX"

        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
            patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
            patch("src.scraper.smart_crawler._store_scrape_detail") as mock_store,
        ):
            from src.scraper.smart_crawler import crawl
            pages, _, _ = crawl("https://example.com")

        urls = [url for url, _y, _ft in pages]
        assert "https://example.com/standings" not in urls
        mock_store.assert_called_once()
        call_kwargs = mock_store.call_args
        assert call_kwargs[1]["page_type"] == "MEDIUM_DETAIL" or call_kwargs[0][2] == "MEDIUM_DETAIL"

    def test_schedule_stored_not_collected(self):
        """SCHEDULE pages are stored in scrape_detail, not collected for extraction."""
        home_yaml = _make_yaml([("/games", "Games")])

        def fake_fetch(url, **kwargs):
            if url == "https://example.com":
                return (home_yaml, {})
            return ("- role: main\n  name: Game Schedule", {})

        def fake_classify(yaml):
            if "Game Schedule" in str(yaml):
                return "SCHEDULE"
            return "LEAGUE_INDEX"

        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
            patch("src.scraper.smart_crawler.classify_page", side_effect=fake_classify),
            patch("src.scraper.smart_crawler._store_scrape_detail") as mock_store,
        ):
            from src.scraper.smart_crawler import crawl
            pages, _, _ = crawl("https://example.com")

        urls = [url for url, _y, _ft in pages]
        assert "https://example.com/games" not in urls
        mock_store.assert_called_once()

    def test_other_with_high_score_collected_and_recursed(self):
        """OTHER pages with score >= 100 are collected and their links are followed."""
        home_yaml = _make_yaml([("/register", "Register")])  # "register" = 100 pts
        register_yaml = _make_yaml([("/form", "Registration Form")])
        form_yaml = "- role: main\n  name: Form"

        visited = []

        def fake_fetch(url, **kwargs):
            visited.append(url)
            if url == "https://example.com":
                return (home_yaml, {})
            if url == "https://example.com/register":
                return (register_yaml, {})
            return (form_yaml, {})

        with (
            patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
            patch("src.scraper.smart_crawler.classify_page", return_value="OTHER"),
            patch("src.scraper.smart_crawler._store_scrape_detail"),
        ):
            from src.scraper.smart_crawler import crawl
            pages, _, _ = crawl("https://example.com")

        urls = [url for url, _y, _ft in pages]
        assert "https://example.com/register" in urls
        # The links from /register should also be followed
        assert "https://example.com/form" in visited
