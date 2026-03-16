"""HTML fetching with Selenium and caching."""

import logging
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple
from urllib.parse import urlparse
import json

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path(__file__).parent.parent.parent / "scrapes"


def fetch_html_multi_page(
    url: str,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Tuple[str, dict]:
    """Fetch HTML with multi-page navigation (default) and fallback to single-page.

    Process:
    1. Try multi-page navigation (landing + registration + schedule + standings)
    2. If multi-page fails, fall back to single-page extraction
    3. Cache individual pages for debugging
    4. Aggregate all pages into single text

    Args:
        url: URL to scrape
        use_cache: Whether to check cache first (default True)
        force_refresh: Skip cache and re-scrape (default False)

    Returns:
        (aggregated_html_text, metadata_dict) where metadata includes:
        - url: Original URL
        - method: 'multi_page_selenium' | 'single_page_selenium'
        - pages_visited: int (number of unique page types)
        - page_types: list (types of pages found)
        - manual_review_flag: 'MULTI_PAGE' | 'MAIN_PAGE_ONLY' | 'FAILED'
        - cached: bool (True if pages loaded from cache)
        - fallback_reason: str | None (reason for fallback if applicable)

    Raises:
        Exception: If both multi-page and fallback fail
    """
    logger.info(f"Fetching with multi-page navigation: {url}")

    # Import here to avoid circular imports
    from src.scraper.multi_page_navigator import MultiPageNavigator

    try:
        # Try multi-page navigation
        navigator = MultiPageNavigator()

        try:
            page_htmls = navigator.navigate_site(url, max_pages=5, max_depth=1)

            if not page_htmls:
                raise Exception("No pages successfully fetched during navigation")

            # Aggregate pages into single text
            aggregated_text, page_types = navigator.aggregate_pages(page_htmls)

            # Determine manual review flag
            if len(page_htmls) > 1:
                manual_review_flag = "MULTI_PAGE"
            else:
                manual_review_flag = "MAIN_PAGE_ONLY"

            # Cache each page individually
            for page_type, html in page_htmls.items():
                _cache_page(url, page_type, html)

            metadata = {
                "url": url,
                "method": "multi_page_selenium",
                "pages_visited": len(page_htmls),
                "page_types": list(page_htmls.keys()),
                "manual_review_flag": manual_review_flag,
                "cached": False,
                "fallback_reason": None,
                "page_htmls": page_htmls,  # Individual page HTMLs for vector store
            }

            logger.info(
                f"Multi-page success: {len(page_htmls)} pages "
                f"({', '.join(page_htmls.keys())})"
            )
            navigator.close()
            return aggregated_text, metadata

        except Exception as e:
            logger.warning(f"Multi-page navigation failed: {e}")
            navigator.close()

            # Fallback: single-page extraction
            logger.info(f"Falling back to single-page extraction for {url}")
            single_html, single_meta = fetch_html(url, use_cache=use_cache)

            single_meta["method"] = "single_page_selenium"
            single_meta["pages_visited"] = 1
            single_meta["page_types"] = ["home"]
            single_meta["manual_review_flag"] = "MAIN_PAGE_ONLY"
            single_meta["fallback_reason"] = str(e)
            single_meta["page_htmls"] = {"home": single_html}  # Single page as home

            logger.info(f"Single-page fallback: {single_meta['manual_review_flag']}")
            return single_html, single_meta

    except Exception as e:
        logger.error(f"Both multi-page and single-page extraction failed: {e}")
        raise


def _cache_page(url: str, page_type: str, html: str) -> Path:
    """Cache individual page HTML with page type.

    Cache structure:
        scrapes/{domain}/YYYYMMDD_HHMMSS_{page_type}.html
        scrapes/{domain}/YYYYMMDD_HHMMSS_{page_type}.json

    Args:
        url: Source URL
        page_type: Type of page (home, registration, schedule, etc.)
        html: HTML content to cache

    Returns:
        Path to cached HTML file
    """
    domain = urlparse(url).netloc
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # Create cache directory
    cache_dir = CACHE_DIR / domain
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Save HTML with page type
    html_path = cache_dir / f"{timestamp}_{page_type}.html"
    html_path.write_text(html, encoding="utf-8")

    # Save metadata
    metadata = {
        "url": url,
        "page_type": page_type,
        "fetch_time": datetime.utcnow().isoformat(),
        "html_length": len(html),
    }
    json_path = cache_dir / f"{timestamp}_{page_type}.json"
    json_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.debug(f"Cached {page_type} page: {html_path}")
    return html_path


def fetch_html(url: str, use_cache: bool = True) -> Tuple[str, dict]:
    """Fetch HTML using Selenium with caching.

    Process:
    1. Check cache if use_cache=True
    2. If cache hit and fresh (<7 days), return cached HTML
    3. If cache miss or stale, fetch using Selenium with retries
    4. Save to cache
    5. Return (html_content, metadata)

    Args:
        url: URL to scrape
        use_cache: Whether to check cache first (default True)

    Returns:
        (html_content, metadata_dict) where metadata includes:
        - url: Original URL
        - fetch_time: ISO timestamp when fetched
        - method: 'selenium'
        - cached: bool (True if returned from cache)
        - cache_age_seconds: int (if cached)

    Raises:
        Exception: After 3 failed retry attempts
    """
    logger.info(f"Fetching: {url}")

    # Try cache first
    if use_cache:
        cached = load_from_cache(url)
        if cached:
            html, metadata = cached
            logger.info(f"Cache hit: {url} (age: {metadata.get('cache_age_seconds', 0)}s)")
            return html, metadata

    # Cache miss or disabled - fetch with Selenium
    logger.debug(f"Cache miss, fetching with Selenium: {url}")
    start_time = time.time()

    html = _fetch_with_selenium(url)
    fetch_duration = time.time() - start_time

    # Prepare metadata
    metadata = {
        "url": url,
        "fetch_time": datetime.utcnow().isoformat(),
        "method": "selenium",
        "cached": False,
        "fetch_duration_seconds": round(fetch_duration, 2),
        "html_length": len(html)
    }

    # Save to cache
    save_to_cache(url, html, metadata)

    logger.info(f"Fetched {len(html)} bytes in {fetch_duration:.1f}s")
    return html, metadata


def _fetch_with_selenium(url: str, max_retries: int = 3) -> str:
    """Fetch HTML using Selenium with retry logic.

    Args:
        url: URL to fetch
        max_retries: Number of retry attempts (default 3)

    Returns:
        HTML content as string

    Raises:
        Exception: If all retries fail
    """
    driver = None
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"Attempt {attempt}/{max_retries}: {url}")

            # Initialize driver
            options = _get_chrome_options()
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options
            )

            # Set timeouts
            driver.set_page_load_timeout(30)

            # Load page
            driver.get(url)

            # Wait for page to fully load (simple JS rendering wait)
            time.sleep(5)

            # Get HTML
            html = driver.page_source

            logger.debug(f"Successfully fetched {len(html)} bytes")
            return html

        except TimeoutException as e:
            last_error = e
            logger.warning(f"Timeout on attempt {attempt}: {str(e)[:100]}")
            wait_time = 2 ** (attempt - 1)  # 1s, 2s, 4s
            if attempt < max_retries:
                time.sleep(wait_time)

        except WebDriverException as e:
            last_error = e
            logger.warning(f"WebDriver error on attempt {attempt}: {str(e)[:100]}")
            wait_time = 2 ** (attempt - 1)
            if attempt < max_retries:
                time.sleep(wait_time)

        except Exception as e:
            last_error = e
            logger.warning(f"Unexpected error on attempt {attempt}: {str(e)[:100]}")

        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

    # All retries failed
    error_msg = f"Failed to fetch {url} after {max_retries} attempts: {str(last_error)}"
    logger.error(error_msg)
    raise Exception(error_msg)


