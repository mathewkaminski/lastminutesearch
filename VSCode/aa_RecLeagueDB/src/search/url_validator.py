"""URL validation and canonicalization logic.

This module handles:
- Validating URLs against domain/keyword rules
- Classifying validation failures
- Extracting organization names from URLs/titles
- Canonicalizing URLs for deduplication
"""

import re
import logging
from typing import Tuple
from urllib.parse import urlparse
from src.config.search_filters import (
    YOUTH_INDICATORS,
    ADULT_REC_KEYWORDS,
    PROFESSIONAL_PATTERNS
)

logger = logging.getLogger(__name__)

# Configuration: Invalid file extensions
INVALID_EXTENSIONS = ['.pdf', '.doc', '.docx', '.jpg', '.png', '.xlsx', '.csv']

# Configuration: Invalid/exclusion domains
INVALID_DOMAINS = [
    'facebook.com', 'instagram.com', 'twitter.com', 'tiktok.com', 'reddit.com',
    'yelp.com', 'google.com', 'maps.google.com', 'wikipedia.org', 'wikimedia.org',
    'youtube.com', 'linkedin.com', 'pinterest.com'
]

# Configuration: Keywords indicating valid league content
VALID_KEYWORDS = ['league', 'register', 'schedule', 'sign up', 'team', 'roster', 'season']

# Configuration: Keywords indicating non-league content
INVALID_KEYWORDS = [
    'news article', 'blog post', 'review', 'article',
    'facility rental', 'equipment shop', 'sports bar', 'gym'
]

# Configuration: Professional sports indicators (reject these - we want adult rec leagues only)
PROFESSIONAL_SPORTS_PATTERNS = [
    # Major professional leagues
    'mls', 'nba', 'nfl', 'nhl', 'mlb',
    'major league', 'premier league', 'la liga', 'serie a',
    # Professional team indicators
    'toronto fc', 'raptors', 'maple leafs', 'blue jays',
    # Professional league domains
    '.canpl.ca', 'mlssoccer.com',
    # Keywords indicating professional
    'professional', 'pro team', 'ticket', 'tickets'
]

# Configuration: Valid domain extensions
VALID_DOMAIN_EXTENSIONS = ['.com', '.org', '.net', '.ca', '.io', '.app']


def canonicalize_url(url: str) -> str:
    """Normalize URL for deduplication.

    Performs:
    - Lowercase the entire URL
    - Remove trailing slash
    - Remove tracking parameters (utm_*, fbclid, gclid)
    - Normalize http → https
    - Remove www. prefix
    - Clean up leftover ? and & characters

    Args:
        url: Original URL string

    Returns:
        Canonicalized URL

    Examples:
        >>> canonicalize_url("https://example.com/?utm_source=google")
        "https://example.com"

        >>> canonicalize_url("http://www.example.com/")
        "https://example.com"

        >>> canonicalize_url("HTTPS://Example.COM/page/")
        "https://example.com/page"
    """
    if not url:
        return ""

    try:
        # Lowercase
        canonical = url.lower()

        # Remove trailing slash
        canonical = re.sub(r'/$', '', canonical)

        # Remove tracking parameters (utm_*, fbclid, gclid)
        canonical = re.sub(r'[?&](utm_[^&]+|fbclid=[^&]+|gclid=[^&]+)', '', canonical)

        # Normalize http → https
        canonical = re.sub(r'^http://', 'https://', canonical)

        # Remove www. prefix
        canonical = re.sub(r'://www\.', '://', canonical)

        # Clean up leftover ? or & at end
        canonical = re.sub(r'[?&]$', '', canonical)

        return canonical

    except Exception as e:
        logger.warning(f"Error canonicalizing URL: {str(e)}")
        return url


def extract_organization_name(url: str, title: str) -> str:
    """Extract organization name from URL or title (best effort).

    Strategy:
    1. Try extracting from URL domain before .com/.ca (e.g., tssc.ca → "tssc")
    2. Filter out nonsense words (too short, mostly numbers, etc.)
    3. Fall back to page title
    4. Return empty string if both fail

    Args:
        url: URL string
        title: Page title

    Returns:
        Organization name or empty string

    Examples:
        >>> extract_organization_name("https://tssc.ca/soccer", "")
        "tssc"

        >>> extract_organization_name("https://torontosports.com", "")
        "torontosports"

        >>> extract_organization_name("https://example.com", "Toronto Soccer League")
        "Toronto Soccer League"
    """
    # Try extracting from domain
    if url:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Remove 'www.' prefix
            domain = re.sub(r'^www\.', '', domain)

            # Extract the leftmost meaningful part (before any dot)
            # e.g., "soccer.example.com" → "soccer", "tssc.ca" → "tssc"
            domain_name = domain.split('.')[0]

            # Filter out nonsense (too short, mostly numbers, etc.)
            if domain_name and len(domain_name) > 1 and not _is_nonsense_word(domain_name):
                return domain_name.upper()
        except Exception as e:
            logger.debug(f"Could not extract from URL {url}: {str(e)}")

    # Fall back to title
    if title:
        # Take first meaningful part of title (before dash or pipe)
        parts = re.split(r'[\s\-\|]', title)
        if parts and parts[0]:
            return parts[0].strip()

    return ""


