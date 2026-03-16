"""Unit tests for URL validator module."""

import pytest
from src.search.url_validator import (
    canonicalize_url,
    extract_organization_name,
    validate_url
)


class TestCanonicalizeUrl:
    """Test URL canonicalization for deduplication."""

    def test_canonicalize_removes_utm_params(self):
        """Test removing UTM tracking parameters."""
        url = "https://example.com/?utm_source=google&utm_medium=search"
        result = canonicalize_url(url)
        assert "utm_source" not in result
        assert result.startswith("https://example.com")

    def test_canonicalize_removes_fbclid(self):
        """Test removing Facebook click ID."""
        url = "https://example.com/?fbclid=abc123&other=value"
        result = canonicalize_url(url)
        assert "fbclid" not in result
        assert "other=value" in result

    def test_canonicalize_removes_gclid(self):
        """Test removing Google click ID."""
        url = "https://example.com/?gclid=xyz789"
        result = canonicalize_url(url)
        assert "gclid" not in result

    def test_canonicalize_trailing_slash(self):
        """Test removing trailing slash."""
        assert canonicalize_url("https://example.com/") == "https://example.com"
        assert canonicalize_url("https://example.com/path/") == "https://example.com/path"

    def test_canonicalize_http_to_https(self):
        """Test normalizing http to https."""
        assert canonicalize_url("http://example.com") == "https://example.com"

    def test_canonicalize_removes_www(self):
        """Test removing www. prefix."""
        assert canonicalize_url("https://www.example.com") == "https://example.com"

    def test_canonicalize_case_insensitive(self):
        """Test case normalization."""
        result = canonicalize_url("HTTPS://Example.COM/Page")
        assert result == "https://example.com/page"

    def test_canonicalize_complete_example(self):
        """Test full canonicalization with all transformations."""
        url = "http://www.example.com/?utm_source=google&fbclid=123"
        result = canonicalize_url(url)
        assert "utm_source" not in result
        assert "fbclid" not in result
        assert result.startswith("https://example.com")

    def test_canonicalize_empty_string(self):
        """Test handling empty URL."""
        assert canonicalize_url("") == ""

    def test_canonicalize_preserves_path(self):
        """Test that URL path is preserved."""
        url = "https://example.com/soccer/registration"
        result = canonicalize_url(url)
        assert "/soccer/registration" in result


class TestExtractOrganizationName:
    """Test organization name extraction."""

    def test_extract_from_domain(self):
        """Test extracting org name from domain."""
        assert extract_organization_name("https://tssc.ca", "") == "TSSC"
        assert extract_organization_name("https://volosports.com", "") == "VOLOSPORTS"

    def test_extract_from_title(self):
        """Test extracting org name from title when URL has no org domain."""
        assert extract_organization_name("", "Toronto Soccer League") == "Toronto"
        assert extract_organization_name("", "Chicago Basketball") == "Chicago"

    def test_extract_prefers_domain(self):
        """Test that domain is preferred over title."""
        result = extract_organization_name("https://tssc.ca", "Some Long Title Here")
        assert result == "TSSC"

    def test_extract_removes_www(self):
        """Test that www. is removed from domain."""
        assert extract_organization_name("https://www.tssc.ca", "") == "TSSC"

    def test_extract_title_with_dash(self):
        """Test extracting first part of title with dashes."""
        result = extract_organization_name("", "Toronto - Soccer League")
        assert result == "Toronto"

    def test_extract_empty_url_and_title(self):
        """Test with both empty."""
        assert extract_organization_name("", "") == ""

    def test_extract_handles_subdomains(self):
        """Test that subdomains are handled."""
        assert extract_organization_name("https://soccer.example.com", "") == "SOCCER"


