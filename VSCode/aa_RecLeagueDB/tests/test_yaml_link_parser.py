"""Tests for yaml_link_parser module."""

import pytest
from src.scraper.yaml_link_parser import (
    DiscoveredLink, infer_link_category, score_links, _SPORT_KEYWORDS,
)


class TestFieldCategory:
    def test_schedule_link_gets_schedule_category(self):
        assert infer_link_category("schedule", "standings") == "SCHEDULE"

    def test_registration_link_gets_registration_category(self):
        assert infer_link_category("registration", "registration") == "REGISTRATION"

    def test_rules_link_gets_policy_category(self):
        assert infer_link_category("rules", "rules") == "POLICY"

    def test_insurance_text_gets_policy_category(self):
        assert infer_link_category("insurance info", None) == "POLICY"

    def test_venue_text_gets_venue_category(self):
        assert infer_link_category("gym locations", None) == "VENUE"

    def test_league_list_gets_detail_category(self):
        assert infer_link_category("spring leagues", "league_list") == "DETAIL"

    def test_join_text_gets_detail_category(self):
        assert infer_link_category("join now", None) == "DETAIL"

    def test_home_link_gets_none_category(self):
        assert infer_link_category("home", None) is None

    def test_discovered_link_has_field_category_attribute(self):
        link = DiscoveredLink(url="https://example.com", anchor_text="schedule")
        assert hasattr(link, "field_category")
        assert link.field_category is None  # default None before scoring


class TestSportKeywords:
    def test_sport_keywords_contains_expected_sports(self):
        expected = {"volleyball", "basketball", "soccer", "dodgeball",
                    "hockey", "lacrosse", "softball", "football", "rugby",
                    "pickleball", "badminton", "tennis", "baseball", "cricket"}
        assert expected.issubset(_SPORT_KEYWORDS)

    def test_sport_keywords_excludes_short_words(self):
        # Words <= 2 chars should be excluded
        for word in _SPORT_KEYWORDS:
            assert len(word) > 2


class TestScoring:
    def test_sport_name_link_scores_100(self):
        link = DiscoveredLink(url="https://example.com/volleyball", anchor_text="Court Volleyball")
        scored = score_links([link])
        assert scored[0].score == 100

    def test_structural_keyword_scores_100(self):
        link = DiscoveredLink(url="https://example.com/info", anchor_text="League Rules")
        scored = score_links([link])
        assert scored[0].score == 100

    def test_combined_keywords_dont_double_score(self):
        # "Volleyball League" has both a high-priority keyword ("league") and a sport keyword
        # Should only score 100, not 200
        link = DiscoveredLink(url="https://example.com/vb", anchor_text="Volleyball League")
        scored = score_links([link])
        assert scored[0].score == 100

    def test_no_keyword_scores_zero(self):
        link = DiscoveredLink(url="https://example.com/about", anchor_text="About Us")
        scored = score_links([link])
        assert scored[0].score == 0

    def test_social_media_penalized(self):
        link = DiscoveredLink(url="https://facebook.com/league", anchor_text="Our Facebook")
        scored = score_links([link])
        assert scored[0].score < 100

    def test_sport_keyword_infers_detail_category(self):
        assert infer_link_category("indoor volleyball", None) == "DETAIL"


class TestFieldCategoryIntegration:
    def test_extract_navigation_links_sets_field_category(self):
        """extract_navigation_links() sets field_category on returned DiscoveredLink objects."""
        import yaml as _yaml
        from src.scraper.yaml_link_parser import extract_navigation_links

        yaml_str = """
- role: nav
  children:
  - role: a
    name: Schedule
    url: /schedule
  - role: a
    name: Register
    url: /register
"""
        tree = _yaml.safe_load(yaml_str)
        links = extract_navigation_links(tree, "https://example.com", min_score=0)
        url_to_cat = {lnk.url: lnk.field_category for lnk in links}
        assert url_to_cat.get("https://example.com/schedule") == "SCHEDULE"
        assert url_to_cat.get("https://example.com/register") == "REGISTRATION"
