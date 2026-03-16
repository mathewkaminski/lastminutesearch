#!/usr/bin/env python
"""Quick test for Phase 3: HTML Scraping"""

import sys
from pathlib import Path
from dotenv import load_dotenv

# Load env vars
load_dotenv()

from src.scraper.html_fetcher import fetch_html

print("Testing Phase 3: HTML Scraping")
print("=" * 60)

try:
    print("Fetching https://ottawaadultsoccer.com...")
    html, metadata = fetch_html('https://ottawaadultsoccer.com')

    print(f"[PASS] Successfully fetched HTML")
    print(f"   URL: {metadata['url']}")
    print(f"   Size: {len(html)} bytes")
    print(f"   Method: {metadata['method']}")
    print(f"   Cached: {metadata['cached']}")
    print(f"   Fetch time: {metadata.get('fetch_time', 'N/A')}")
    print()

    # Check cache was saved
    cache_dir = Path("scrapes") / "ottawaadultsoccer.com"
    html_files = list(cache_dir.glob("*.html"))
    if html_files:
        print(f"   Cache files: {len(html_files)} found")

    print()
    print("[PASS] Phase 3 Test PASSED")
    sys.exit(0)

except Exception as e:
    print(f"[FAIL] Phase 3 Test FAILED")
    print(f"Error: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
