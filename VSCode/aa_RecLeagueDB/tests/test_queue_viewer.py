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


# ── update_scrape_result ─────────────────────────────────────────────────────

def test_update_scrape_result_sets_status_and_increments_attempts():
    """Sets new status and increments scrape_attempts by 1."""
    mock_client, mock_builder, _ = _make_builder(data=[{'scrape_attempts': 2}])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import update_scrape_result
        update_scrape_result('scrape-id-1', 'COMPLETED')
    mock_builder.update.assert_called_once()
    call_payload = mock_builder.update.call_args[0][0]
    assert call_payload['status'] == 'COMPLETED'
    assert call_payload['scrape_attempts'] == 3   # 2 + 1


def test_update_scrape_result_handles_null_attempts():
    """scrape_attempts=None in DB is treated as 0."""
    mock_client, mock_builder, _ = _make_builder(data=[{'scrape_attempts': None}])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import update_scrape_result
        update_scrape_result('scrape-id-1', 'FAILED')
    call_payload = mock_builder.update.call_args[0][0]
    assert call_payload['scrape_attempts'] == 1   # None → 0, then +1


# ── screen_urls ──────────────────────────────────────────────────────────────

def test_screen_urls_empty_list_returns_zero_without_db_call():
    """Empty ID list skips DB entirely."""
    mock_client, _, _ = _make_builder(data=[])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import screen_urls
        result = screen_urls([], [], 'sub_page')
    assert result == 0
    mock_client.table.assert_not_called()


def test_screen_urls_deletes_from_scrape_queue():
    """Calls .delete() on scrape_queue with matching scrape_ids."""
    ids = ['id-1', 'id-2']
    urls = ['https://a.com', 'https://b.com']
    mock_builder = MagicMock()
    for method in ['select', 'eq', 'in_', 'or_', 'order', 'range',
                   'ilike', 'update', 'delete', 'neq']:
        getattr(mock_builder, method).return_value = mock_builder
    mock_result = MagicMock()
    mock_result.data = [{'scrape_id': 'id-1'}, {'scrape_id': 'id-2'}]
    mock_result.count = 2
    mock_builder.execute.return_value = mock_result
    mock_client = MagicMock()
    mock_client.table.return_value = mock_builder

    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import screen_urls
        n = screen_urls(ids, urls, 'sub_page')

    mock_builder.delete.assert_called_once()
    mock_builder.in_.assert_any_call('scrape_id', ids)
    assert n == 2


def test_screen_urls_updates_search_results_with_reason():
    """Updates search_results validation_status and validation_reason."""
    ids = ['id-1']
    urls = ['https://a.com']
    mock_builder = MagicMock()
    for method in ['select', 'eq', 'in_', 'or_', 'order', 'range',
                   'ilike', 'update', 'delete', 'neq']:
        getattr(mock_builder, method).return_value = mock_builder
    delete_result = MagicMock()
    delete_result.data = [{'scrape_id': 'id-1'}]
    update_result = MagicMock()
    update_result.data = [{'result_id': 'r-1'}]
    mock_builder.execute.side_effect = [delete_result, update_result]
    mock_client = MagicMock()
    mock_client.table.return_value = mock_builder

    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import screen_urls
        screen_urls(ids, urls, 'social_media')

    update_calls = mock_builder.update.call_args_list
    assert len(update_calls) == 1
    payload = update_calls[0][0][0]
    assert payload['validation_status'] == 'FAILED'
    assert payload['validation_reason'] == 'social_media'