class TestValidateUrl:
    """Test URL validation logic."""

    def test_validate_valid_league_page(self):
        """Test validation of a valid league page."""
        is_valid, reason = validate_url(
            "https://tssc.ca/soccer",
            title="TSSC Soccer League - Register Now"
        )
        assert is_valid is True
        assert reason == "valid_league_page"

    def test_validate_rejects_pdf(self):
        """Test rejecting PDF files."""
        is_valid, reason = validate_url("https://example.com/rules.pdf")
        assert is_valid is False
        assert reason == "invalid_file_type"

    def test_validate_rejects_word_doc(self):
        """Test rejecting Word documents."""
        is_valid, reason = validate_url("https://example.com/schedule.docx")
        assert is_valid is False
        assert reason == "invalid_file_type"

    def test_validate_rejects_facebook(self):
        """Test rejecting Facebook URLs."""
        is_valid, reason = validate_url("https://facebook.com/tssc-league")
        assert is_valid is False
        assert reason == "social_media"

    def test_validate_rejects_instagram(self):
        """Test rejecting Instagram URLs."""
        is_valid, reason = validate_url("https://instagram.com/soccer_league")
        assert is_valid is False
        assert reason == "social_media"

    def test_validate_rejects_yelp(self):
        """Test rejecting Yelp URLs."""
        is_valid, reason = validate_url("https://yelp.com/biz/soccer-facility")
        assert is_valid is False
        assert reason == "review_site"

    def test_validate_rejects_news_article(self):
        """Test rejecting news articles."""
        is_valid, reason = validate_url(
            "https://example.com/article",
            title="Sports News Article",
            snippet="News article about local sports"
        )
        assert is_valid is False
        assert reason == "not_league_content"

    def test_validate_rejects_equipment_shop(self):
        """Test rejecting equipment shops."""
        is_valid, reason = validate_url(
            "https://soccergear.com",
            title="Buy Soccer Equipment",
            snippet="Equipment shop for soccer"
        )
        assert is_valid is False
        assert reason == "not_league_content"

    def test_validate_with_league_keyword(self):
        """Test URL with 'league' keyword passes."""
        is_valid, reason = validate_url(
            "https://localleague.com",
            title="Local Soccer League",
            snippet="Register for our league"
        )
        assert is_valid is True

    def test_validate_with_register_keyword(self):
        """Test URL with 'register' keyword passes."""
        is_valid, reason = validate_url(
            "https://example.com",
            title="Register for Volleyball"
        )
        assert is_valid is True

    def test_validate_with_schedule_keyword(self):
        """Test URL with 'schedule' keyword passes."""
        is_valid, reason = validate_url(
            "https://example.com",
            snippet="View our schedule"
        )
        assert is_valid is True

    def test_validate_org_domain_passes(self):
        """Test that .org domains pass even without keywords."""
        is_valid, reason = validate_url("https://example.org/sports")
        assert is_valid is True

    def test_validate_com_domain_passes_without_keywords(self):
        """Test that .com domains pass even without keywords."""
        is_valid, reason = validate_url(
            "https://example.com/random-page",
            title="Random Page",
            snippet="Random content"
        )
        # .com is a valid domain extension, so it passes
        assert is_valid is True

    def test_validate_empty_url(self):
        """Test that empty URL fails."""
        is_valid, reason = validate_url("")
        assert is_valid is False

    def test_validate_case_insensitive(self):
        """Test that validation is case-insensitive."""
        is_valid, reason = validate_url(
            "https://example.com",
            title="TORONTO SOCCER LEAGUE"
        )
        assert is_valid is True

    def test_validate_multiple_keywords(self):
        """Test with multiple keywords in content."""
        is_valid, reason = validate_url(
            "https://example.com",
            title="Register for Soccer",
            snippet="View the season schedule and roster"
        )
        assert is_valid is True

    def test_validate_rejects_youth_leagues(self):
        """Test rejecting youth/minor sports organizations."""
        test_cases = [
            ("https://example.com", "U18 Boys Soccer", "District association"),
            ("https://example.com", "Minor Hockey League", ""),
            ("https://example.com", "Youth Basketball", "Rep team tryouts"),
            ("https://example.com", "Toronto Youth Soccer", "U16 division"),
        ]

        for url, title, snippet in test_cases:
            is_valid, reason = validate_url(url, title, snippet)
            assert is_valid is False, f"Failed for {title}"
            assert reason == "youth_organization", f"Expected youth_organization for {title}, got {reason}"

    def test_validate_rejects_youth_age_ranges(self):
        """Test rejecting URLs with youth age range patterns (U18, U16, etc.)."""
        test_cases = [
            ("https://example.com", "Soccer League", "U18 division"),
            ("https://example.com", "Hockey", "U16 teams"),
            ("https://example.com", "Basketball", "U12 and U14 brackets"),
        ]

        for url, title, snippet in test_cases:
            is_valid, reason = validate_url(url, title, snippet)
            assert is_valid is False, f"Failed for {snippet}"
            assert reason == "youth_organization"

    def test_validate_rejects_professional_sports(self):
        """Test rejecting professional sports teams and leagues."""
        test_cases = [
            ("https://torontofc.ca", "Toronto FC", ""),
            ("https://mlssoccer.com", "MLS Soccer", "Schedule"),
            ("https://example.com", "NBA Basketball", ""),
            ("https://example.com", "Professional Hockey", ""),
        ]

        for url, title, snippet in test_cases:
            is_valid, reason = validate_url(url, title, snippet)
            assert is_valid is False, f"Failed for {title}"
            assert reason == "professional_sports", f"Expected professional_sports for {title}, got {reason}"

    def test_validate_rejects_canadian_professional(self):
        """Test rejecting Canadian professional sports."""
        test_cases = [
            ("https://canpl.ca", "Canadian Premier League", ""),
            ("https://example.com", "CANPL Soccer", ""),
            ("https://example.com", "CF Montreal", "Professional team"),
        ]

        for url, title, snippet in test_cases:
            is_valid, reason = validate_url(url, title, snippet)
            assert is_valid is False
            assert reason == "professional_sports"

    def test_validate_detects_adult_rec_leagues(self):
        """Test detection of adult rec league indicators."""
        test_cases = [
            ("https://example.com", "Toronto Adult Coed Recreational Soccer", "Social league for adults"),
            ("https://ossc.ca/volleyball", "OSSC Adult Volleyball", "Join our coed league"),
            ("https://example.com", "Chicago Adult Rec Basketball", "Register for our league"),
        ]

        for url, title, snippet in test_cases:
            is_valid, reason = validate_url(url, title, snippet)
            assert is_valid is True, f"Failed for {title}"
            assert reason == "valid_adult_rec_league", f"Expected valid_adult_rec_league for {title}, got {reason}"

    def test_validate_generic_league_without_adult_indicators(self):
        """Test that generic leagues without adult indicators get labeled as valid_league_page."""
        is_valid, reason = validate_url(
            "https://example.com",
            title="Toronto Soccer League",
            snippet="Join our league"
        )
        assert is_valid is True
        # Without strong adult rec indicators, should be "valid_league_page" not "valid_adult_rec_league"
        assert reason == "valid_league_page"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