def _is_nonsense_word(word: str) -> bool:
    """Check if a word is likely nonsense/gibberish.

    Filters:
    - Words that are mostly digits (e.g., '12345')
    - Single characters (handled elsewhere but included for safety)
    - Very long random strings (> 30 chars with mostly consonants/numbers)

    Args:
        word: Word to check

    Returns:
        True if word appears to be nonsense, False otherwise
    """
    if not word:
        return True

    # Filter: mostly digits (> 50% digits)
    digit_ratio = sum(1 for c in word if c.isdigit()) / len(word)
    if digit_ratio > 0.5:
        return True

    return False


def has_adult_rec_indicators(title: str, snippet: str) -> bool:
    """Check if content contains strong adult rec league indicators.

    Requires at least 2 adult rec keyword matches for high confidence.

    Args:
        title: Page title
        snippet: Page snippet/description

    Returns:
        True if content has strong adult rec signals, False otherwise
    """
    content = (title + " " + snippet).lower()

    # Count adult rec keyword matches
    matches = sum(1 for kw in ADULT_REC_KEYWORDS if kw in content)
    return matches >= 2  # Require at least 2 matches for high confidence


def validate_url(
    url: str,
    title: str = "",
    snippet: str = ""
) -> Tuple[bool, str]:
    """Validate URL against rules and return validation status + reason.

    Args:
        url: URL to validate
        title: Page title (for keyword checking)
        snippet: Page snippet/description (for keyword checking)

    Returns:
        Tuple of (is_valid, reason)
        - is_valid: True if URL passes validation
        - reason: String describing validation result:
          - "valid_league_page" - Passed with league content
          - "valid_adult_rec_league" - Passed with explicit adult rec indicators
          - "invalid_file_type" - PDF, DOC, image files
          - "social_media" - Facebook, Instagram, Twitter, etc.
          - "review_site" - Yelp, Google Maps, etc.
          - "professional_sports" - MLS, NBA, Toronto FC, etc.
          - "youth_organization" - Youth leagues, district associations, etc.
          - "not_league_content" - News, blog, equipment shop, etc.
    """
    if not url:
        return False, "empty_url"

    url_lower = url.lower()
    content = (title + " " + snippet).lower()

    # Check invalid file extensions
    for ext in INVALID_EXTENSIONS:
        if url_lower.endswith(ext):
            logger.debug(f"Invalid extension: {url} ({ext})")
            return False, "invalid_file_type"

    # Check invalid domains (social media, review sites, etc.)
    for domain in INVALID_DOMAINS:
        if domain in url_lower:
            logger.debug(f"Invalid domain: {url} ({domain})")
            if 'yelp' in domain or 'google' in domain and 'maps' in domain:
                return False, "review_site"
            else:
                return False, "social_media"

    # Check for professional sports teams/leagues (we want adult rec leagues only)
    for pattern in PROFESSIONAL_PATTERNS:
        if pattern in url_lower or pattern in content:
            logger.debug(f"Professional sports detected: {url} ({pattern})")
            return False, "professional_sports"

    # Check for youth organizations (strict blocking - same as professional)
    for pattern in YOUTH_INDICATORS:
        if pattern in url_lower or pattern in content:
            logger.debug(f"Youth organization detected: {url} ({pattern})")
            return False, "youth_organization"

    # Additional heuristic: check for age ranges (U18, U16, etc.)
    if re.search(r'\bu\d{1,2}\b', content):
        logger.debug(f"Youth age range detected: {url}")
        return False, "youth_organization"

    # Check for invalid keywords (news, blog, reviews, equipment, etc.)
    for keyword in INVALID_KEYWORDS:
        if keyword in content:
            logger.debug(f"Invalid keyword found in {url}: {keyword}")
            return False, "not_league_content"

    # Check for valid keywords in title or snippet
    has_valid_keyword = any(kw in content for kw in VALID_KEYWORDS)

    # Check domain extension is reasonable
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        has_valid_domain = any(domain.endswith(ext) for ext in VALID_DOMAIN_EXTENSIONS)
    except Exception:
        has_valid_domain = False

    # URL is valid if it has valid keywords OR has a recognized domain
    if has_valid_keyword or has_valid_domain:
        # Check if this is explicitly an adult rec league
        if has_adult_rec_indicators(title, snippet):
            logger.debug(f"Valid adult rec league: {url}")
            return True, "valid_adult_rec_league"

        logger.debug(f"Valid league page: {url}")
        return True, "valid_league_page"

    # Default: reject if no clear indicators
    logger.debug(f"No league indicators found: {url}")
    return False, "not_league_content"
