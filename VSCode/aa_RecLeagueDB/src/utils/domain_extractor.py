"""Utility for extracting the base domain from a URL."""
from urllib.parse import urlparse


def extract_base_domain(url: str | None) -> str:
    """Return the base domain from a URL, stripping www. and subdomains.

    Examples:
        "https://www.javelin.com/calgary/vball" -> "javelin.com"
        "https://register.zogculture.com/page"  -> "zogculture.com"

    Args:
        url: A URL string, or None.

    Returns:
        Base domain string, e.g. "javelin.com". Empty string if url is None/empty/invalid.
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        netloc = parsed.netloc or parsed.path  # fallback for schemeless strings
        # Strip port if present
        netloc = netloc.split(":")[0]
        # Strip www. prefix
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Keep only last two parts of subdomain (e.g. register.zogculture.com -> zogculture.com)
        parts = netloc.split(".")
        if len(parts) > 2:
            netloc = ".".join(parts[-2:])
        return netloc.lower()
    except Exception:
        return ""
