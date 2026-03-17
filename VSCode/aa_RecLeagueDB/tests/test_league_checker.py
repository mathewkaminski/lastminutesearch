from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4
from src.checkers.league_checker import LeagueChecker, compute_status


def test_compute_status_match():
    assert compute_status(old=8, new=8) == "MATCH"
    assert compute_status(old=8, new=9) == "MATCH"   # ±1 tolerance


def test_compute_status_changed():
    assert compute_status(old=8, new=12) == "CHANGED"
    assert compute_status(old=8, new=5) == "CHANGED"


def test_compute_status_no_old():
    assert compute_status(old=None, new=10) == "CHANGED"  # new data found


def test_compute_status_not_found():
    assert compute_status(old=8, new=0) == "NOT_FOUND"
    assert compute_status(old=None, new=0) == "NOT_FOUND"


def test_match_league_by_division():
    from src.checkers.league_checker import match_to_db
    db_leagues = [
        {
            "league_id": str(uuid4()),
            "day_of_week": "Monday",
            "gender_eligibility": "CoEd",
            "source_comp_level": "Recreational",
            "num_teams": 8,
        },
        {
            "league_id": str(uuid4()),
            "day_of_week": "Sunday",
            "gender_eligibility": "Mens",
            "source_comp_level": "Competitive",
            "num_teams": 6,
        },
    ]
    extraction = MagicMock()
    extraction.division_name = "Monday CoEd Recreational"
    matched = match_to_db(extraction, db_leagues)
    assert matched is not None
    assert matched["day_of_week"] == "Monday"
    assert matched["gender_eligibility"] == "CoEd"


def test_match_league_returns_none_on_no_match():
    from src.checkers.league_checker import match_to_db
    db_leagues = [{
        "league_id": str(uuid4()),
        "day_of_week": "Monday",
        "gender_eligibility": "CoEd",
        "source_comp_level": "Recreational",
        "num_teams": 8,
    }]
    extraction = MagicMock()
    extraction.division_name = "Completely Unrelated Division"
    matched = match_to_db(extraction, db_leagues)
    assert matched is None


def test_standard_check_writes_back_changed_num_teams():
    """CHANGED checks with a matched league_id must update leagues_metadata."""
    from src.checkers.league_checker import LeagueChecker

    fake_league_id = str(uuid4())
    fake_check = {
        "check_run_id": str(uuid4()),
        "league_id": fake_league_id,
        "status": "CHANGED",
        "old_num_teams": 5,
        "new_num_teams": 9,
        "division_name": "Monday CoEd",
        "nav_path": [],
        "screenshot_paths": [],
        "url_checked": "https://example.com",
        "raw_teams": ["Team A"] * 9,
    }
    fake_result = MagicMock()
    fake_result.checks = [fake_check]

    with patch("src.checkers.league_checker.CheckStore"), \
         patch("src.checkers.league_checker.PlaywrightNavigator"), \
         patch("src.checkers.league_checker.TeamCountExtractor"), \
         patch("src.checkers.league_checker.get_client"), \
         patch("src.checkers.league_checker.update_num_teams") as mock_update:

        checker = LeagueChecker()
        with patch.object(checker, "_standard_check_async", new=AsyncMock(return_value=fake_result)):
            checker._standard_check("https://example.com", [], None)

        mock_update.assert_called_once_with(fake_league_id, 9)
