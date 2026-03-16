"""Playwright YAML snapshot fetcher using JavaScript accessibility API.

Generates accessibility tree YAML by evaluating JavaScript in the browser.
Much smaller than raw HTML (~95% reduction).
"""

import json
import logging
import time
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
# Rate-limit / block detection
_RATE_LIMIT_SIGNALS = [
    "rate limit",
    "too many requests",
    "access denied",
    "403 forbidden",
    "please try again later",
    "you have been blocked",
    "request blocked",
]
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 10  # seconds; doubles each retry (10, 20, 40)

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


# Tab labels to try, in priority order.
# "Standings" is preferred because it shows teams regardless of date filters.
_TAB_PRIORITY = ["standings", "teams", "schedule", "results", "divisions", "season"]


def _click_best_sports_tab(page) -> None:
    """Click the highest-priority sports tab/button found on the page.

    Looks for [role="tab"] and <button> elements whose text matches sports
    keywords. Clicks the best match and waits 1500 ms for content to update.
    Silently ignores all failures — this is a best-effort enhancement.
    """
    try:
        tabs = page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('[role="tab"], button, [role="button"]'));
            return els.map(el => ({
                text: (el.innerText || el.textContent || '').trim(),
            })).filter(e => e.text.length > 0 && e.text.length < 60);
        }""")
    except Exception:
        return

    best_label: str | None = None
    best_priority = len(_TAB_PRIORITY)  # lower index = higher priority

    for tab in tabs:
        text_lower = tab.get("text", "").lower()
        for idx, keyword in enumerate(_TAB_PRIORITY):
            if keyword in text_lower and idx < best_priority:
                best_priority = idx
                best_label = tab["text"]  # keep original case for locator
                break

    if best_label is None:
        return

    try:
        locator = page.locator(
            f'[role="tab"]:has-text("{best_label}"), button:has-text("{best_label}")'
        ).first
        locator.click(timeout=3000)
        time.sleep(1.5)  # Frame objects don't have wait_for_timeout; use time.sleep
        logger.info(f"Clicked sports tab: '{best_label}'")
    except Exception:
        pass


def _extract_iframe_yamls(page) -> list[str]:
    """Extract accessibility tree YAML from child iframes.

    Widgets like GameSheet are embedded via iframe. The outer page's
    document.documentElement does NOT include iframe content.
    This function iterates page.frames (skipping the main frame), clicks
    the best sports tab inside each frame, and returns YAML for frames
    that contain meaningful content.

    Args:
        page: Playwright sync Page object (browser must still be open)

    Returns:
        List of YAML strings, one per non-empty child frame.
    """
    results = []
    try:
        frames = page.frames[1:]  # index 0 is always the main frame
    except Exception:
        return results

    for frame in frames:
        try:
            # Skip about:blank, data: URIs, etc.
            frame_url = frame.url
            if not frame_url or frame_url in ("about:blank", "") or frame_url.startswith("data:"):
                continue

            logger.info(f"Inspecting iframe: {frame_url}")

            # Click the best sports tab inside this frame
            _click_best_sports_tab(frame)

            # Extract accessibility tree from this frame's document
            tree = frame.evaluate(EXTRACT_ACCESSIBILITY_TREE_JS)
            frame_yaml = yaml.dump(
                tree,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )

            # Only include frames that have non-trivial content
            if len(frame_yaml.strip()) > 100:
                logger.info(f"  iframe YAML: {len(frame_yaml):,} bytes")
                results.append(frame_yaml)

        except Exception as e:
            logger.debug(f"  iframe skipped ({frame_url}): {e}")
            continue

    return results


def fetch_page_as_yaml(
    url: str,
    use_cache: bool = True,
    force_refresh: bool = False,
    wait_time: int = 30,
    max_full_text_chars: int = 15000,
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
            if "full_text" not in cached_meta:
                cached_meta["full_text"] = ""
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

    last_error = None
    for attempt in range(_MAX_RETRIES):
        try:
            full_text = ""
            with sync_playwright() as p:
                # Launch browser
                logger.info("Launching browser...")
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    ignore_https_errors=True,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                )
                page = context.new_page()

                # Navigate to URL — try networkidle first, fall back to load for
                # sites with persistent polling/analytics that never go quiet.
                logger.info(f"Opening: {url}")
                response = None
                try:
                    response = page.goto(url, wait_until="networkidle", timeout=wait_time * 1000)
                except Exception:
                    logger.info("networkidle timed out, retrying with wait_until='load'")
                    response = page.goto(url, wait_until="load", timeout=wait_time * 1000)

                # Check HTTP status for rate limiting (429, 403)
                http_status = response.status if response else 0
                if http_status in (429, 403):
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"HTTP {http_status} on {url} — rate limited, "
                        f"retrying in {delay}s (attempt {attempt + 1}/{_MAX_RETRIES})"
                    )
                    page.close()
                    context.close()
                    browser.close()
                    time.sleep(delay)
                    continue

                # Detect and wait for Cloudflare challenge to resolve
                for cf_attempt in range(6):  # up to ~15s
                    title = page.title() or ""
                    if "just a moment" not in title.lower():
                        break
                    logger.info(f"Cloudflare challenge detected, waiting... (attempt {cf_attempt + 1})")
                    page.wait_for_timeout(2500)

                # Extra wait for SPAs that render data after initial load
                page.wait_for_timeout(3000)

                # Try to click sports-relevant tabs before capturing —
                # e.g. GameSheet defaults to Schedule (shows "no matching games" for
                # today's date), but Standings always shows teams regardless of date.
                _click_best_sports_tab(page)

                # Extract accessibility tree using JavaScript
                logger.info("Extracting accessibility tree...")
                accessibility_tree = page.evaluate(EXTRACT_ACCESSIBILITY_TREE_JS)

                # Capture full rendered text for Tier-2 extraction
                # MUST be before page.close()
                try:
                    full_text = page.inner_text("body") or ""
                    if max_full_text_chars and len(full_text) > max_full_text_chars:
                        full_text = full_text[:max_full_text_chars]
                except Exception:
                    full_text = ""

                # --- Rate limit / block detection on page content ---
                body_lower = full_text.lower() if full_text else ""
                tree_name = ""
                if isinstance(accessibility_tree, dict):
                    tree_name = (accessibility_tree.get("name") or "").lower()
                check_text = body_lower + " " + tree_name
                if any(signal in check_text for signal in _RATE_LIMIT_SIGNALS):
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Rate limit/block detected in page content for {url} — "
                        f"retrying in {delay}s (attempt {attempt + 1}/{_MAX_RETRIES})"
                    )
                    page.close()
                    context.close()
                    browser.close()
                    time.sleep(delay)
                    continue

                # Also extract content from child iframes (e.g. GameSheet embeds).
                # page.evaluate() only sees the outer document; iframe documents are
                # separate browsing contexts that must be accessed via page.frames.
                iframe_yamls = _extract_iframe_yamls(page)

                # Close browser
                page.close()
                context.close()
                browser.close()

                # Convert main page to YAML
                yaml_content = yaml.dump(
                    accessibility_tree,
                    default_flow_style=False,
                    sort_keys=False,
                    allow_unicode=True,
                    width=120,
                )

                # Append iframe sections (each labelled so the LLM can see them)
                for i, iframe_yaml in enumerate(iframe_yamls):
                    yaml_content += f"\n# --- IFRAME {i} ---\n{iframe_yaml}"

                # Calculate metrics
                yaml_bytes = len(yaml_content.encode("utf-8"))
                enc = tiktoken.get_encoding("cl100k_base")
                tokens = len(enc.encode(yaml_content))

                metadata["yaml_size_bytes"] = yaml_bytes
                metadata["token_estimate"] = tokens
                metadata["full_text"] = full_text

                logger.info(f"Success: {yaml_bytes:,} bytes, ~{tokens:,} tokens")

                # Cache the result
                save_yaml_to_cache(url, yaml_content, metadata)

                return yaml_content, metadata

        except Exception as e:
            last_error = e
            logger.error(f"Failed to fetch YAML (attempt {attempt + 1}/{_MAX_RETRIES}): {url}", exc_info=True)
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.info(f"Retrying in {delay}s...")
                time.sleep(delay)

    # All retries exhausted
    raise last_error or RuntimeError(f"Failed to fetch {url} after {_MAX_RETRIES} attempts")


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
