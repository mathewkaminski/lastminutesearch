"""Tests for two-tier extraction in yaml_extractor."""
import pytest
from unittest.mock import patch, MagicMock


SIMPLE_YAML = """
- role: main
  name: Monday Volleyball League
  children:
  - role: heading
    name: League Details
"""

DETAIL_WITH_TEXT = """
- role: main
  name: Ottawa Volleyball Spring League
"""

FULL_TEXT_WITH_FIELDS = """
Monday Co-ed Volleyball
Season: January 6 - March 24, 2026
Start time: 7:00 PM
Game length: 60 minutes
10-week season
Team fee: $1,200
Venue: Greenwood Arena
6v6 format, refereed games
Insurance required - policy at https://example.com/insurance
Registration deadline: December 15, 2025
"""

_STUB_LEAGUE_JSON = """{
  "leagues": [{
    "organization_name": "Test Org",
    "sport_name": "Soccer",
    "season_name": "Spring",
    "sport_season_code": "111",
    "season_start_date": null,
    "season_end_date": null,
    "day_of_week": "Monday",
    "start_time": null,
    "num_weeks": null,
    "time_played_per_week": null,
    "stat_holidays": null,
    "venue_name": null,
    "competition_level": null,
    "gender_eligibility": "CoEd",
    "players_per_side": null,
    "team_fee": null,
    "individual_fee": null,
    "registration_deadline": null,
    "num_teams": null,
    "slots_left": null,
    "has_referee": null,
    "requires_insurance": null,
    "insurance_policy_link": null
  }]
}"""


def _make_fake_anthropic(captured_prompt: dict):
    """Return a mock anthropic module that captures messages sent to Claude."""
    mock_content = MagicMock()
    mock_content.text = _STUB_LEAGUE_JSON

    mock_response = MagicMock()
    mock_response.content = [mock_content]

    def fake_create(**kwargs):
        captured_prompt["messages"] = kwargs.get("messages", [])
        return mock_response

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = fake_create

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    return mock_anthropic


class TestTwoTierExtraction:
    def test_extract_without_full_text_uses_yaml_only_prompt(self):
        """When no full_text provided, prompt does not mention 'FULL PAGE TEXT'."""
        captured_prompt = {}

        import src.extractors.yaml_extractor as mod

        with patch.object(mod, "anthropic", _make_fake_anthropic(captured_prompt)):
            mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        prompt_text = str(captured_prompt["messages"])
        assert "FULL PAGE TEXT" not in prompt_text

    def test_extract_with_full_text_uses_dual_input_prompt(self):
        """When full_text provided, prompt includes 'FULL PAGE TEXT' section."""
        captured_prompt = {}

        import src.extractors.yaml_extractor as mod

        with patch.object(mod, "anthropic", _make_fake_anthropic(captured_prompt)):
            mod.extract_league_data_from_yaml(
                DETAIL_WITH_TEXT, url="http://example.com", full_text=FULL_TEXT_WITH_FIELDS
            )

        prompt_text = str(captured_prompt["messages"])
        assert "FULL PAGE TEXT" in prompt_text

    def test_output_schema_includes_insurance_policy_link(self):
        """The extraction prompt always includes insurance_policy_link in schema."""
        captured_prompt = {}

        import src.extractors.yaml_extractor as mod

        with patch.object(mod, "anthropic", _make_fake_anthropic(captured_prompt)):
            mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        prompt_text = str(captured_prompt["messages"])
        assert "insurance_policy_link" in prompt_text
