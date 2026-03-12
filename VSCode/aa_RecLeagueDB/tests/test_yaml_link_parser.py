"""Tests for yaml_link_parser module."""

import pytest
from src.scraper.yaml_link_parser import DiscoveredLink, infer_link_category


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
