"""Typed DB access layer for the scrape_queue table.

All Supabase calls are isolated here. The UI layer imports only from
this module — no raw client calls in Streamlit pages.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.database.supabase_client import get_client

logger = logging.getLogger(__name__)

VALID_STATUSES = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'SKIPPED']

# Columns shown in the UI table (select only what's needed)
_SELECT_COLS = (
    'scrape_id, url, status, priority, '
    'organization_name, sport_season_code, scrape_attempts, created_at'
)


def get_queue_stats() -> dict:
    """Return row counts per status for the metrics bar.

    Uses index-only COUNT queries — does not fetch row data.

    Returns:
        Dict mapping status → count, e.g. {'PENDING': 12, 'COMPLETED': 48, ...}
    """
    client = get_client()
    counts = {}
    for status in VALID_STATUSES:
        result = (
            client.table('scrape_queue')
            .select('scrape_id', count='exact')
            .eq('status', status)
            .execute()
        )
        counts[status] = result.count or 0
    return counts


def _apply_filters(query, status_filter, priority_filter, search_text):
    """Apply shared filter logic to a Supabase query builder."""
    if status_filter:
        query = query.in_('status', status_filter)
    if priority_filter:
        query = query.in_('priority', priority_filter)
    if search_text:
        # Sanitize wildcards to prevent injection
        safe = search_text.replace('%', '').replace("'", '')
        query = query.or_(
            f"url.ilike.%{safe}%,organization_name.ilike.%{safe}%"
        )
    return query


def get_queue_rows(
    status_filter: Optional[list] = None,
    priority_filter: Optional[list] = None,
    search_text: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> list:
    """Return paginated, filtered rows from scrape_queue.

    All filtering is server-side. Safe to call on 1,000+ row tables.

    Args:
        status_filter: Statuses to include, e.g. ['PENDING', 'FAILED']
        priority_filter: Priority ints to include, e.g. [1, 2]
        search_text: Matched against url OR organization_name (case-insensitive)
        offset: Row offset for pagination (page_number * page_size)
        limit: Max rows to return per page

    Returns:
        List of row dicts
    """
    client = get_client()
    query = (
        client.table('scrape_queue')
        .select(_SELECT_COLS)
        .order('priority', desc=False)
        .order('created_at', desc=False)
    )
    query = _apply_filters(query, status_filter, priority_filter, search_text)
    query = query.range(offset, offset + limit - 1)
    result = query.execute()
    return result.data or []


def get_queue_row_count(
    status_filter: Optional[list] = None,
    priority_filter: Optional[list] = None,
    search_text: Optional[str] = None,
) -> int:
    """Return total count of rows matching the given filters.

    Used for pagination math. Single index-scan COUNT query.

    Args:
        Same filters as get_queue_rows.

    Returns:
        Integer row count
    """
    client = get_client()
    query = client.table('scrape_queue').select('scrape_id', count='exact')
    query = _apply_filters(query, status_filter, priority_filter, search_text)
    result = query.execute()
    return result.count or 0


def bulk_update_status(scrape_ids: list, new_status: str) -> int:
    """Update status for a specific list of scrape_ids (checkbox selection use case).

    Args:
        scrape_ids: List of scrape_id UUIDs to update
        new_status: Target status string

    Returns:
        Number of rows updated
    """
    if not scrape_ids:
        return 0
    client = get_client()
    result = (
        client.table('scrape_queue')
        .update({'status': new_status, 'updated_at': datetime.now(timezone.utc).isoformat()})
        .in_('scrape_id', scrape_ids)
        .execute()
    )
    return len(result.data or [])


def bulk_update_by_filter(
    status_filter: Optional[list] = None,
    priority_filter: Optional[list] = None,
    search_text: Optional[str] = None,
    new_status: str = 'PENDING',
) -> int:
    """Update status for ALL rows matching current filters.

    Two DB calls: SELECT matching IDs, then UPDATE WHERE IN (ids).
    No ID list from the caller needed — works for "re-queue all FAILED" at any scale.

    Args:
        status_filter, priority_filter, search_text: Same as get_queue_rows
        new_status: Target status to set on all matching rows

    Returns:
        Number of rows updated
    """
    client = get_client()

    # Step 1: Fetch matching IDs
    id_query = client.table('scrape_queue').select('scrape_id')
    id_query = _apply_filters(id_query, status_filter, priority_filter, search_text)
    id_result = id_query.execute()
    ids = [r['scrape_id'] for r in (id_result.data or [])]

    if not ids:
        return 0

    # Step 2: Batch UPDATE
    update_result = (
        client.table('scrape_queue')
        .update({'status': new_status, 'updated_at': datetime.now(timezone.utc).isoformat()})
        .in_('scrape_id', ids)
        .execute()
    )
    return len(update_result.data or [])


def update_scrape_result(scrape_id: str, new_status: str) -> None:
    """Set status and increment scrape_attempts after a scrape job finishes.

    Two DB calls: fetch current attempts, then update status + incremented count.
    Safe for concurrent use at the small queue sizes this app targets.

    Args:
        scrape_id: UUID of the scrape_queue row
        new_status: 'COMPLETED' or 'FAILED'
    """
    client = get_client()

    # Fetch current attempt count
    row = (
        client.table('scrape_queue')
        .select('scrape_attempts')
        .eq('scrape_id', scrape_id)
        .execute()
    )
    current = (row.data[0].get('scrape_attempts') or 0) if row.data else 0

    client.table('scrape_queue').update({
        'status': new_status,
        'scrape_attempts': current + 1,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }).eq('scrape_id', scrape_id).execute()


def screen_urls(scrape_ids: list, urls: list, reason: str) -> int:
    """Delete screened URLs from scrape_queue and flag them in search_results.

    Two DB calls: DELETE from scrape_queue, then UPDATE search_results so
    the URLs won't resurface in future campaign dedup checks.

    Args:
        scrape_ids: List of scrape_id UUIDs to delete from scrape_queue
        urls: Corresponding canonical URL strings (for updating search_results)
        reason: Screening reason — one of: sub_page, social_media,
                professional_sports, manually_screened

    Returns:
        Number of rows deleted from scrape_queue
    """
    if not scrape_ids:
        return 0

    client = get_client()

    # Step 1: Delete from scrape_queue
    delete_result = (
        client.table('scrape_queue')
        .delete()
        .in_('scrape_id', scrape_ids)
        .execute()
    )
    deleted = len(delete_result.data or [])

    # Step 2: Flag in search_results so dedup checks prevent re-adding
    if urls:
        client.table('search_results').update({
            'validation_status': 'FAILED',
            'validation_reason': reason,
        }).in_('url_canonical', urls).execute()

    return deleted
