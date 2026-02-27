"""Playwright YAML snapshot fetcher using JavaScript accessibility API.

Generates accessibility tree YAML by evaluating JavaScript in the browser.
Much smaller than raw HTML (~95% reduction).
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import yaml
import tiktoken
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path(__file__).parent.parent.parent / "scrapes"
CACHE_TTL_DAYS = 7

# JavaScript to extract accessibility tree from page
EXTRACT_ACCESSIBILITY_TREE_JS = """
(function getAccessibilityTree(element = document.documentElement) {
    const role = element.getAttribute('role') ||
                 (element.getAttribute('aria-label') ? 'generic' : null);

    const result = {
        role: role || element.tagName.toLowerCase(),
        name: element.getAttribute('aria-label') ||
              (element.textContent && element.textContent.slice(0, 100).trim()) ||
              element.getAttribute('placeholder') ||
              element.getAttribute('title') || '',
    };

    // Add aria attributes
    if (element.hasAttribute('aria-checked')) result.checked = element.getAttribute('aria-checked') === 'true';
    if (element.hasAttribute('aria-selected')) result.selected = element.getAttribute('aria-selected') === 'true';
    if (element.hasAttribute('href')) result.url = element.getAttribute('href');
    if (element.hasAttribute('aria-level')) result.level = parseInt(element.getAttribute('aria-level'));

    // Get children - skip script/style tags
    const children = [];
    for (let child of element.children) {
        if (!['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(child.tagName)) {
            const childTree = getAccessibilityTree(child);
            if (childTree.name || childTree.children) {
                children.push(childTree);
            }
        }
    }

    if (children.length > 0) {
        result.children = children;
    }

    return result;
})(document.documentElement)
"""


def fetch_page_as_yaml(
    url: str,
    use_cache: bool = True,
    force_refresh: bool = False,
    wait_time: int = 30,
) -> Tuple[str, dict]:
    """Fetch page accessibility tree as YAML using JavaScript evaluation.

    Uses Playwright to:
    1. Open the page in browser
    2. Wait for page to load
    3. Execute JavaScript to extract accessibility tree
    4. Convert to YAML

    Args:
        url: URL to fetch
        use_cache: Use cached YAML if available (default True)
        force_refresh: Re-fetch even if cached (default False)
        wait_time: Seconds to wait for page load (default 30)

    Returns:
        (yaml_content, metadata) tuple
    """
    # Check cache first
    if use_cache and not force_refresh:
        cached_yaml, cached_meta = load_yaml_from_cache(url)
        if cached_yaml is not None:
            logger.info(f"Loaded from cache: {url}")
            return cached_yaml, cached_meta

    logger.info(f"Fetching YAML snapshot: {url}")

    metadata = {
        "url": url,
        "fetch_time": datetime.now().isoformat(),
        "method": "playwright_js_eval",
        "yaml_size_bytes": 0,
        "token_estimate": 0,
        "cached": False,
    }

    try:
        with sync_playwright() as p:
            # Launch browser
            logger.info("Launching browser...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()

            # Navigate to URL — try networkidle first, fall back to load for
            # sites with persistent polling/analytics that never go quiet.
            logger.info(f"Opening: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=wait_time * 1000)
            except Exception:
                logger.info("networkidle timed out, retrying with wait_until='load'")
                page.goto(url, wait_until="load", timeout=wait_time * 1000)

            # Extract accessibility tree using JavaScript
            logger.info("Extracting accessibility tree...")
            accessibility_tree = page.evaluate(EXTRACT_ACCESSIBILITY_TREE_JS)

            # Close browser
            page.close()
            context.close()
            browser.close()

            # Convert to YAML
            yaml_content = yaml.dump(
                accessibility_tree,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )

            # Calculate metrics
            yaml_bytes = len(yaml_content.encode("utf-8"))
            enc = tiktoken.get_encoding("cl100k_base")
            tokens = len(enc.encode(yaml_content))

            metadata["yaml_size_bytes"] = yaml_bytes
            metadata["token_estimate"] = tokens

            logger.info(f"Success: {yaml_bytes:,} bytes, ~{tokens:,} tokens")

            # Cache the result
            save_yaml_to_cache(url, yaml_content, metadata)

            return yaml_content, metadata

    except Exception as e:
        logger.error(f"Failed to fetch YAML: {url}", exc_info=True)
        raise


def save_yaml_to_cache(url: str, yaml_content: str, metadata: dict) -> Path:
    """Save YAML and metadata to cache directory.

    Args:
        url: Source URL
        yaml_content: YAML content
        metadata: Metadata dict

    Returns:
        Path to saved YAML file
    """
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    path_slug = parsed_url.path.strip("/").replace("/", "_") or "home"

    domain_dir = CACHE_DIR / domain
    domain_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    yaml_path = domain_dir / f"{timestamp}_{path_slug}.yaml"
    json_path = domain_dir / f"{timestamp}_{path_slug}.json"

    yaml_path.write_text(yaml_content, encoding="utf-8")
    json_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info(f"Cached: {yaml_path}")
    return yaml_path


def load_yaml_from_cache(
    url: str, max_age_days: int = CACHE_TTL_DAYS
) -> Tuple[Optional[str], Optional[dict]]:
    """Load cached YAML if fresh.

    Args:
        url: Source URL
        max_age_days: Max cache age in days (default 7)

    Returns:
        (yaml_content, metadata) or (None, None) if not found/expired
    """
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    path_slug = parsed_url.path.strip("/").replace("/", "_") or "home"
    domain_dir = CACHE_DIR / domain

    if not domain_dir.exists():
        return None, None

    yaml_files = sorted(domain_dir.glob(f"*_{path_slug}.yaml"))
    if not yaml_files:
        return None, None

    latest_yaml = yaml_files[-1]
    latest_json = latest_yaml.with_suffix(".json")

    # Check age
    file_age = datetime.now() - datetime.fromtimestamp(latest_yaml.stat().st_mtime)
    if file_age > timedelta(days=max_age_days):
        logger.info(f"Cache expired ({file_age.days} days): {url}")
        return None, None

    # Load files
    try:
        yaml_content = latest_yaml.read_text(encoding="utf-8")
        metadata = {"cached": True, "cache_age_days": file_age.days}

        if latest_json.exists():
            cached_meta = json.loads(latest_json.read_text(encoding="utf-8"))
            metadata.update(cached_meta)

        logger.info(f"Loaded from cache ({file_age.days} days old)")
        return yaml_content, metadata

    except Exception as e:
        logger.error(f"Cache load failed: {latest_yaml}", exc_info=True)
        return None, None


def load_yaml_file(yaml_path: str) -> Tuple[str, dict]:
    """Load existing YAML file.

    Args:
        yaml_path: Path to YAML file

    Returns:
        (yaml_content, metadata) tuple
    """
    yaml_file = Path(yaml_path)
    if not yaml_file.exists():
        raise FileNotFoundError(f"File not found: {yaml_path}")

    yaml_content = yaml_file.read_text(encoding="utf-8")

    yaml_bytes = len(yaml_content.encode("utf-8"))
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = len(enc.encode(yaml_content))

    metadata = {
        "url": "(from file)",
        "fetch_time": datetime.now().isoformat(),
        "method": "file_load",
        "yaml_size_bytes": yaml_bytes,
        "token_estimate": tokens,
        "file_path": str(yaml_path),
        "cached": False,
    }

    logger.info(f"Loaded file: {yaml_bytes:,} bytes, ~{tokens:,} tokens")
    return yaml_content, metadata


def fetch_yaml_multi_page(
    url: str,
    max_pages: int = 5,
    min_link_score: int = 50,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Fetch YAML from multiple pages: home + high/medium priority links.

    Process:
    1. Fetch home page as YAML
    2. Extract links using yaml_link_parser (score >= 50)
    3. Fetch YAML for each high-priority link
    4. Return dict mapping page_type → yaml_content

    Args:
        url: Base URL
        max_pages: Maximum pages to fetch (default 5)
        min_link_score: Minimum link score to follow (default 50 = medium priority)
        use_cache: Use cached YAML if available (default True)
        force_refresh: Force refresh all pages (default False)

    Returns:
        (yaml_pages_dict, metadata) where yaml_pages_dict is:
        {
            "home": "...yaml content...",
            "registration": "...yaml content...",
            "schedule": "...yaml content...",
            ...
        }
        metadata contains aggregated info
    """
    from src.scraper.yaml_link_parser import extract_navigation_links, infer_page_type

    logger.info(f"Fetching YAML from multiple pages: {url}")

    # Step 1: Fetch home page
    home_yaml, home_meta = fetch_page_as_yaml(
        url, use_cache=use_cache, force_refresh=force_refresh
    )
    if home_yaml is None:
        raise ValueError(f"Failed to fetch home page: {url}")

    yaml_pages = {"home": home_yaml}
    total_bytes = home_meta.get("yaml_size_bytes", 0)
    total_tokens = home_meta.get("token_estimate", 0)
    pages_fetched = 1

    # Step 2: Extract links from home page
    home_tree = yaml.safe_load(home_yaml)
    links = extract_navigation_links(home_tree, url, min_score=min_link_score)

    if not links:
        logger.info("No high/medium priority links found on home page")
        return yaml_pages, {
            "url": url,
            "pages_fetched": 1,
            "total_bytes": total_bytes,
            "total_tokens": total_tokens,
            "page_types": list(yaml_pages.keys()),
        }

    logger.info(f"Found {len(links)} high/medium priority links")

    # Step 3: Fetch YAML for each link (up to max_pages - 1)
    for link in links[: max_pages - 1]:
        try:
            logger.info(f"  Fetching: {link.page_type or 'unknown'} - {link.url}")

            page_yaml, page_meta = fetch_page_as_yaml(
                link.url, use_cache=use_cache, force_refresh=force_refresh
            )

            if page_yaml is None:
                logger.warning(f"  Failed to fetch: {link.url}")
                continue

            # Determine page type (use inferred type or URL-based name)
            page_type = link.page_type or "other"

            # Avoid duplicate page types
            if page_type in yaml_pages:
                page_type = f"{page_type}_{pages_fetched}"

            yaml_pages[page_type] = page_yaml
            total_bytes += page_meta.get("yaml_size_bytes", 0)
            total_tokens += page_meta.get("token_estimate", 0)
            pages_fetched += 1

        except Exception as e:
            logger.warning(f"Error fetching {link.url}: {e}")
            continue

    logger.info(
        f"Fetched {pages_fetched} pages, {total_bytes:,} bytes, ~{total_tokens:,} tokens"
    )

    return yaml_pages, {
        "url": url,
        "pages_fetched": pages_fetched,
        "total_bytes": total_bytes,
        "total_tokens": total_tokens,
        "page_types": list(yaml_pages.keys()),
        "method": "multi_page_yaml",
    }
