import pytest
from unittest.mock import MagicMock, patch


# ── Test helper ─────────────────────────────────────────────────────────────

def _make_builder(data=None, count=0):
    """Return (mock_client, mock_builder, mock_result).

    All chained builder methods return the same builder so any query
    chain works without additional setup.
    """
    mock_builder = MagicMock()
    for method in ['select', 'eq', 'in_', 'or_', 'order', 'range', 'ilike', 'update', 'neq']:
        getattr(mock_builder, method).return_value = mock_builder

    mock_result = MagicMock()
    mock_result.count = count
    mock_result.data = data if data is not None else []
    mock_builder.execute.return_value = mock_result

    mock_client = MagicMock()
    mock_client.table.return_value = mock_builder
    return mock_client, mock_builder, mock_result


# ── get_queue_stats ──────────────────────────────────────────────────────────

def test_get_queue_stats_returns_all_statuses():
    """Stats dict has all 5 status keys."""
    mock_client, _, _ = _make_builder(count=3)
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import get_queue_stats
        stats = get_queue_stats()
    assert set(stats.keys()) == {'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'SKIPPED'}


def test_get_queue_stats_reads_count_not_data_length():
    """Uses result.count (index scan), not len(result.data)."""
    mock_client, _, mock_result = _make_builder(count=42, data=[])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import get_queue_stats
        stats = get_queue_stats()
    assert all(v == 42 for v in stats.values())


# ── get_queue_rows ───────────────────────────────────────────────────────────

def test_get_queue_rows_returns_data():
    """Returns list of row dicts from DB."""
    rows = [
        {'scrape_id': 'id-1', 'url': 'https://a.com', 'status': 'PENDING', 'priority': 1},
        {'scrape_id': 'id-2', 'url': 'https://b.com', 'status': 'PENDING', 'priority': 2},
    ]
    mock_client, _, _ = _make_builder(data=rows)
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import get_queue_rows
        result = get_queue_rows()
    assert result == rows


def test_get_queue_rows_returns_empty_list_on_no_data():
    """Returns [] when DB returns no rows."""
    mock_client, _, _ = _make_builder(data=None)
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import get_queue_rows
        result = get_queue_rows()
    assert result == []


def test_get_queue_rows_passes_status_filter_to_db():
    """status_filter calls .in_() on the builder."""
    mock_client, mock_builder, _ = _make_builder(data=[])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import get_queue_rows
        get_queue_rows(status_filter=['PENDING', 'FAILED'])
    mock_builder.in_.assert_any_call('status', ['PENDING', 'FAILED'])


def test_get_queue_rows_passes_search_text_via_or():
    """search_text calls .or_() with ilike patterns for url and org name."""
    mock_client, mock_builder, _ = _make_builder(data=[])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import get_queue_rows
        get_queue_rows(search_text='ottawa')
    mock_builder.or_.assert_called_once()
    call_arg = mock_builder.or_.call_args[0][0]
    assert 'ottawa' in call_arg.lower()
    assert 'url' in call_arg.lower()
    assert 'organization_name' in call_arg.lower()


# ── get_queue_row_count ──────────────────────────────────────────────────────

def test_get_queue_row_count_returns_count():
    """Returns result.count as integer."""
    mock_client, _, _ = _make_builder(count=17)
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import get_queue_row_count
        assert get_queue_row_count() == 17


# ── bulk_update_status ───────────────────────────────────────────────────────

def test_bulk_update_status_empty_list_returns_zero_without_db_call():
    """Empty ID list skips DB entirely."""
    mock_client, _, _ = _make_builder(data=[])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import bulk_update_status
        result = bulk_update_status([], 'PENDING')
    assert result == 0
    mock_client.table.assert_not_called()


def test_bulk_update_status_calls_update_with_ids():
    """Calls .update() then .in_('scrape_id', ids)."""
    ids = ['id-1', 'id-2']
    rows = [{'scrape_id': 'id-1'}, {'scrape_id': 'id-2'}]
    mock_client, mock_builder, _ = _make_builder(data=rows)
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import bulk_update_status
        n = bulk_update_status(ids, 'SKIPPED')
    mock_builder.update.assert_called_once()
    mock_builder.in_.assert_any_call('scrape_id', ids)
    assert n == 2


# ── bulk_update_by_filter ────────────────────────────────────────────────────

def test_bulk_update_by_filter_returns_zero_when_no_matches():
    """No matching rows → returns 0, no UPDATE called."""
    mock_client, mock_builder, _ = _make_builder(data=[])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import bulk_update_by_filter
        result = bulk_update_by_filter(status_filter=['FAILED'], new_status='PENDING')
    assert result == 0
    mock_builder.update.assert_not_called()


def test_bulk_update_by_filter_updates_all_matched_rows():
    """SELECT ids first, then UPDATE with those ids."""
    matching = [{'scrape_id': 'id-1'}, {'scrape_id': 'id-2'}, {'scrape_id': 'id-3'}]
    updated = [{'scrape_id': 'id-1'}, {'scrape_id': 'id-2'}, {'scrape_id': 'id-3'}]

    mock_builder = MagicMock()
    for method in ['select', 'eq', 'in_', 'or_', 'order', 'range', 'ilike', 'update', 'neq']:
        getattr(mock_builder, method).return_value = mock_builder

    select_result = MagicMock()
    select_result.data = matching
    update_result = MagicMock()
    update_result.data = updated
    mock_builder.execute.side_effect = [select_result, update_result]

    mock_client = MagicMock()
    mock_client.table.return_value = mock_builder

    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import bulk_update_by_filter
        n = bulk_update_by_filter(status_filter=['FAILED'], new_status='PENDING')

    assert n == 3
