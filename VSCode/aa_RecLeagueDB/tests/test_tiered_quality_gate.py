"""Verify tiered quality gate: 25% for true children, 50% for standalone."""
from unittest.mock import MagicMock, patch
from src.database.writer import insert_league


def _make_league(pct, org="Test Org", sport="Soccer", url="https://example.com"):
    return {
        "organization_name": org,
        "sport_name": sport,
        "url_scraped": url,
        "sport_season_code": "100",
        "identifying_fields_pct": pct,
    }


@patch("src.database.writer.get_client")
@patch("src.database.writer.check_duplicate_league", return_value=None)
def test_standalone_below_50_rejected(mock_dedup, mock_client):
    league = _make_league(44)
    league_id, is_new = insert_league(league)
    assert league_id is None
    assert is_new is False


@patch("src.database.writer.get_client")
@patch("src.database.writer.check_duplicate_league", return_value=None)
def test_true_child_at_25_accepted(mock_dedup, mock_client):
    mock_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"league_id": "abc"}])
    league = _make_league(25)
    league_id, is_new = insert_league(league, is_true_child=True)
    assert league_id is not None


@patch("src.database.writer.get_client")
@patch("src.database.writer.check_duplicate_league", return_value=None)
def test_true_child_below_25_rejected(mock_dedup, mock_client):
    league = _make_league(20)
    league_id, is_new = insert_league(league, is_true_child=True)
    assert league_id is None
