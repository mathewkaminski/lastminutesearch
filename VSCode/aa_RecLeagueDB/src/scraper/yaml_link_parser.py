"""Extract and score links from Playwright YAML accessibility trees."""

import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from src.config.sss_codes import SPORT_CODES

logger = logging.getLogger(__name__)

# Build sport keywords dynamically from SSS codes at module level
_SPORT_KEYWORDS: set[str] = set()
for _sport_name in SPORT_CODES.values():
    for _word in _sport_name.lower().split():
        if len(_word) > 2:  # skip "&", "up", etc.
            _SPORT_KEYWORDS.add(_word)


class DiscoveredLink:
    """Represents a discovered link with metadata."""

    def __init__(
        self,
        url: str,
        anchor_text: str = "",
        score: int = 0,
        page_type: Optional[str] = None,
        clickable: bool = False,
        field_category: Optional[str] = None,
    ):
        """Initialize discovered link.

        Args:
            url: Link URL
            anchor_text: Visible link text
            score: Link relevance score (0-100+)
            page_type: Inferred page type (registration, schedule, etc.)
            clickable: Whether link is high-priority enough to follow
            field_category: DB field category this link likely leads to
        """
        self.url = url
        self.anchor_text = anchor_text
        self.score = score
        self.page_type = page_type
        self.clickable = clickable
        self.field_category = field_category

    def __repr__(self) -> str:
        return (
            f"DiscoveredLink(url={self.url!r}, text={self.anchor_text!r}, "
            f"score={self.score}, clickable={self.clickable})"
        )


def parse_yaml_links(yaml_tree, base_url: str = "") -> List[DiscoveredLink]:
    """Extract all links from Playwright YAML accessibility tree.

    Recursively traverses YAML tree to find link elements (role='a') and extract URLs.

    YAML link structure:
    ```yaml
    - role: a
      name: "Register Now"
      url: /registration
    - role: li
      children:
        - role: a
          name: "Sign Up"
          url: /registration
    ```

    Args:
        yaml_tree: Parsed YAML tree (can be dict or list)
        base_url: Base URL for resolving relative URLs

    Returns:
        List of DiscoveredLink objects
    """
    links = []

    def traverse(node):
        """Recursively traverse YAML tree to find elements with role='a'."""
        if not isinstance(node, (dict, list)):
            return

        if isinstance(node, list):
            for item in node:
                traverse(item)
        elif isinstance(node, dict):
            # Check if this node is a link element (role='a' or role='link')
            if node.get("role") in ("a", "link"):
                anchor_text = node.get("name", "").strip()
                link_url = node.get("url", "").strip()

                # Resolve relative URLs
                if link_url:
                    if link_url.startswith(("http://", "https://")):
                        full_url = link_url
                    elif base_url:
                        full_url = urljoin(base_url, link_url)
                    else:
                        full_url = link_url

                    # Only include if we have both URL and text
                    if full_url and anchor_text:
                        link = DiscoveredLink(
                            url=full_url,
                            anchor_text=anchor_text,
                            score=0,  # Score calculated later
                            clickable=False,
                        )
                        links.append(link)

            # Recursively search children
            for key, value in node.items():
                if key == "children" and isinstance(value, list):
                    traverse(value)

    traverse(yaml_tree)
    return links


def _extract_url_from_node(node, base_url: str = "") -> Optional[str]:
    """Extract URL from a YAML node.

    Looks for /url property in the node or its children.

    Args:
        node: YAML node (dict, list, or string)
        base_url: Base URL for resolving relative URLs

    Returns:
        Full URL or None
    """
    if isinstance(node, dict):
        # Check for /url key
        if "/url" in node:
            url = node["/url"]
            if isinstance(url, str) and url:
                # Resolve relative URLs
                if url.startswith(("http://", "https://")):
                    return url
                elif url.startswith("/") and base_url:
                    parsed = urlparse(base_url)
                    base = f"{parsed.scheme}://{parsed.netloc}"
                    return urljoin(base, url)
                else:
                    return url

        # Check children
        for value in node.values():
            url = _extract_url_from_node(value, base_url)
            if url:
                return url

    elif isinstance(node, list):
        for item in node:
            url = _extract_url_from_node(item, base_url)
            if url:
                return url

    return None


