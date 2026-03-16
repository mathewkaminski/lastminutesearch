#!/usr/bin/env python3
"""Quick test of Phase 3 multi-page navigation."""

import logging
import sys
from pathlib import Path

# Fix encoding on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(name)s] %(levelname)s - %(message)s'
)

from src.scraper.html_fetcher import fetch_html_multi_page

def test_url(url: str):
    """Test single URL."""
    print(f"\n{'='*70}")
    print(f"Testing: {url}")
    print(f"{'='*70}\n")

    try:
        aggregated_text, metadata = fetch_html_multi_page(url, use_cache=False)

        print(f"\n{'='*70}")
        print("RESULTS:")
        print(f"{'='*70}")
        print(f"[OK] Method: {metadata.get('method')}")
        print(f"[OK] Pages visited: {metadata.get('pages_visited')}")
        print(f"[OK] Page types: {metadata.get('page_types')}")
        print(f"[OK] Manual review flag: {metadata.get('manual_review_flag')}")
        print(f"[OK] Aggregated text length: {len(aggregated_text)} characters")
        if metadata.get('fallback_reason'):
            print(f"[WARN] Fallback reason: {metadata.get('fallback_reason')}")

        print(f"\nFirst 400 characters of aggregated text:")
        print(f"{aggregated_text[:400]}")
        print(f"\n... (total {len(aggregated_text)} chars)")

        return True

    except Exception as e:
        print(f"\n[FAIL] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n[START] PHASE 3 QUICK TEST - Multi-Page Navigation\n")

    # Test both URLs
    urls = [
        "https://ottawaadultsoccer.com",
        "https://www.ottawavolleysixes.com/home/volleyball",
    ]

    results = {}
    for url in urls:
        results[url] = test_url(url)

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY:")
    print(f"{'='*70}")
    for url, success in results.items():
        status = "[PASS]" if success else "[FAIL]"
        print(f"{status}: {url}")

    print(f"\n[DONE] Phase 3 tests: {sum(results.values())}/{len(results)} passed")
    sys.exit(0 if all(results.values()) else 1)
