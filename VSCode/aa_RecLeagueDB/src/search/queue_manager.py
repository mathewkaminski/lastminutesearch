"""Queue management: add validated URLs to scrape queue with deduplication."""

import logging
from typing import Optional
from src.database.supabase_client import get_client
from src.search.url_validator import canonicalize_url

logger = logging.getLogger(__name__)


def add_to_scrape_queue(
    result_id: str,
    url: str,
    org_name: str = None,
    priority: int = 2,
    sport_season_code: str = None
) -> bool:
    """Add validated URL to scrape queue with deduplication checks.

    Three-level deduplication:
    1. Already in scrape_queue?
    2. Already in leagues_metadata (already scraped)?
    3. If either: skip but mark result as queued anyway

    Args:
        result_id: ID from search_results table
        url: URL to add (will be canonicalized)
        org_name: Organization name (optional)
        priority: Priority 1-3
        sport_season_code: SSS code (optional)

    Returns:
        True if added, False if skipped (duplicate)
    """
    client = get_client()

    # Canonicalize URL for consistent comparison
    url_canonical = canonicalize_url(url)

    try:
        # Check 1: Already in scrape_queue with an active status?
        existing_queue = (
            client.table('scrape_queue')
            .select('scrape_id')
            .eq('url', url_canonical)
            .in_('status', ['PENDING', 'IN_PROGRESS'])
            .limit(1)
            .execute()
        )

        if existing_queue.data:
            logger.debug(f"URL already in queue: {url_canonical}")
            # Mark result as queued but don't re-add
            mark_result_queued(result_id)
            return False

        # Check 2: Already scraped (in leagues_metadata)?
        try:
            existing_scraped = client.table('leagues_metadata').select('league_id').eq(
                'url_scraped', url_canonical
            ).limit(1).execute()

            if existing_scraped.data:
                logger.debug(f"URL already scraped: {url_canonical}")
                # Mark result as queued but don't re-add
                mark_result_queued(result_id)
                return False
        except Exception as e:
            # leagues_metadata table may not exist yet (normal in early phases)
            logger.debug(f"Could not check leagues_metadata (table may not exist): {str(e)[:50]}")
            pass

        # URL is new - add to queue
        queue_data = {
            'url': url_canonical,
            'source_result_id': result_id,
            'organization_name': org_name,
            'sport_season_code': sport_season_code,
            'priority': priority,
            'status': 'PENDING',
            'scrape_attempts': 0
        }

        client.table('scrape_queue').insert(queue_data).execute()
        logger.info(f"Added to scrape queue: {url_canonical} (priority {priority})")

        # Mark result as queued
        mark_result_queued(result_id)

        return True

    except Exception as e:
        logger.error(f"Failed to add to queue: {str(e)}")
        # Still mark result as queued even if DB operation fails
        try:
            mark_result_queued(result_id)
        except:
            pass
        raise


def mark_result_queued(result_id: str) -> None:
    """Mark search result as added to queue.

    Args:
        result_id: ID from search_results table
    """
    try:
        client = get_client()
        client.table('search_results').update({
            'added_to_scrape_queue': True
        }).eq('result_id', result_id).execute()
    except Exception as e:
        logger.error(f"Failed to mark result as queued: {str(e)}")
        raise


def get_queue_status(page_size: int = None) -> dict:
    """Get summary of scrape_queue status.

    Returns:
        Dict with status counts and pending URLs
    """
    try:
        client = get_client()

        # Get status counts
        query = client.table('scrape_queue').select('status', count='exact')
        result = query.execute()

        # Parse results by status
        statuses = {}
        for status in ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'SKIPPED']:
            filtered = [r for r in result.data if r.get('status') == status]
            statuses[status] = len(filtered)

        # Get pending URLs
        pending = client.table('scrape_queue').select('url, priority').eq(
            'status', 'PENDING'
        ).order('priority', desc=False).execute()

        return {
            'status_counts': statuses,
            'pending_urls': [p['url'] for p in pending.data[:10]]  # First 10
        }

    except Exception as e:
        logger.error(f"Failed to get queue status: {str(e)}")
        return {
            'status_counts': {},
            'pending_urls': []
        }
