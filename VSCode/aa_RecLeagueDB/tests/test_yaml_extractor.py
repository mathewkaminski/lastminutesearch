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
    "source_comp_level": null,
    "standardized_comp_level": null,
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


def _make_fake_anthropic(captured_prompt: dict, response_json: str = None):
    """Return a mock anthropic module that captures messages sent to Claude."""
    mock_content = MagicMock()
    mock_content.text = response_json or _STUB_LEAGUE_JSON

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


class TestCompLevelNormalization:
    def test_fallback_fills_standardized_from_source(self):
        """When LLM returns source_comp_level but null standardized, fallback fills it."""
        stub_json = _STUB_LEAGUE_JSON.replace(
            '"source_comp_level": null',
            '"source_comp_level": "Recreational"'
        )
        captured = {}
        import src.extractors.yaml_extractor as mod
        mock = _make_fake_anthropic(captured, response_json=stub_json)

        with patch.object(mod, "anthropic", mock):
            leagues = mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        assert leagues[0]["source_comp_level"] == "Recreational"
        assert leagues[0]["standardized_comp_level"] == "C"

    def test_invalid_standardized_gets_cleared_and_fallback_runs(self):
        """When LLM returns invalid standardized (e.g., 'XY'), it gets cleared."""
        stub_json = _STUB_LEAGUE_JSON.replace(
            '"source_comp_level": null',
            '"source_comp_level": "Competitive"'
        ).replace(
            '"standardized_comp_level": null',
            '"standardized_comp_level": "XY"'
        )
        captured = {}
        import src.extractors.yaml_extractor as mod
        mock = _make_fake_anthropic(captured, response_json=stub_json)

        with patch.object(mod, "anthropic", mock):
            leagues = mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        assert leagues[0]["standardized_comp_level"] == "A"

    def test_null_comp_level_defaults_to_none_found(self):
        """When LLM returns null source_comp_level, it defaults to 'None Found' / 'A'."""
        captured = {}
        import src.extractors.yaml_extractor as mod
        mock = _make_fake_anthropic(captured, response_json=_STUB_LEAGUE_JSON)

        with patch.object(mod, "anthropic", mock):
            leagues = mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        assert leagues[0]["source_comp_level"] == "None Found"
        assert leagues[0]["standardized_comp_level"] == "A"

    def test_valid_single_letter_accepted_with_source(self):
        """When LLM returns valid single letter + source, both are preserved."""
        stub_json = _STUB_LEAGUE_JSON.replace(
            '"source_comp_level": null',
            '"source_comp_level": "Intermediate"'
        ).replace(
            '"standardized_comp_level": null',
            '"standardized_comp_level": "B"'
        )
        captured = {}
        import src.extractors.yaml_extractor as mod
        mock = _make_fake_anthropic(captured, response_json=stub_json)

        with patch.object(mod, "anthropic", mock):
            leagues = mod.extract_league_data_from_yaml(SIMPLE_YAML, url="http://example.com")

        assert leagues[0]["source_comp_level"] == "Intermediate"
        assert leagues[0]["standardized_comp_level"] == "B"