def score_links(links: List[DiscoveredLink]) -> List[DiscoveredLink]:
    """Score links by relevance for navigation.

    Scoring system:
    - 100+ points: HIGH PRIORITY (registration, schedule, standings, upcoming leagues)
    - 50 points: MEDIUM PRIORITY (leagues, teams, rules, divisions, pricing)
    - 0 points: LOW PRIORITY (everything else)

    Clickable links have score >= 100.

    Args:
        links: List of discovered links

    Returns:
        List of links with updated scores and clickable flags
    """
    # All keywords at high priority (100 pts)
    high_priority_keywords = [
        # Navigation/action
        "register", "signup", "sign up", "registration",
        "schedule", "standings", "upcoming", "leagues", "games",
        "season", "current", "join", "enroll", "programs",
        "results", "details", "more info", "more information",
        # Structural (promoted from former medium tier)
        "league", "division", "divisions", "team", "teams",
        "rules", "pricing", "format", "competition",
        "sport", "sports", "calendar", "scores", "program",
    ]

    for link in links:
        url_lower = (link.url + " " + link.anchor_text).lower()

        # Check high priority keywords
        for keyword in high_priority_keywords:
            if keyword in url_lower:
                link.score += 100
                break

        # Check sport name keywords (also high priority)
        if link.score < 100:
            if any(kw in url_lower for kw in _SPORT_KEYWORDS):
                link.score += 100

        # Penalize social media and external links
        if any(
            x in link.url.lower()
            for x in ["facebook", "twitter", "instagram", "youtube", "linkedin"]
        ):
            link.score -= 50

        # Filter out common non-content links
        if any(
            x in link.url.lower()
            for x in ["logout", "login", "signin", "admin", "dashboard", "profile"]
        ):
            link.score = max(0, link.score - 50)

        # Set clickable flag
        link.clickable = link.score >= 100

    # Sort by score descending
    return sorted(links, key=lambda l: l.score, reverse=True)


def infer_page_type(url: str, anchor_text: str = "") -> Optional[str]:
    """Infer page type from URL and anchor text.

    Args:
        url: Link URL
        anchor_text: Visible link text

    Returns:
        Inferred page type: 'registration', 'schedule', 'standings', etc.
    """
    combined = (url + " " + anchor_text).lower()

    type_patterns = {
        "registration": ["register", "signup", "sign up", "registration", "enroll"],
        "schedule": ["schedule", "games", "game", "times", "fixtures"],
        "standings": ["standings", "results", "scores", "results", "ranking"],
        "league_list": ["leagues", "league info", "divisions", "competition"],
        "rules": ["rules", "format", "regulations", "policy", "policies"],
        "teams": ["teams", "team", "roster"],
    }

    for page_type, patterns in type_patterns.items():
        for pattern in patterns:
            if pattern in combined:
                return page_type

    return None


# Field categories → which DB fields they typically contain
_CATEGORY_MAP: dict[str, list[str]] = {
    "SCHEDULE": ["schedule", "standings", "teams", "results", "scores", "matchups"],
    "REGISTRATION": ["registration"],
    "POLICY": ["rules", "policies", "waiver", "insurance", "referee"],
    "VENUE": ["venue", "location", "facility"],
    "DETAIL": ["league_list", "league", "program", "division", "about", "season"],
}

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "SCHEDULE": ["schedule", "standings", "teams", "results", "scores", "matchups", "upcoming"],
    "REGISTRATION": ["register", "signup", "sign up", "enroll", "payment", "fees", "pricing", "cost"],
    "POLICY": ["rules", "policies", "insurance", "waiver", "referee", "format"],
    "VENUE": ["venue", "location", "facility", "field", "gym", "arena", "court"],
    "DETAIL": ["league", "division", "program", "season", "current", "calendar", "about", "sport", "join", "enroll", "upcoming", "more info", "more information"],
}


def infer_link_category(anchor_text: str, page_type: Optional[str]) -> Optional[str]:
    """Return the field category a link likely leads to.

    Args:
        anchor_text: Visible link text (lowercased internally)
        page_type: Page type from infer_page_type(), or None

    Returns:
        One of "SCHEDULE", "REGISTRATION", "POLICY", "VENUE", "DETAIL", or None
    """
    text = anchor_text.lower()

    # Check page_type first (more reliable signal)
    if page_type:
        for category, types in _CATEGORY_MAP.items():
            if page_type in types:
                return category

    # Fall back to keyword matching on anchor text
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return category

    # Check sport keywords for DETAIL category
    if any(kw in text for kw in _SPORT_KEYWORDS):
        return "DETAIL"

    return None


def extract_navigation_links(
    yaml_tree: List, base_url: str = "", min_score: int = 100
) -> List[DiscoveredLink]:
    """Extract and score navigation links from YAML tree.

    Convenience function that combines parsing, scoring, and filtering.

    Args:
        yaml_tree: Parsed YAML tree
        base_url: Base URL for relative link resolution
        min_score: Minimum score to include (default 100 = high priority)

    Returns:
        List of high-priority links sorted by score
    """
    # Extract all links
    links = parse_yaml_links(yaml_tree, base_url)

    # Score links
    scored_links = score_links(links)

    # Infer page types and field categories
    for link in scored_links:
        link.page_type = infer_page_type(link.url, link.anchor_text)
        link.field_category = infer_link_category(link.anchor_text, link.page_type)

    # Filter by score
    high_priority = [link for link in scored_links if link.score >= min_score]

    logger.info(
        f"Extracted {len(links)} total links, "
        f"{len(high_priority)} high-priority for navigation"
    )

    return high_priority
