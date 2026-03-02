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
        {"league_id": str(uuid4()), "division_name": "Monday Coed", "num_teams": 8},
        {"league_id": str(uuid4()), "division_name": "Sunday Beach", "num_teams": 6},
    ]
    extraction = MagicMock()
    extraction.division_name = "monday coed 6v6"
    matched = match_to_db(extraction, db_leagues)
    assert matched["division_name"] == "Monday Coed"


def test_match_league_returns_none_on_no_match():
    from src.checkers.league_checker import match_to_db
    db_leagues = [{"league_id": str(uuid4()), "division_name": "Monday Coed", "num_teams": 8}]
    extraction = MagicMock()
    extraction.division_name = "Completely Unrelated Division"
    matched = match_to_db(extraction, db_leagues)
    assert matched is None
