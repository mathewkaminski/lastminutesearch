"""Deterministic BFS crawler: Playwright YAML + Haiku classifier.

Navigation algorithm:
  Step A — Visit ALL primary links (score >= 100) from home. No early exit.
            Collect every page that classifies as having leagues.
  Step B — If A found nothing: visit secondary links (score 50-99), stop at first YES.
  Step C — If A+B found nothing: BFS from primary pages following TOP link only,
            up to max_depth layers. Stop at first YES.
"""

import logging
import yaml as yaml_lib

from src.scraper.playwright_yaml_fetcher import fetch_page_as_yaml
from src.scraper.yaml_link_parser import parse_yaml_links, score_links
from src.scraper.league_classifier import has_league_data

logger = logging.getLogger(__name__)

MAX_DEPTH = 4


def crawl(start_url: str, max_depth: int = MAX_DEPTH) -> list[tuple[str, str]]:
    """Crawl a sports league website, return pages confirmed to have league data.

    Args:
        start_url: Home page URL
        max_depth: Maximum BFS depth from home (default 4)

    Returns:
        List of (url, yaml_content) for pages where classifier returned True
    """
    visited: set[str] = set()

    # --- Layer 0: Home page ---
    logger.info(f"Fetching home: {start_url}")
    home_yaml, _ = fetch_page_as_yaml(start_url)
    visited.add(start_url)

    # --- Step A: Visit ALL primary links ---
    league_pages: list[tuple[str, str]] = []

    # Check if home page itself has league data
    if has_league_data(home_yaml):
        logger.info(f"Home page has league data: {start_url}")
        league_pages.append((start_url, home_yaml))
    # Always continue to Step A

    home_tree = yaml_lib.safe_load(home_yaml)
    all_home_links = parse_yaml_links(home_tree, start_url)
    scored_home = score_links(all_home_links)

    # Deduplicate while preserving score-desc order
    seen: set[str] = {start_url}
    primary_links = []
    secondary_links = []
    for link in scored_home:
        if link.url in seen:
            continue
        seen.add(link.url)
        if link.score >= 100:
            primary_links.append(link)
        elif link.score >= 50:
            secondary_links.append(link)

    logger.info(
        f"Home links: {len(primary_links)} primary, {len(secondary_links)} secondary"
    )

    primary_page_store: list[tuple[str, str]] = []  # for Step C

    for link in primary_links:
        if link.url in visited:
            continue
        visited.add(link.url)
        try:
            page_yaml, _ = fetch_page_as_yaml(link.url)
            primary_page_store.append((link.url, page_yaml))
            if has_league_data(page_yaml):
                logger.info(f"[Step A] League page: {link.url}")
                league_pages.append((link.url, page_yaml))
        except Exception as e:
            logger.warning(f"[Step A] Fetch failed {link.url}: {e}")

    if league_pages:
        logger.info(f"Step A complete: {len(league_pages)} league page(s)")
        return league_pages

    # --- Step B: Secondary links (only if A found nothing) ---
    logger.info("Step A: no leagues. Trying secondary links...")
    for link in secondary_links:
        if link.url in visited:
            continue
        visited.add(link.url)
        try:
            page_yaml, _ = fetch_page_as_yaml(link.url)
            if has_league_data(page_yaml):
                logger.info(f"[Step B] League page: {link.url}")
                return [(link.url, page_yaml)]
        except Exception as e:
            logger.warning(f"[Step B] Fetch failed {link.url}: {e}")

    # --- Step C: Deeper BFS from primary pages, top link only ---
    logger.info("Step B: no leagues. Going deeper (BFS, top link per page)...")
    # frontier entries: (url, yaml_content, depth)
    frontier: list[tuple[str, str, int]] = [
        (url, yml, 2) for url, yml in primary_page_store
    ]

    while frontier:
        curr_url, curr_yaml, depth = frontier.pop(0)
        if depth > max_depth:
            continue
        try:
            curr_tree = yaml_lib.safe_load(curr_yaml)
        except Exception:
            continue

        curr_links = parse_yaml_links(curr_tree, curr_url)
        curr_scored = score_links(curr_links)
        top_candidates = [
            l for l in curr_scored if l.score >= 50 and l.url not in visited
        ][:1]

        for link in top_candidates:
            visited.add(link.url)
            try:
                page_yaml, _ = fetch_page_as_yaml(link.url)
                if has_league_data(page_yaml):
                    logger.info(f"[Step C, depth={depth}] League page: {link.url}")
                    return [(link.url, page_yaml)]
                frontier.append((link.url, page_yaml, depth + 1))
            except Exception as e:
                logger.warning(f"[Step C] Fetch failed {link.url}: {e}")

    logger.warning(f"No league pages found within depth {max_depth}")
    return []
