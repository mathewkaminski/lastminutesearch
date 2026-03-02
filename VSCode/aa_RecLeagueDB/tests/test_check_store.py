from unittest.mock import MagicMock, patch
from uuid import uuid4
from src.database.check_store import CheckStore


def make_store():
    mock_client = MagicMock()
    store = CheckStore.__new__(CheckStore)
    store.client = mock_client
    return store, mock_client


def test_save_checks_inserts_rows():
    store, mock_client = make_store()
    mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock()
    checks = [{"check_run_id": str(uuid4()), "league_id": str(uuid4()), "status": "MATCH"}]
    store.save_checks(checks)
    mock_client.table.assert_called_with("league_checks")
    mock_client.table.return_value.insert.assert_called_once_with(checks)


def test_get_checks_for_run_returns_list():
    store, mock_client = make_store()
    run_id = uuid4()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"check_id": str(uuid4()), "check_run_id": str(run_id), "status": "MATCH"}
    ]
    result = store.get_checks_for_run(run_id)
    assert len(result) == 1
    assert result[0]["status"] == "MATCH"


def test_get_latest_check_per_league_returns_list():
    store, mock_client = make_store()
    mock_client.rpc.return_value.execute.return_value.data = [
        {"league_id": str(uuid4()), "status": "CHANGED", "new_num_teams": 10}
    ]
    result = store.get_latest_check_per_league()
    assert isinstance(result, list)


def test_get_urls_with_check_age():
    store, mock_client = make_store()
    mock_client.rpc.return_value.execute.return_value.data = [
        {"url_scraped": "https://example.com", "league_count": 3, "last_checked_at": None}
    ]
    result = store.get_urls_with_check_age()
    assert result[0]["league_count"] == 3
