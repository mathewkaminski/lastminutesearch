from unittest.mock import patch, MagicMock
from src.checkers.league_checker import LeagueChecker


def _make_db_leagues(quality: int) -> list[dict]:
    return [{
        "league_id": "abc-123",
        "organization_name": "Test",
        "num_teams": 8,
        "day_of_week": "Monday",
        "source_comp_level": "Rec",
        "gender_eligibility": "Mens",
        "sport_season_code": "S01",
        "quality_score": quality,
    }]


def test_high_quality_uses_standard_check():
    checker = LeagueChecker.__new__(LeagueChecker)
    with patch.object(checker, "_get_leagues_for_url", return_value=_make_db_leagues(80)), \
         patch.object(checker, "_standard_check", return_value=MagicMock()) as mock_std, \
         patch.object(checker, "_super_check") as mock_super:
        checker.check_url("https://example.com")
        mock_std.assert_called_once()
        mock_super.assert_not_called()


def test_low_quality_uses_super_check():
    checker = LeagueChecker.__new__(LeagueChecker)
    with patch.object(checker, "_get_leagues_for_url", return_value=_make_db_leagues(60)), \
         patch.object(checker, "_standard_check") as mock_std, \
         patch.object(checker, "_super_check", return_value=MagicMock()) as mock_super:
        checker.check_url("https://example.com")
        mock_super.assert_called_once()
        mock_std.assert_not_called()