def save_to_cache(url: str, html: str, metadata: dict) -> Path:
    """Save HTML to cache directory.

    Cache structure:
        scrapes/{domain}/YYYYMMDD_HHMMSS.html
        scrapes/{domain}/YYYYMMDD_HHMMSS.json

    Args:
        url: Source URL
        html: HTML content to cache
        metadata: Metadata dict with fetch_time

    Returns:
        Path to saved HTML file
    """
    # Extract domain from URL
    domain = urlparse(url).netloc

    # Get timestamp from metadata or current time
    fetch_time_str = metadata.get("fetch_time", datetime.utcnow().isoformat())
    fetch_dt = datetime.fromisoformat(fetch_time_str.replace('Z', '+00:00'))
    timestamp = fetch_dt.strftime("%Y%m%d_%H%M%S")

    # Create cache directory
    cache_dir = CACHE_DIR / domain
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Save HTML
    html_path = cache_dir / f"{timestamp}.html"
    html_path.write_text(html, encoding="utf-8")
    logger.debug(f"Cached HTML: {html_path}")

    # Save metadata
    json_path = cache_dir / f"{timestamp}.json"
    json_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.debug(f"Cached metadata: {json_path}")

    return html_path


def load_from_cache(url: str, max_age_days: int = 7) -> Optional[Tuple[str, dict]]:
    """Load HTML from cache if exists and fresh.

    Args:
        url: URL to find in cache
        max_age_days: Max age of cache file in days (default 7)

    Returns:
        (html_content, metadata) or None if not found or stale
    """
    domain = urlparse(url).netloc
    cache_dir = CACHE_DIR / domain

    if not cache_dir.exists():
        logger.debug(f"No cache directory: {cache_dir}")
        return None

    # Find most recent file
    html_files = list(cache_dir.glob("*.html"))
    if not html_files:
        logger.debug(f"No cached files in {cache_dir}")
        return None

    # Get most recent file
    most_recent = max(html_files, key=lambda p: p.stat().st_mtime)

    # Check age
    age_days = (datetime.utcnow() - datetime.fromtimestamp(most_recent.stat().st_mtime)).days
    if age_days > max_age_days:
        logger.debug(f"Cache too old ({age_days} days > {max_age_days} day limit): {most_recent}")
        return None

    # Load HTML
    html = most_recent.read_text(encoding="utf-8")

    # Load metadata
    json_path = most_recent.with_suffix(".json")
    metadata = {}
    if json_path.exists():
        metadata = json.loads(json_path.read_text(encoding="utf-8"))

    # Add cache age info
    metadata["cached"] = True
    metadata["cache_age_seconds"] = int(age_days * 86400 + (datetime.utcnow() - datetime.fromtimestamp(most_recent.stat().st_mtime)).total_seconds())

    logger.debug(f"Loaded from cache: {most_recent}")
    return html, metadata


def _get_chrome_options() -> Options:
    """Configure Chrome options for headless scraping.

    Returns:
        Configured Options object
    """
    options = Options()

    # Headless mode
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # Window size
    options.add_argument("--window-size=1920,1080")

    # User agent (appear as real browser)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    return options
