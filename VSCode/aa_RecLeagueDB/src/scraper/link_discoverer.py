"""Link discoverer - find relevant links to navigate to on a page."""

import re
from urllib.parse import urljoin, urlparse
from typing import Optional
from bs4 import BeautifulSoup

from src.utils.domain_extractor import extract_base_domain


class DiscoveredLink:
    """Represents a discovered link with metadata."""

    def __init__(
        self,
        url: str,
        text: str,
        score: int,
        context: str = "body",
        clickable: bool = False,
    ):
        self.url = url
        self.text = text
        self.score = score
        self.context = context
        self.clickable = clickable  # True if score >= 100 (will be followed)

    def __repr__(self) -> str:
        status = "CLICK" if self.clickable else "RECORD"
        return f"<Link {status} score={self.score} text='{self.text[:30]}' url='{self.url}'>"


class LinkDiscoverer:
    """Discover and score links on a page."""

    # High-priority keywords (100 points - these links will be clicked)
    # Covers: registration actions, schedule/standings/results, league info, CTA
    HIGH_PRIORITY_PATTERNS = [
        r"(?:register|signup|sign-up|sign_up|registration|register\s+now)",
        r"(?:join|enroll|apply|get\s+started|create\s+account|buy\s+now)",
        r"(?:view\s+)?schedule",
        r"standings",
        r"results",
        r"league(?:\s+info)?",
        r"season",
    ]

    # Medium-priority keywords (50 points - recorded but not clicked, for future scrapers)
    # Covers: competition structure, rules, participation details
    MEDIUM_PRIORITY_PATTERNS = [
        r"divisions?",
        r"teams?",
        r"rosters?",
        r"bracket(?:s)?",
        r"tournament",
        r"playoffs?",
        r"(?:game|match)(?:es)?",
        r"about\s+(?:the\s+)?league",
        r"how\s+to\s+(?:play|join)",
        r"fees?",
        r"pricing",
        r"rules?",
        r"format",
    ]

    # Blocked contexts (don't follow these links)
    BLOCKED_CONTEXTS = {
        "footer",
        "copyright",
        "social",
        "contact",
        "privacy",
        "terms",
        "login",
        "account",
        "admin",
    }

    # External/blacklisted domains to skip (social media only)
    # Note: LeagueApps, SportsEngine, and similar platforms are allowed as they often host league info
    BLOCKED_DOMAINS = {
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "tiktok.com",
        "youtube.com",
        "reddit.com",
        "linkedin.com",
        "pinterest.com",
        "yelp.com",
        "google.com",
        "maps.google.com",
    }

    def discover_links(
        self,
        base_url: str,
        html: str,
        min_score: int = 1,
        max_links: int = 20,
    ) -> list[DiscoveredLink]:
        """
        Discover relevant links on a page using keyword matching.

        All links with score >= min_score are returned. Links with score >= 100
        are marked as clickable=True (should be followed by scraper).

        Args:
            base_url: Base URL for resolving relative links
            html: HTML content
            min_score: Minimum score to include link (default 1 = skip unscored links)
            max_links: Maximum links to return (default 20)

        Returns:
            List of DiscoveredLink objects, sorted by score descending.
            Clickable links (score=100) should be followed; recorded links (0-99)
            are for future scrapers to prioritize.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return []

        discovered = []
        base_domain = extract_base_domain(base_url)

        # Find all links
        for link in soup.find_all("a", href=True):
            link_text = link.get_text(strip=True)
            link_href = link.get("href", "").strip()

            # Allow empty text (for image links), but require href
            if not link_href:
                continue

            # Resolve relative URLs
            absolute_url = urljoin(base_url, link_href)

            # Filter links
            if not self._should_visit_link(absolute_url, base_domain, base_url):
                continue

            # Score the link
            score = self._score_link(link_text, absolute_url, link)

            if score >= min_score:
                # Determine context (header, nav, body, footer)
                context = self._determine_context(link)
                clickable = score >= 100
                discovered.append(
                    DiscoveredLink(
                        url=absolute_url,
                        text=link_text,
                        score=score,
                        context=context,
                        clickable=clickable,
                    )
                )

        # Sort by score descending, remove duplicates (by URL)
        discovered.sort(key=lambda x: x.score, reverse=True)
        seen_urls = set()
        unique = []
        for link in discovered:
            if link.url not in seen_urls:
                unique.append(link)
                seen_urls.add(link.url)

        return unique[:max_links]

    def _should_visit_link(self, url: str, base_domain: str, base_url: str) -> bool:
        """Check if we should visit this link."""
        # Reject non-HTTP URL schemes (mailto:, tel:, javascript:, etc.)
        if not url.startswith(("http://", "https://", "/")):
            return False

        # Reject anchor-only links (#only) — they don't navigate to new pages
        if url.startswith("#"):
            return False

        parsed = urlparse(url)
        link_domain = extract_base_domain(url)

        # Check if same base domain (normalizes www. and subdomains)
        if link_domain != base_domain:
            return False

        # Check blacklist
        for blocked in self.BLOCKED_DOMAINS:
            if blocked in link_domain:
                return False

        # Reject file extensions
        path = parsed.path.lower()
        blocked_extensions = (".pdf", ".doc", ".docx", ".jpg", ".png", ".xlsx", ".csv")
        if path.endswith(blocked_extensions):
            return False

        # Reject blacklisted paths
        blocked_paths = ("/login", "/admin", "/wp-admin", "/account", "/profile")
        if any(path.startswith(bp) for bp in blocked_paths):
            return False

        return True

    def _score_link(self, text: str, url: str, link_element=None) -> int:
        """
        Score link relevance using keyword matching against multiple text sources.

        Checks anchor text, title attribute, aria-label, and URL path.
        Returns 100 for high-priority matches, 50 for medium-priority, 0 if no keywords.

        Args:
            text: Visible anchor text
            url: Link URL
            link_element: BeautifulSoup link element (for extracting title, aria-label)
        """
        text_lower = text.lower() if text else ""
        url_lower = url.lower()

        # Extract additional text sources from link element
        title = ""
        aria_label = ""
        if link_element:
            title = link_element.get("title", "").lower()
            aria_label = link_element.get("aria-label", "").lower()

        # Combine all text sources for keyword matching
        combined_text = f"{text_lower} {title} {aria_label}".strip()

        # Check for HIGH-PRIORITY keywords (100 points)
        for pattern in self.HIGH_PRIORITY_PATTERNS:
            if re.search(pattern, url_lower) or re.search(pattern, combined_text):
                return 100

        # Check for MEDIUM-PRIORITY keywords (50 points)
        for pattern in self.MEDIUM_PRIORITY_PATTERNS:
            if re.search(pattern, url_lower) or re.search(pattern, combined_text):
                return 50

        # No keywords found
        return 0

    def _determine_context(self, link_element) -> str:
        """
        Determine context of link (header, nav, body, footer) by walking DOM tree.

        Walks up to 5 parents checking for semantic HTML tags and class/id names
        containing "footer", "nav", or "header".

        Note: Links rendered by JavaScript after page load are invisible to this method
        since it operates on the static HTML. For complete coverage, use a browser-based
        scraper (Selenium/Playwright) alongside this parser-based approach.
        """
        parent = link_element.parent
        for _ in range(5):  # Check up to 5 parents
            if parent is None:
                return "body"
            tag_name = parent.name or ""
            classes = " ".join(parent.get("class", []))
            context_str = f"{tag_name} {classes}".lower()

            if "footer" in context_str:
                return "footer"
            if "nav" in context_str:
                return "nav"
            if "header" in context_str:
                return "header"

            parent = parent.parent

        return "body"
