"""Deep crawler — aggressive settings for super scraper Pass 1."""
from __future__ import annotations
import logging
from src.scraper.smart_crawler import crawl

logger = logging.getLogger(__name__)


def deep_crawl(start_url: str) -> list[tuple[str, str]]:
    """Crawl with depth=4, lowered link threshold, and cache bypass.

    Returns list of (url, yaml_content) same as crawl().
    Returns empty list on any failure (caller decides how to handle).
    """
    try:
        return crawl(
            start_url,
            max_index_depth=4,
            primary_link_min_score=60,
            force_refresh=True,
        )
    except Exception as e:
        logger.error(f"deep_crawl failed for {start_url}: {e}")
        return []
