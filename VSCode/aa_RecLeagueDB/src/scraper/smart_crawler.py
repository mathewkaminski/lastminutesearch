"""Deterministic crawler: Playwright YAML + 5-way Haiku classifier.

Navigation algorithm:
  Layer 0 — Fetch start URL. Always collect (home pages carry fee/schedule data
             even when classified OTHER). If start URL is a sub-page, also fetch
             the root URL and collect it.
             If classified LEAGUE_INDEX, follow internal links.
  Step A  — Visit ALL primary links (score >= 100). For each:
              LEAGUE_INDEX             → collect + follow internal links
              LEAGUE_DETAIL            → collect; recurse if score >= 100
              SCHEDULE / MEDIUM_DETAIL → store in scrape_detail for later
              OTHER (score >= 100)     → collect + recurse
              OTHER (score < 100)      → skip

Decision matrix (used in both _follow_index_links and Step A):
  | Classification | score >= 100       | 50 <= score < 100     | score < 50  |
  |----------------|--------------------|-----------------------|-------------|
  | LEAGUE_INDEX   | collect + recurse  | collect + recurse     | skip        |
  | LEAGUE_DETAIL  | collect + recurse  | collect (no recurse)  | skip        |
  | SCHEDULE       | store scrape_detail| store scrape_detail   | skip        |
  | MEDIUM_DETAIL  | store scrape_detail| store scrape_detail   | skip        |
  | OTHER          | collect + recurse  | skip                  | skip        |
"""

import logging
import yaml as yaml_lib
from urllib.parse import urljoin, urlparse

from src.scraper.playwright_yaml_fetcher import fetch_page_as_yaml
from src.scraper.yaml_link_parser import parse_yaml_links, score_links, infer_link_category, extract_navigation_links
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


_SKIP_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".mp4", ".mp3"}


def _is_fetchable(url: str) -> bool:
    """Return False for non-HTML resources (PDFs, images, etc.) that Playwright can't scrape."""
    path = urlparse(url).path.lower()
    return not any(path.endswith(ext) for ext in _SKIP_EXTENSIONS)


def _normalize_url(url: str) -> str:
    """Canonical URL for deduplication: https, no www, no trailing slash, no fragment."""
    url = url.split("#")[0]
    try:
        parsed = urlparse(url)
        scheme = "https"
        host = parsed.netloc.lstrip("www.")
        path = parsed.path.rstrip("/") or "/"
        query = ("?" + parsed.query) if parsed.query else ""
        return f"{scheme}://{host}{path}{query}"
    except Exception:
        return url


