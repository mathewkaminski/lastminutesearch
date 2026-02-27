"""Deterministic crawler: Playwright YAML + 4-way Haiku classifier.

Navigation algorithm:
  Layer 0 — Fetch home. Classify. If not OTHER, collect.
  Step A  — Visit ALL primary links (score >= 100). For each:
              LEAGUE_DETAIL / SCHEDULE → collect
              LEAGUE_INDEX             → follow internal links (_follow_index_links)
              OTHER                    → skip
  No Step B (secondary), no Step C (BFS deep crawl).
"""

import logging
import yaml as yaml_lib
from urllib.parse import urlparse

from src.scraper.playwright_yaml_fetcher import fetch_page_as_yaml
from src.scraper.yaml_link_parser import parse_yaml_links, score_links
from src.scraper.page_type_classifier import classify_page

logger = logging.getLogger(__name__)

MAX_DETAIL_LINKS = 20  # max unvisited same-domain links to follow from one LEAGUE_INDEX page


def _same_domain(url: str, base_url: str) -> bool:
    """True if url is on the same domain (or a subdomain) as base_url."""
    try:
        base_host = urlparse(base_url).netloc.lstrip("www.")
        link_host = urlparse(url).netloc.lstrip("www.")
        return link_host == base_host or link_host.endswith("." + base_host)
    except Exception:
        return False


def _follow_index_links(
    index_url: str,
    index_yaml: str,
    base_url: str,
    visited: set,
    league_pages: list,
    max_index_depth: int,
    current_depth: int,
) -> None:
    """Fetch and classify internal links found on a LEAGUE_INDEX page.

    Adds LEAGUE_DETAIL and SCHEDULE pages to league_pages.
    Recurses into nested LEAGUE_INDEX pages up to max_index_depth.

    Args:
        index_url: URL of the index page (for logging)
        index_yaml: YAML content of the index page
        base_url: Site root URL (for domain filtering)
        visited: Set of already-visited URLs (mutated in-place)
        league_pages: Accumulator list (mutated in-place)
        max_index_depth: Maximum recursion depth for nested indexes
        current_depth: Current recursion depth (starts at 1)
    """
    try:
        tree = yaml_lib.safe_load(index_yaml)
    except Exception:
        return

    all_links = parse_yaml_links(tree, index_url)

    # Take up to MAX_DETAIL_LINKS unique unvisited same-domain links
    candidates = []
    for link in all_links:
        if link.url in visited:
            continue
        if not _same_domain(link.url, base_url):
            continue
        candidates.append(link)
        if len(candidates) >= MAX_DETAIL_LINKS:
            break

    for link in candidates:
        visited.add(link.url)
        try:
            page_yaml, _ = fetch_page_as_yaml(link.url)
            page_type = classify_page(page_yaml)

            if page_type in ("LEAGUE_DETAIL", "SCHEDULE"):
                logger.info(f"[Index→{page_type}] {link.url}")
                league_pages.append((link.url, page_yaml))

            elif page_type == "LEAGUE_INDEX":
                logger.info(f"[Index→INDEX depth={current_depth}] {link.url}")
                # Also collect the index page itself (partial data better than nothing)
                league_pages.append((link.url, page_yaml))
                if current_depth < max_index_depth:
                    _follow_index_links(
                        index_url=link.url,
                        index_yaml=page_yaml,
                        base_url=base_url,
                        visited=visited,
                        league_pages=league_pages,
                        max_index_depth=max_index_depth,
                        current_depth=current_depth + 1,
                    )
            # OTHER: skip

        except Exception as e:
            logger.warning(f"[Index follow] Fetch failed {link.url}: {e}")


def crawl(
    start_url: str,
    max_index_depth: int = 2,
) -> list:
    """Crawl a sports league website, return pages confirmed to have league data.

    Args:
        start_url: Home page URL
        max_index_depth: Maximum recursion depth when following LEAGUE_INDEX pages

    Returns:
        List of (url, yaml_content) for pages classified as
        LEAGUE_DETAIL, SCHEDULE, or LEAGUE_INDEX.
    """
    visited: set = set()
    league_pages: list = []

    # --- Layer 0: Home page ---
    logger.info(f"Fetching home: {start_url}")
    home_yaml, _ = fetch_page_as_yaml(start_url)
    visited.add(start_url)

    home_type = classify_page(home_yaml)
    if home_type == "LEAGUE_INDEX":
        logger.info(f"Home is LEAGUE_INDEX: {start_url}")
        league_pages.append((start_url, home_yaml))
        _follow_index_links(
            index_url=start_url,
            index_yaml=home_yaml,
            base_url=start_url,
            visited=visited,
            league_pages=league_pages,
            max_index_depth=max_index_depth,
            current_depth=1,
        )
    elif home_type in ("LEAGUE_DETAIL", "SCHEDULE"):
        logger.info(f"Home is {home_type}: {start_url}")
        league_pages.append((start_url, home_yaml))
    # OTHER: don't add home, still parse its links for primary navigation

    # --- Parse home navigation links ---
    try:
        home_tree = yaml_lib.safe_load(home_yaml)
    except Exception:
        home_tree = None

    if home_tree is not None:
        all_home_links = parse_yaml_links(home_tree, start_url)
        scored_home = score_links(all_home_links)
    else:
        scored_home = []

    seen: set = {start_url}
    primary_links = []
    for link in scored_home:
        if link.url in seen:
            continue
        seen.add(link.url)
        if link.score >= 100:
            primary_links.append(link)

    logger.info(f"Home primary links: {len(primary_links)}")

    # --- Step A: Visit ALL primary links ---
    for link in primary_links:
        if link.url in visited:
            continue
        visited.add(link.url)
        try:
            page_yaml, _ = fetch_page_as_yaml(link.url)
            page_type = classify_page(page_yaml)

            if page_type in ("LEAGUE_DETAIL", "SCHEDULE"):
                logger.info(f"[Step A {page_type}] {link.url}")
                league_pages.append((link.url, page_yaml))

            elif page_type == "LEAGUE_INDEX":
                logger.info(f"[Step A LEAGUE_INDEX] {link.url}")
                league_pages.append((link.url, page_yaml))
                _follow_index_links(
                    index_url=link.url,
                    index_yaml=page_yaml,
                    base_url=start_url,
                    visited=visited,
                    league_pages=league_pages,
                    max_index_depth=max_index_depth,
                    current_depth=1,
                )
            # OTHER: skip

        except Exception as e:
            logger.warning(f"[Step A] Fetch failed {link.url}: {e}")

    if not league_pages:
        logger.warning(f"No league pages found for {start_url}")

    return league_pages
