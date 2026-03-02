import os
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-for-mocking")

from unittest.mock import patch, MagicMock
from src.checkers.team_count_extractor import TeamCountExtractor, TeamExtractionResult

SAMPLE_HTML = """
<table>
  <tr><td>Red Devils</td><td>3</td><td>1</td></tr>
  <tr><td>Blue Hawks</td><td>2</td><td>2</td></tr>
  <tr><td>Green Force</td><td>1</td><td>3</td></tr>
</table>
"""

EMPTY_HTML = "<div>No leagues found this season.</div>"


def mock_openai_response(team_names, division=None, season=None):
    import json
    mock = MagicMock()
    mock.choices[0].message.content = json.dumps({
        "team_names": team_names,
        "division_name": division,
        "season_identifier": season,
    })
    return mock


def test_extracts_team_names():
    extractor = TeamCountExtractor.__new__(TeamCountExtractor)
    with patch("src.checkers.team_count_extractor.openai.chat.completions.create") as mock_create:
        mock_create.return_value = mock_openai_response(
            ["Red Devils", "Blue Hawks", "Green Force"], "Division A", "Fall 2025"
        )
        result = extractor.extract(SAMPLE_HTML, url="http://example.com", nav_path=["Standings"])
    assert len(result.team_names) == 3
    assert result.division_name == "Division A"
    assert result.season_identifier == "Fall 2025"


def test_returns_empty_on_no_teams():
    extractor = TeamCountExtractor.__new__(TeamCountExtractor)
    with patch("src.checkers.team_count_extractor.openai.chat.completions.create") as mock_create:
        mock_create.return_value = mock_openai_response([])
        result = extractor.extract(EMPTY_HTML, url="http://example.com", nav_path=[])
    assert result.team_names == []
    assert result.division_name is None


def test_result_has_nav_path():
    extractor = TeamCountExtractor.__new__(TeamCountExtractor)
    with patch("src.checkers.team_count_extractor.openai.chat.completions.create") as mock_create:
        mock_create.return_value = mock_openai_response(["Team A"])
        result = extractor.extract("<p>Team A</p>", url="http://x.com", nav_path=["Standings", "Fall 2025"])
    assert result.nav_path == ["Standings", "Fall 2025"]
    assert result.url == "http://x.com"