def _store_scrape_detail(
    parent_url: str,
    url: str,
    page_type: str,
    yaml_content: str = "",
    full_text: str = "",
) -> None:
    """Store a MEDIUM_DETAIL or SCHEDULE URL in scrape_detail for later processing.

    Looks up scrape_id from scrape_queue by matching the parent_url, then inserts
    into scrape_detail. Fails silently on DB errors (crawl should not abort).
    """
    try:
        from src.database.supabase_client import get_client
        client = get_client()

        # Look up scrape_id from scrape_queue for the parent URL
        scrape_id = None
        result = client.table("scrape_queue").select("scrape_id").eq("url", parent_url).execute()
        if result.data:
            scrape_id = result.data[0]["scrape_id"]

        record = {
            "url": url,
            "page_type": page_type,
            "parent_url": parent_url,
            "yaml_content": yaml_content,
            "full_text": full_text,
            "status": "PENDING",
        }
        if scrape_id:
            record["scrape_id"] = scrape_id

        client.table("scrape_detail").insert(record).execute()
        logger.debug(f"Stored scrape_detail: {page_type} {url}")
    except Exception as e:
        logger.warning(f"Failed to store scrape_detail for {url}: {e}")


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
    parent_map: dict = None,
    home_link_urls: set = None,
) -> None:
    """Fetch and classify internal links found on a LEAGUE_INDEX or LEAGUE_DETAIL page.

    Uses the 5-way decision matrix to collect, recurse, store, or skip each link.

    Args:
        index_url: URL of the parent page (for logging and parent_map)
        index_yaml: YAML content of the parent page
        base_url: Site root URL (for domain filtering)
        visited: Set of already-visited URLs (mutated in-place)
        league_pages: Accumulator list (mutated in-place)
        max_index_depth: Maximum recursion depth for nested indexes
        current_depth: Current recursion depth (starts at 1)
        use_cache: Whether to use the page cache
        force_refresh: If True, bypass cache and re-fetch all pages
        parent_map: Dict mapping child_url → parent_url (mutated in-place)
        home_link_urls: Set of normalized URLs from the start page (skip these on subpages)
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
        normalized = _normalize_url(link.url)
        if not _is_fetchable(normalized):
            continue
        if normalized in visited:
            continue
        if normalized in seen_candidates:
            continue
        if not _same_domain(normalized, base_url):
            continue
        # Skip links already identified as site-wide nav (handled by Step A)
        if home_link_urls and normalized in home_link_urls:
            continue
        seen_candidates.add(normalized)
        link.url = normalized  # fetch the clean URL
        candidates.append(link)
        if len(candidates) >= MAX_DETAIL_LINKS:
            break

    # Score candidates before fetching so we can use score in the decision matrix
    candidates = score_links(candidates)

    # Skip negatively-scored candidates (penalized by negative keywords like
    # "swim", "children", "fitness") — don't even fetch/classify them
    candidates = [link for link in candidates if link.score >= 0]

    for link in candidates:
        visited.add(link.url)  # already normalized above
        try:
            page_yaml, page_meta = fetch_page_as_yaml(link.url, use_cache=use_cache, force_refresh=force_refresh)
            page_type = classify_page(page_yaml)
            full_text = page_meta.get("full_text", "") if page_meta else ""

            if page_type == "LEAGUE_INDEX":
                if link.score < 50:
                    logger.debug(f"[Index->INDEX skip low-score={link.score}] {link.url}")
                    continue
                # collect + recurse
                logger.info(f"[Index->INDEX depth={current_depth}] {link.url}")
                league_pages.append((link.url, page_yaml, full_text))
                if parent_map is not None:
                    parent_map[link.url] = index_url
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
                        parent_map=parent_map,
                        home_link_urls=home_link_urls,
                    )

            elif page_type == "LEAGUE_DETAIL":
                if link.score < 50:
                    logger.debug(f"[Index->DETAIL skip low-score={link.score}] {link.url}")
                    continue
                # collect; recurse only if high-scored
                logger.info(f"[Index->DETAIL] {link.url}")
                league_pages.append((link.url, page_yaml, full_text))
                if parent_map is not None:
                    parent_map[link.url] = index_url
                if link.score >= 100 and current_depth < max_index_depth:
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
                        parent_map=parent_map,
                        home_link_urls=home_link_urls,
                    )

            elif page_type in ("SCHEDULE", "MEDIUM_DETAIL"):
                # Store in scrape_detail for later processing
                logger.info(f"[Index->{page_type}] {link.url} (saved for later)")
                _store_scrape_detail(
                    parent_url=index_url,
                    url=link.url,
                    page_type=page_type,
                    yaml_content=page_yaml,
                    full_text=full_text,
                )

            else:  # OTHER
                if link.score >= 100:
                    # High-scored OTHER — collect + recurse
                    logger.info(f"[Index->OTHER-scored] {link.url}")
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
                            parent_map=parent_map,
                            home_link_urls=home_link_urls,
                        )
                # else: skip

        except Exception as e:
            logger.warning(f"[Index follow] Fetch failed {link.url}: {e}")


def crawl(
    start_url: str,
    max_index_depth: int = 2,
    primary_link_min_score: int = 100,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> tuple[list[tuple[str, str, str]], dict[str, list[str]], dict[str, str]]:
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
          - Dict mapping detail_url → parent index_url (parent_map).
    """
    if not use_cache:
        force_refresh = True

    visited: set = set()
    collected_pages: list = []
    parent_map: dict[str, str] = {}
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
    visited.add(_normalize_url(start_url))
    home_full_text = home_meta.get("full_text", "") if home_meta else ""

    # Always collect start page — home pages carry fee/schedule data even when
    # classified OTHER (e.g. a login modal makes Haiku say OTHER but fee text is present).
    home_type = classify_page(home_yaml)
    logger.info(f"Start URL classified as: {home_type}")
    collected_pages.append((start_url, home_yaml, home_full_text))

    # --- Build home-link set so subpages don't re-follow start-page links ---
    try:
        home_tree_parsed = yaml_lib.safe_load(home_yaml)
    except Exception:
        home_tree_parsed = None
    home_link_urls: set[str] = set()
    if home_tree_parsed:
        for link in parse_yaml_links(home_tree_parsed, start_url):
            if _same_domain(link.url, start_url):
                home_link_urls.add(_normalize_url(link.url))
    if home_link_urls:
        logger.info(f"Home page has {len(home_link_urls)} internal links (will skip on subpages)")

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
            parent_map=parent_map,
            home_link_urls=home_link_urls,
        )

    # --- If start URL is a sub-page, also fetch the root ---
    root_stripped = _normalize_url(root_url)
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
                parent_map=parent_map,
                home_link_urls=home_link_urls,
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

    seen: set = {_normalize_url(start_url)}
    primary_links = []
    for link in scored_home:
        normalized = _normalize_url(link.url)
        if normalized in seen:
            continue
        seen.add(normalized)
        if link.score >= primary_link_min_score:
            link.url = normalized  # fetch the clean URL
            primary_links.append(link)

    logger.info(f"Home primary links: {len(primary_links)}")

    # --- Step A: Visit ALL primary links (same 5-way decision matrix) ---
    for link in primary_links:
        # Infer and record category coverage
        if link.field_category is None:
            link.field_category = infer_link_category(link.anchor_text, link.page_type)
        if link.field_category and link.field_category in category_coverage:
            category_coverage[link.field_category].append(link.url)

        if not _is_fetchable(link.url):
            continue
        if link.url in visited:
            continue
        visited.add(link.url)  # link.url is already normalized from above
        try:
            page_yaml, page_meta = fetch_page_as_yaml(link.url, use_cache=use_cache, force_refresh=force_refresh)
            page_type = classify_page(page_yaml)
            full_text = page_meta.get("full_text", "") if page_meta else ""

            if page_type == "LEAGUE_INDEX":
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
                    parent_map=parent_map,
                    home_link_urls=home_link_urls,
                )

            elif page_type == "LEAGUE_DETAIL":
                logger.info(f"[Step A DETAIL] {link.url}")
                collected_pages.append((link.url, page_yaml, full_text))
                # Recurse into high-scored detail pages
                if link.score >= 100:
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
                        parent_map=parent_map,
                        home_link_urls=home_link_urls,
                    )

            elif page_type in ("SCHEDULE", "MEDIUM_DETAIL"):
                logger.info(f"[Step A {page_type}] {link.url} (saved for later)")
                _store_scrape_detail(
                    parent_url=start_url,
                    url=link.url,
                    page_type=page_type,
                    yaml_content=page_yaml,
                    full_text=full_text,
                )

            else:
                # OTHER — but scored 100+ so still worth extracting from.
                logger.info(f"[Step A OTHER-scored] {link.url}")
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
                    parent_map=parent_map,
                    home_link_urls=home_link_urls,
                )

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
            adaptive_links = extract_navigation_links(
                home_tree, start_url, min_score=60  # lowered threshold
            )
            for cat in uncovered:
                cat_links = [
                    lnk for lnk in adaptive_links
                    if lnk.field_category == cat and _normalize_url(lnk.url) not in visited
                ][:3]  # max 3 per uncovered category
                for lnk in cat_links:
                    norm_url = _normalize_url(lnk.url)
                    if norm_url in visited:
                        continue
                    visited.add(norm_url)
                    page_yaml, page_meta = fetch_page_as_yaml(
                        lnk.url,
                        use_cache=use_cache,
                        force_refresh=force_refresh,
                    )
                    if page_yaml:
                        full_text = page_meta.get("full_text", "") if page_meta else ""
                        collected_pages.append((lnk.url, page_yaml, full_text))
                        category_coverage[cat].append(lnk.url)

    # --- Dedup collected_pages by normalized URL (keep first occurrence) ---
    seen_collected: set[str] = set()
    deduped: list = []
    for url, yaml_content, full_text in collected_pages:
        norm = _normalize_url(url)
        if norm not in seen_collected:
            seen_collected.add(norm)
            deduped.append((url, yaml_content, full_text))
    if len(deduped) < len(collected_pages):
        logger.info(f"Deduped collected_pages: {len(collected_pages)} → {len(deduped)}")
    collected_pages = deduped

    if not collected_pages:
        logger.warning(f"No league pages found for {start_url}")

    return collected_pages, category_coverage, parent_map
