"""Store and retrieve page snapshots (YAML/HTML) in Supabase."""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse
import uuid

from src.database.supabase_client import get_client

logger = logging.getLogger(__name__)


def store_page_snapshot(
    url: str,
    content: str,
    snapshot_type: str = "playwright_yaml",
    content_format: str = "yaml",
    size_bytes: int = 0,
    token_estimate: int = 0,
    metadata: Optional[Dict] = None,
) -> str:
    """Store a page snapshot (YAML or HTML) in the database.

    Args:
        url: Source URL
        content: Raw YAML or HTML content
        snapshot_type: Type of snapshot (playwright_yaml, selenium_html, etc.)
        content_format: Format ('yaml' or 'html')
        size_bytes: Size of content in bytes
        token_estimate: Estimated token count
        metadata: Additional metadata dict

    Returns:
        UUID of stored snapshot
    """
    client = get_client()

    # Extract domain from URL
    parsed_url = urlparse(url)
    domain = parsed_url.netloc

    # Prepare metadata
    if metadata is None:
        metadata = {}

    # Ensure we have fetch_time
    if "fetch_time" not in metadata:
        metadata["fetch_time"] = datetime.now().isoformat()

    # Create insert payload
    snapshot_id = str(uuid.uuid4())

    data = {
        "id": snapshot_id,
        "url": url,
        "domain": domain,
        "snapshot_type": snapshot_type,
        "content": content,
        "content_format": content_format,
        "size_bytes": size_bytes,
        "token_estimate": token_estimate,
        "metadata": metadata,
        "extraction_status": "pending",
        "extracted_league_ids": [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    try:
        # Insert into Supabase
        response = client.table("page_snapshots").insert(data).execute()

        logger.info(f"Stored page snapshot: {snapshot_id} for {url}")
        return snapshot_id

    except Exception as e:
        logger.error(f"Failed to store page snapshot: {url}", exc_info=True)
        raise


def get_page_snapshot(snapshot_id: str) -> Optional[Dict]:
    """Retrieve a page snapshot by ID.

    Args:
        snapshot_id: UUID of snapshot

    Returns:
        Snapshot dict or None if not found
    """
    client = get_client()

    try:
        response = client.table("page_snapshots").select("*").eq("id", snapshot_id).execute()

        if response.data:
            return response.data[0]
        return None

    except Exception as e:
        logger.error(f"Failed to retrieve snapshot: {snapshot_id}", exc_info=True)
        return None


def get_snapshots_by_domain(domain: str) -> List[Dict]:
    """Get all snapshots for a domain.

    Args:
        domain: Domain name (e.g., 'ottawavolleysixes.com')

    Returns:
        List of snapshot dicts
    """
    client = get_client()

    try:
        response = (
            client.table("page_snapshots")
            .select("*")
            .eq("domain", domain)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data

    except Exception as e:
        logger.error(f"Failed to retrieve snapshots for domain: {domain}", exc_info=True)
        return []


def get_snapshots_by_url(url: str) -> List[Dict]:
    """Get all snapshots for a specific URL.

    Args:
        url: Full URL

    Returns:
        List of snapshot dicts
    """
    client = get_client()

    try:
        response = (
            client.table("page_snapshots")
            .select("*")
            .eq("url", url)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data

    except Exception as e:
        logger.error(f"Failed to retrieve snapshots for URL: {url}", exc_info=True)
        return []


def update_snapshot_status(
    snapshot_id: str,
    extraction_status: str,
    extracted_league_ids: List[str] = None,
) -> bool:
    """Update snapshot extraction status after league extraction.

    Args:
        snapshot_id: UUID of snapshot
        extraction_status: Status ('pending', 'extracted', 'failed')
        extracted_league_ids: List of league UUIDs extracted from snapshot

    Returns:
        True if successful
    """
    client = get_client()

    try:
        update_data = {
            "extraction_status": extraction_status,
            "updated_at": datetime.now().isoformat(),
        }

        if extracted_league_ids:
            update_data["extracted_league_ids"] = extracted_league_ids

        response = (
            client.table("page_snapshots")
            .update(update_data)
            .eq("id", snapshot_id)
            .execute()
        )

        logger.info(f"Updated snapshot status: {snapshot_id} -> {extraction_status}")
        return bool(response.data)

    except Exception as e:
        logger.error(f"Failed to update snapshot: {snapshot_id}", exc_info=True)
        return False


def store_gap_report(domain: str, gap_report: dict) -> None:
    """Store field coverage gap report in page_snapshots metadata for domain.

    Args:
        domain: Base domain (e.g. "ottawavolleysixes.com")
        gap_report: Output from gap_reporter.compute_field_coverage()
    """
    client = get_client()
    result = (
        client.table("page_snapshots")
        .select("id, metadata")
        .eq("domain", domain)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        row = result.data[0]
        existing_meta = row.get("metadata") or {}
        existing_meta["gap_report"] = gap_report
        client.table("page_snapshots").update(
            {"metadata": existing_meta}
        ).eq("id", row["id"]).execute()
