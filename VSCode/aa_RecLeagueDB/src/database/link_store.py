"""Store and manage discovered links in Supabase."""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4

from src.database.supabase_client import get_client
from src.utils.domain_extractor import extract_base_domain

logger = logging.getLogger(__name__)


class LinkStore:
    """Manage discovered links in Supabase."""

    def __init__(self):
        """Initialize Supabase client."""
        self.db = get_client()

    def store_discovered_links(
        self,
        url: str,
        links: List[Dict[str, Any]],
        snapshot_id: Optional[str] = None,
        result_id: Optional[str] = None,
        url_raw: Optional[str] = None,
    ) -> List[str]:
        """Store discovered links for a URL.

        Each link is tagged with the source URL, snapshot ID, and result ID for tracking.

        Args:
            url: Source URL where links were discovered
            links: List of DiscoveredLink objects (with url, anchor_text, score, page_type)
            snapshot_id: Optional snapshot ID to link to page_snapshots table
            result_id: Optional result_id from search_results table (tracks origin)
            url_raw: Optional original URL from search_results.url_raw

        Returns:
            List of stored link IDs

        Example:
            links = extract_navigation_links(yaml_tree, url)
            link_ids = store_discovered_links(
                url, links,
                snapshot_id=snap_id,
                result_id=search_result_id,
                url_raw=original_url
            )
        """
        logger.info(f"Storing {len(links)} discovered links for {url}")
        if result_id:
            logger.info(f"  Tracking result_id: {result_id}")

        stored_ids = []

        try:
            for link in links:
                link_data = {
                    "id": str(uuid4()),
                    "source_url": url,
                    "discovered_url": link.get("url") or link.url,
                    "anchor_text": link.get("anchor_text") or getattr(link, "anchor_text", ""),
                    "score": link.get("score") or getattr(link, "score", 0),
                    "page_type": link.get("page_type") or getattr(link, "page_type", None),
                    "clickable": link.get("clickable") or getattr(link, "clickable", False),
                    "snapshot_id": snapshot_id,
                    "result_id": result_id,
                    "url_raw": url_raw,
                    "base_domain": extract_base_domain(url),
                }

                # Insert into discovered_links table
                response = self.db.table("discovered_links").insert(
                    link_data
                ).execute()

                if response.data:
                    stored_ids.append(link_data["id"])
                    logger.debug(f"Stored link: {link_data['discovered_url']}")

            logger.info(f"Successfully stored {len(stored_ids)} links")
            return stored_ids

        except Exception as e:
            logger.error(f"Error storing discovered links: {e}", exc_info=True)
            raise

    def get_links_for_url(self, source_url: str) -> List[Dict[str, Any]]:
        """Get all discovered links for a source URL.

        Args:
            source_url: Source URL to retrieve links for

        Returns:
            List of discovered link records
        """
        try:
            response = (
                self.db.table("discovered_links")
                .select("*")
                .eq("source_url", source_url)
                .order("score", desc=True)
                .execute()
            )

            return response.data if response.data else []

        except Exception as e:
            logger.error(f"Error retrieving links for {source_url}: {e}")
            return []

    def get_high_priority_links(
        self, source_url: str, min_score: int = 100
    ) -> List[Dict[str, Any]]:
        """Get high-priority discovered links (score >= min_score).

        Args:
            source_url: Source URL
            min_score: Minimum score to include (default 100)

        Returns:
            List of high-priority link records
        """
        try:
            response = (
                self.db.table("discovered_links")
                .select("*")
                .eq("source_url", source_url)
                .gte("score", min_score)
                .order("score", desc=True)
                .execute()
            )

            return response.data if response.data else []

        except Exception as e:
            logger.error(f"Error retrieving high-priority links: {e}")
            return []

    def get_links_by_page_type(
        self, source_url: str, page_type: str
    ) -> List[Dict[str, Any]]:
        """Get discovered links filtered by page type.

        Args:
            source_url: Source URL
            page_type: Page type to filter by (e.g., 'registration', 'schedule')

        Returns:
            List of matching link records
        """
        try:
            response = (
                self.db.table("discovered_links")
                .select("*")
                .eq("source_url", source_url)
                .eq("page_type", page_type)
                .order("score", desc=True)
                .execute()
            )

            return response.data if response.data else []

        except Exception as e:
            logger.error(f"Error retrieving links by page type: {e}")
            return []

    def update_link_status(
        self, link_id: str, status: str, notes: Optional[str] = None
    ) -> bool:
        """Update link processing status.

        Args:
            link_id: Link ID
            status: Status (e.g., 'pending', 'fetched', 'extracted', 'failed')
            notes: Optional notes about processing

        Returns:
            True if successful
        """
        try:
            update_data = {"status": status}
            if notes:
                update_data["notes"] = notes

            response = (
                self.db.table("discovered_links")
                .update(update_data)
                .eq("id", link_id)
                .execute()
            )

            return bool(response.data)

        except Exception as e:
            logger.error(f"Error updating link status: {e}")
            return False

    def get_unprocessed_links(
        self, source_url: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get links that haven't been processed yet (status IS NULL or 'pending').

        Args:
            source_url: Source URL
            limit: Maximum links to return

        Returns:
            List of unprocessed link records
        """
        try:
            response = (
                self.db.table("discovered_links")
                .select("*")
                .eq("source_url", source_url)
                .or_("status.is.NULL,status.eq.pending")
                .order("score", desc=True)
                .limit(limit)
                .execute()
            )

            return response.data if response.data else []

        except Exception as e:
            logger.error(f"Error retrieving unprocessed links: {e}")
            return []


# Convenience function for external use
def store_discovered_links(
    url: str, links: List[Dict[str, Any]], snapshot_id: Optional[str] = None
) -> List[str]:
    """Store discovered links to Supabase.

    Args:
        url: Source URL
        links: List of discovered links
        snapshot_id: Optional snapshot ID to link

    Returns:
        List of stored link IDs
    """
    store = LinkStore()
    return store.store_discovered_links(url, links, snapshot_id)
