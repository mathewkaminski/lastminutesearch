"""Deterministic crawler: Playwright YAML + 4-way Haiku classifier.

Navigation algorithm:
  Layer 0 — Fetch start URL. Always collect (home pages carry fee/schedule data
             even when classified OTHER). If start URL is a sub-page, also fetch
             the root URL and collect it.
             If classified LEAGUE_INDEX, follow internal links.
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
from src.scraper.yaml_link_parser import parse_yaml_links, score_links, infer_link_category
from src.scraper.page_type_classifier import classify_page

logger = logging.getLogger(__name__)

MAX_DETAIL_LINKS = 30  # max unvisited same-domain links to follow from one LEAGUE_INDEX page


def _same_domain(url: str, base_url: str) -> bool:
    """True if url is on the same domain (or a subdomain) as base_url."""
    try:
        base_host = urlparse(base_url).netloc.lstrip("www.")
        link_host = urlparse(url).netloc.lstrip("www.")
        return link_host == base_host or link_host.endswith("." + base_host)
    except Exception:
        return False


def _strip_fragment(url: str) -> str:
    """Strip hash fragment from URL — treat /page and /page#section as the same resource."""
    return url.split("#")[0]


def _follow_index_links(
    index_url: str,
    index_yaml: str,
    base_url: str,
    visited: set,
    league_pages: list,
    max_index_depth: int,
    current_depth: int,
    use_cache: bool = True,
    force_refresh: bool = False,
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
        use_cache: Whether to use the page cache
        force_refresh: If True, bypass cache and re-fetch all pages
    """
    try:
        tree = yaml_lib.safe_load(index_yaml)
    except Exception:
        return

    all_links = parse_yaml_links(tree, index_url)

    # Take up to MAX_DETAIL_LINKS unique unvisited same-domain links
    candidates = []
    seen_candidates: set = set()
    for link in all_links:
        normalized = _strip_fragment(link.url)
        if normalized in visited:
            continue
        if normalized in seen_candidates:
            continue
        if not _same_domain(normalized, base_url):
            continue
        seen_candidates.add(normalized)
        link.url = normalized  # fetch the clean URL
        candidates.append(link)
        if len(candidates) >= MAX_DETAIL_LINKS:
            break

    for link in candidates:
        visited.add(link.url)  # already normalized above
        try:
            page_yaml, page_meta = fetch_page_as_yaml(link.url, use_cache=use_cache, force_refresh=force_refresh)
            page_type = classify_page(page_yaml)
            full_text = page_meta.get("full_text", "") if page_meta else ""

            if page_type in ("LEAGUE_DETAIL", "SCHEDULE"):
                logger.info(f"[Index->{page_type}] {link.url}")
                league_pages.append((link.url, page_yaml, full_text))

            elif page_type == "LEAGUE_INDEX":
                logger.info(f"[Index->INDEX depth={current_depth}] {link.url}")
                # Also collect the index page itself (partial data better than nothing)
                league_pages.append((link.url, page_yaml, full_text))
                if current_depth < max_index_depth:
                    _follow_index_links(
                        index_url=link.url,
                        index_yaml=page_yaml,
                        base_url=base_url,
                        visited=visited,
                        league_pages=league_pages,
                        max_index_depth=max_index_depth,
                        current_depth=current_depth + 1,
                        use_cache=use_cache,
                        force_refresh=force_refresh,
                    )
            # OTHER: skip

        except Exception as e:
            logger.warning(f"[Index follow] Fetch failed {link.url}: {e}")


def crawl(
    start_url: str,
    max_index_depth: int = 2,
    primary_link_min_score: int = 100,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> tuple[list[tuple[str, str, str]], dict[str, list[str]]]:
    """Crawl a sports league website, return pages confirmed to have league data.

    Args:
        start_url: Home page URL
        max_index_depth: Maximum recursion depth when following LEAGUE_INDEX pages
        primary_link_min_score: Minimum score for a link to be followed in Step A
        use_cache: Whether to use the page cache
        force_refresh: If True, bypass cache and re-fetch all pages

    Returns:
        Tuple of:
          - List of (url, yaml_content, full_text) for pages classified as
            LEAGUE_DETAIL, SCHEDULE, or LEAGUE_INDEX.
          - Dict mapping field category → list of URLs seen for that category.
    """
    if not use_cache:
        force_refresh = True

    visited: set = set()
    collected_pages: list = []
    category_coverage: dict[str, list[str]] = {
        "SCHEDULE": [],
        "REGISTRATION": [],
        "POLICY": [],
        "VENUE": [],
        "DETAIL": [],
    }

    parsed_start = urlparse(start_url)
    root_url = f"{parsed_start.scheme}://{parsed_start.netloc}/"

    # --- Layer 0: Start URL ---
    logger.info(f"Fetching start URL: {start_url}")
    home_yaml, home_meta = fetch_page_as_yaml(start_url, use_cache=use_cache, force_refresh=force_refresh)
    visited.add(_strip_fragment(start_url))
    home_full_text = home_meta.get("full_text", "") if home_meta else ""

    # Always collect start page — home pages carry fee/schedule data even when
    # classified OTHER (e.g. a login modal makes Haiku say OTHER but fee text is present).
    home_type = classify_page(home_yaml)
    logger.info(f"Start URL classified as: {home_type}")
    collected_pages.append((start_url, home_yaml, home_full_text))
    if home_type == "LEAGUE_INDEX":
        _follow_index_links(
            index_url=start_url,
            index_yaml=home_yaml,
            base_url=start_url,
            visited=visited,
            league_pages=collected_pages,
            max_index_depth=max_index_depth,
            current_depth=1,
            use_cache=use_cache,
            force_refresh=force_refresh,
        )

    # --- If start URL is a sub-page, also fetch the root ---
    root_stripped = _strip_fragment(root_url)
    if root_stripped not in visited:
        visited.add(root_stripped)
        logger.info(f"Start URL is a sub-page — also fetching root: {root_url}")
        root_yaml, root_meta = fetch_page_as_yaml(root_url, use_cache=use_cache, force_refresh=force_refresh)
        root_type = classify_page(root_yaml)
        root_full_text = root_meta.get("full_text", "") if root_meta else ""
        logger.info(f"Root classified as: {root_type}")
        collected_pages.append((root_url, root_yaml, root_full_text))
        if root_type == "LEAGUE_INDEX":
            _follow_index_links(
                index_url=root_url,
                index_yaml=root_yaml,
                base_url=root_url,
                visited=visited,
                league_pages=collected_pages,
                max_index_depth=max_index_depth,
                current_depth=1,
                use_cache=use_cache,
                force_refresh=force_refresh,
            )

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

    seen: set = {_strip_fragment(start_url)}
    primary_links = []
    for link in scored_home:
        normalized = _strip_fragment(link.url)
        if normalized in seen:
            continue
        seen.add(normalized)
        if link.score >= primary_link_min_score:
            link.url = normalized  # fetch the clean URL
            primary_links.append(link)

    logger.info(f"Home primary links: {len(primary_links)}")

    # --- Step A: Visit ALL primary links ---
    for link in primary_links:
        # Infer and record category coverage
        if link.field_category is None:
            link.field_category = infer_link_category(link.anchor_text, link.page_type)
        if link.field_category and link.field_category in category_coverage:
            category_coverage[link.field_category].append(link.url)

        if link.url in visited:
            continue
        visited.add(link.url)  # link.url is already normalized from above
        try:
            page_yaml, page_meta = fetch_page_as_yaml(link.url, use_cache=use_cache, force_refresh=force_refresh)
            page_type = classify_page(page_yaml)
            full_text = page_meta.get("full_text", "") if page_meta else ""

            if page_type in ("LEAGUE_DETAIL", "SCHEDULE"):
                logger.info(f"[Step A {page_type}] {link.url}")
                collected_pages.append((link.url, page_yaml, full_text))

            elif page_type == "LEAGUE_INDEX":
                logger.info(f"[Step A LEAGUE_INDEX] {link.url}")
                collected_pages.append((link.url, page_yaml, full_text))
                _follow_index_links(
                    index_url=link.url,
                    index_yaml=page_yaml,
                    base_url=start_url,
                    visited=visited,
                    league_pages=collected_pages,
                    max_index_depth=max_index_depth,
                    current_depth=1,
                    use_cache=use_cache,
                    force_refresh=force_refresh,
                )
            # OTHER: skip

        except Exception as e:
            logger.warning(f"[Step A] Fetch failed {link.url}: {e}")

    # Adaptive depth-3: fetch category-targeted links for uncovered categories
    uncovered = [cat for cat, urls in category_coverage.items() if not urls]
    if uncovered:
        # Get home page yaml content from collected_pages
        # The start URL is stored as `start_url` variable in crawl() — use the exact variable name
        home_yaml_content = next(
            (y for u, y, _ft in collected_pages if u == start_url), None
        )
        if home_yaml_content:
            home_tree = yaml_lib.safe_load(home_yaml_content)
            from src.scraper.yaml_link_parser import extract_navigation_links
            adaptive_links = extract_navigation_links(
                home_tree, start_url, min_score=60  # lowered threshold
            )
            visited_urls = {p[0] for p in collected_pages}
            for cat in uncovered:
                cat_links = [
                    lnk for lnk in adaptive_links
                    if lnk.field_category == cat and lnk.url not in visited_urls
                ][:3]  # max 3 per uncovered category
                for lnk in cat_links:
                    page_yaml, page_meta = fetch_page_as_yaml(
                        lnk.url,
                        use_cache=use_cache,
                        force_refresh=force_refresh,
                    )
                    if page_yaml:
                        full_text = page_meta.get("full_text", "") if page_meta else ""
                        collected_pages.append((lnk.url, page_yaml, full_text))
                        category_coverage[cat].append(lnk.url)
                        visited_urls.add(lnk.url)

    if not collected_pages:
        logger.warning(f"No league pages found for {start_url}")

    return collected_pages, category_coverage
