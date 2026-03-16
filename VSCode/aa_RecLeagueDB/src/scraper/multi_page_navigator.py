"""Multi-page navigator - orchestrate site navigation and HTML collection."""

import logging
from typing import Optional
from urllib.parse import urlparse

from src.scraper.chrome_driver import ChromeDriverManager
from src.scraper.page_classifier import PageClassifier
from src.scraper.link_discoverer import LinkDiscoverer
from src.scraper.html_aggregator import HtmlAggregator

logger = logging.getLogger(__name__)


class MultiPageNavigator:
    """Navigate through websites to collect multiple page HTMLs."""

    # Known URL patterns to try first (before link discovery)
    KNOWN_PATTERNS = [
        "/registration",
        "/register",
        "/signup",
        "/sign-up",
        "/sign_up",
        "/schedule",
        "/schedules",
        "/calendar",
        "/standings",
        "/results",
        "/standings",
        "/teams",
        "/fees",
        "/pricing",
    ]

    def __init__(self):
        """Initialize navigator with helpers."""
        self.classifier = PageClassifier()
        self.discoverer = LinkDiscoverer()
        self.aggregator = HtmlAggregator()
        self.driver_manager = ChromeDriverManager(headless=True)

    def navigate_site(
        self,
        url: str,
        max_pages: int = 5,
        max_depth: int = 1,
    ) -> dict[str, str]:
        """
        Navigate website and collect HTMLs from multiple pages.

        Args:
            url: Starting URL
            max_pages: Maximum pages to collect (default 5)
            max_depth: Maximum depth to navigate (default 1, landing only)

        Returns:
            Dict of {page_type: html} for each unique page type discovered
        """
        logger.info(f"Starting multi-page navigation: {url}")

        try:
            # Collect HTMLs from different pages
            page_htmls = {}
            visited_urls = set()

            # 1. Fetch landing page
            landing_html = self.driver_manager.fetch_url(url)
            landing_type = self.classifier.classify_page(url, landing_html)
            page_htmls[landing_type] = landing_html
            visited_urls.add(url)
            logger.info(f"Landing page: {landing_type}")

            # 2. Try known URL patterns (DISABLED - using only discovered links from homepage)
            # This prevents finding outdated pages and focuses on current website structure
            # base_domain = urlparse(url).netloc
            # base_path = "/".join(urlparse(url).path.split("/")[:-1])
            # known_pattern_urls = self._try_known_patterns(url, base_path)
            #
            # for pattern_url, pattern_html in known_pattern_urls.items():
            #     if len(page_htmls) >= max_pages:
            #         break
            #     page_type = self.classifier.classify_page(pattern_url, pattern_html)
            #     if page_type not in page_htmls:  # Don't duplicate page types
            #         page_htmls[page_type] = pattern_html
            #         visited_urls.add(pattern_url)
            #         logger.info(f"Found via pattern: {page_type}")

            # 2. Discover and follow links from homepage
            if len(page_htmls) < max_pages:
                discovered_links = self.discoverer.discover_links(
                    url, landing_html, min_score=0, max_links=50
                )

                # Log all discovered links with scores
                if discovered_links:
                    logger.info(f"Discovered {len(discovered_links)} links from homepage:")
                    for discovered_link in discovered_links:
                        logger.info(f"  - {discovered_link.url} (score: {discovered_link.score})")

                for link in discovered_links:
                    if len(page_htmls) >= max_pages:
                        break
                    if link.url in visited_urls:
                        continue

                    try:
                        link_html = self.driver_manager.fetch_url(link.url)
                        page_type = self.classifier.classify_page(link.url, link_html)

                        # Visit all links regardless of page type (will extract all leagues)
                        # Only stop if we've reached max_pages limit
                        page_htmls[page_type] = link_html
                        visited_urls.add(link.url)
                        logger.info(f"Discovered via link: {page_type} (score: {link.score})")

                    except Exception as e:
                        logger.warning(f"Error fetching discovered link {link.url}: {e}")
                        continue

            logger.info(f"Navigation complete: {len(page_htmls)} unique page types collected")
            return page_htmls

        except Exception as e:
            logger.error(f"Error during multi-page navigation: {e}")
            # Clean up driver on error
            self.driver_manager.quit()
            raise

    def _try_known_patterns(self, base_url: str, base_path: str) -> dict[str, str]:
        """
        Try common URL patterns before link discovery.

        Args:
            base_url: Base URL to construct patterns from
            base_path: Base path for relative patterns

        Returns:
            Dict of {url: html} for successful pattern matches
        """
        results = {}
        parsed = urlparse(base_url)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"

        for pattern in self.KNOWN_PATTERNS:
            if len(results) >= 3:  # Limit to 3 pattern matches
                break

            candidate_url = base_domain + pattern

            try:
                logger.debug(f"Trying known pattern: {candidate_url}")
                html = self.driver_manager.fetch_url(candidate_url)

                # Check if page has meaningful content (not 404)
                if len(html) > 500 and "404" not in html.lower():
                    results[candidate_url] = html
                    logger.info(f"[OK] Pattern match: {pattern}")
                else:
                    logger.debug(f"✗ Pattern failed (empty/404): {pattern}")

            except Exception as e:
                logger.debug(f"✗ Pattern failed: {pattern} ({str(e)[:50]})")
                continue

        return results

    def aggregate_pages(
        self,
        page_htmls: dict[str, str],
    ) -> tuple[str, dict[str, str]]:
        """
        Aggregate collected HTMLs into single text with token budgeting.

        Args:
            page_htmls: Dict of {page_type: html}

        Returns:
            Tuple of (aggregated_text, page_types_dict)
        """
        # Create page_types mapping for aggregator
        page_types = {}
        for page_type, html in page_htmls.items():
            # For now, page_type IS the classification
            page_types[page_type] = page_type

        # Aggregate with token budgeting
        aggregated_text = self.aggregator.aggregate_htmls(page_htmls)

        return aggregated_text, page_types

    def close(self):
        """Clean up resources."""
        self.driver_manager.quit()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
