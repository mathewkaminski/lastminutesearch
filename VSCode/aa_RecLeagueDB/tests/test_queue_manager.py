from unittest.mock import MagicMock, patch
import importlib
import src.search.queue_manager as qm
from src.database.supabase_client import reset_client


def _make_builder(data=None, count=0):
    mock_builder = MagicMock()
    # Includes 'insert' and 'limit' (used by add_to_scrape_queue) in addition
    # to the base set from test_queue_viewer._make_builder
    for method in ['select', 'eq', 'in_', 'or_', 'order', 'range',
                   'ilike', 'update', 'neq', 'insert', 'limit']:
        getattr(mock_builder, method).return_value = mock_builder
    mock_result = MagicMock()
    mock_result.count = count
    mock_result.data = data if data is not None else []
    mock_builder.execute.return_value = mock_result
    mock_client = MagicMock()
    mock_client.table.return_value = mock_builder
    return mock_client, mock_builder, mock_result


def test_add_to_queue_checks_only_pending_and_in_progress():
    """Dedup query uses .in_('status', ['PENDING', 'IN_PROGRESS'])."""
    mock_client, mock_builder, _ = _make_builder(data=[])
    with patch('src.database.supabase_client.get_client', return_value=mock_client):
        reset_client()
        importlib.reload(qm)
        qm.add_to_scrape_queue('result-1', 'https://example.com/leagues', 'TestOrg', 2)
    mock_builder.in_.assert_any_call('status', ['PENDING', 'IN_PROGRESS'])


def test_add_to_queue_skips_when_pending_exists():
    """URL already PENDING/IN_PROGRESS -> returns False (skipped)."""
    mock_client, mock_builder, _ = _make_builder(
        data=[{'scrape_id': 'existing-id'}]  # found in queue
    )
    with patch('src.database.supabase_client.get_client', return_value=mock_client):
        reset_client()
        importlib.reload(qm)
        result = qm.add_to_scrape_queue('result-1', 'https://example.com/leagues', 'TestOrg', 2)
    assert result is False
    mock_builder.insert.assert_not_called()


def test_add_to_queue_allows_when_no_active_entry():
    """URL not in queue as PENDING/IN_PROGRESS -> inserts and returns True."""
    mock_client, mock_builder, _ = _make_builder(data=[])
    with patch('src.database.supabase_client.get_client', return_value=mock_client):
        reset_client()
        importlib.reload(qm)
        result = qm.add_to_scrape_queue('result-1', 'https://example.com/leagues', 'TestOrg', 2)
    assert result is True
    mock_builder.insert.assert_called_once()
