"""Test link discoverer against actual league websites."""

import requests
from src.scraper.link_discoverer import LinkDiscoverer
from urllib.parse import urlparse

# Test URLs
TEST_URLS = [
    "https://ottawaadultsoccer.com/",
    "https://www.ottawavolleysixes.com/home/volleyball",
]


def test_discoverer_on_url(url: str):
    """Fetch a URL and test the link discoverer on it."""
    print("\n" + "="*80)
    print(f"Testing: {url}")
    print("="*80 + "\n")

    try:
        # Fetch the page
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        html = response.text
        print(f"[OK] Fetched {len(html)} bytes of HTML\n")
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch: {e}\n")
        return

    # Run discoverer
    discoverer = LinkDiscoverer()
    links = discoverer.discover_links(url, html, min_score=1, max_links=20)

    if not links:
        print("No links discovered.")
        return

    # Display results
    clickable_count = sum(1 for link in links if link.clickable)
    recorded_count = len(links) - clickable_count

    print(f"Found {len(links)} links: {clickable_count} CLICKABLE, {recorded_count} RECORDED\n")
    print(f"{'Status':<10} {'Score':<8} {'Context':<8} {'Text':<35} {'URL':<50}")
    print("-" * 120)

    for link in links:
        status = "CLICK" if link.clickable else "RECORD"
        text = link.text[:32] if link.text else "(no text)"
        url_display = link.url[:47]
        print(f"{status:<10} {link.score:<8} {link.context:<8} {text:<35} {url_display:<50}")

    print()


def main():
    """Run tests on all URLs."""
    print("\nLink Discoverer Test Suite")
    print("Testing pattern matching and link scoring\n")

    for url in TEST_URLS:
        test_discoverer_on_url(url)

    print("="*80)
    print("Test complete!")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
