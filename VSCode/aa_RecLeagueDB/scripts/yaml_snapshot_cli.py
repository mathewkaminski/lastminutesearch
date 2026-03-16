#!/usr/bin/env python
"""CLI tool to fetch, inspect, extract, and store YAML snapshots from URLs.

Uses Playwright to generate accessibility tree YAML snapshots.
Uses GPT-4 to extract league data from YAML.

Usage:
    # Inspect YAML
    python yaml_snapshot_cli.py https://ottawavolleysixes.com --header
    python yaml_snapshot_cli.py https://ottawavolleysixes.com --summary
    python yaml_snapshot_cli.py https://ottawavolleysixes.com --links

    # Extract leagues from YAML
    python yaml_snapshot_cli.py https://ottawavolleysixes.com --extract

    # Complete workflow: fetch, extract, and store
    python yaml_snapshot_cli.py https://ottawavolleysixes.com --extract --store
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_and_inspect(url: str, display_mode: str = "summary", use_cache: bool = True):
    """Fetch YAML from URL using Playwright and display based on mode."""
    from src.scraper.playwright_yaml_fetcher import fetch_page_as_yaml

    logger.info(f"Fetching YAML from: {url}")

    try:
        yaml_content, metadata = fetch_page_as_yaml(
            url,
            use_cache=use_cache,
            force_refresh=False
        )

        yaml_tree = yaml.safe_load(yaml_content)

        print("\n" + "="*80)
        print(f"YAML SNAPSHOT")
        print("="*80)

        # Display metadata
        print("\nMETADATA:")
        print(f"  URL: {url}")
        print(f"  Size: {metadata['yaml_size_bytes']:,} bytes")
        print(f"  Tokens: {metadata['token_estimate']:,}")
        print(f"  Fetch Time: {metadata['fetch_time']}")
        print(f"  Method: {metadata.get('method', 'unknown')}")
        print(f"  Cached: {metadata.get('cached', False)}")

        if display_mode == "summary":
            display_summary(yaml_tree)
        elif display_mode == "full":
            display_full(yaml_content)
        elif display_mode == "links":
            display_links(yaml_tree, url)
        elif display_mode == "header":
            display_header(yaml_content)

        return yaml_content, metadata, yaml_tree

    except Exception as e:
        logger.error(f"Failed to fetch YAML: {e}", exc_info=True)
        return None, None, None


def display_header(yaml_content: str):
    """Display first 1000 characters."""
    print("\nFIRST 1000 CHARACTERS:")
    print("-" * 80)
    print(yaml_content[:1000])
    if len(yaml_content) > 1000:
        print(f"\n... ({len(yaml_content) - 1000} more characters)")


def display_summary(yaml_tree):
    """Display summary of YAML structure."""
    print("\nYAML STRUCTURE SUMMARY:")
    print("-" * 80)

    def count_elements(node):
        """Count elements by type."""
        roles = {}
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    for key in item.keys():
                        role = key.split()[0] if isinstance(key, str) else "unknown"
                        roles[role] = roles.get(role, 0) + 1
                    roles.update(count_elements(item))
        elif isinstance(node, dict):
            for key, value in node.items():
                role = key.split()[0] if isinstance(key, str) else "unknown"
                roles[role] = roles.get(role, 0) + 1
                roles.update(count_elements(value))
        return roles

    roles = count_elements(yaml_tree)
    if roles:
        print("\nElement types (top 10):")
        for role, count in sorted(roles.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {role:20s}: {count:5d}")
    else:
        print("  No elements found")


def display_full(yaml_content: str):
    """Display full YAML content."""
    print("\nFULL YAML CONTENT:")
    print("-" * 80)
    lines = yaml_content.split('\n')
    for i, line in enumerate(lines, 1):
        if i <= 100:  # Show first 100 lines
            print(line)
        else:
            print(f"... ({len(lines) - 100} more lines)")
            break


def display_links(yaml_tree, base_url: str = ""):
    """Display extracted links."""
    from src.scraper.yaml_link_parser import extract_navigation_links

    print("\nEXTRACTED NAVIGATION LINKS:")
    print("-" * 80)

    links = extract_navigation_links(yaml_tree, base_url)

    if not links:
        print("  No high-priority links found")
        return

    print(f"\nFound {len(links)} high-priority navigation links:\n")

    from collections import defaultdict
    by_type = defaultdict(list)
    for link in links:
        if link.page_type:
            by_type[link.page_type].append(link)

    for page_type in sorted(by_type.keys()):
        page_links = by_type[page_type]
        print(f"{page_type.upper()} ({len(page_links)} links):")
        for link in page_links[:3]:  # Show first 3 of each type
            print(f"  • {link.anchor_text}")
            print(f"    {link.url}")
        if len(page_links) > 3:
            print(f"  ... and {len(page_links) - 3} more")
        print()


def extract_leagues(yaml_content: str, url: str, metadata: dict):
    """Extract league data from YAML."""
    from src.extractors.yaml_extractor import extract_league_data_from_yaml

    logger.info(f"\nExtracting league data from YAML: {url}")

    try:
        leagues = extract_league_data_from_yaml(yaml_content, url, metadata)

        print("\n" + "="*80)
        print(f"EXTRACTED LEAGUES ({len(leagues)} total)")
        print("="*80)

        for i, league in enumerate(leagues, 1):
            print(f"\n{i}. {league.get('organization_name')}")
            print(f"   Sport/Season: {league.get('sport_season_code')}")
            print(f"   Day/Time: {league.get('day_of_week')} {league.get('start_time', 'TBD')}")
            print(f"   Gender: {league.get('gender_eligibility')}")
            print(f"   Fee: ${league.get('team_fee')} (team)" if league.get('team_fee') else "   Fee: TBD")
            print(f"   Completeness: {league.get('completeness_status')} ({league.get('identifying_fields_pct'):.0f}%)")

        return leagues

    except Exception as e:
        logger.error(f"Failed to extract leagues: {e}", exc_info=True)
        return None


def store_snapshot(url: str, yaml_content: str, metadata: dict, leagues: list = None):
    """Store snapshot and extracted leagues in database."""
    from src.database.snapshot_store import store_page_snapshot, update_snapshot_status

    logger.info(f"\nStoring snapshot: {url}")

    try:
        snapshot_id = store_page_snapshot(
            url=url,
            content=yaml_content,
            snapshot_type="playwright_yaml",
            content_format="yaml",
            size_bytes=metadata['yaml_size_bytes'],
            token_estimate=metadata['token_estimate'],
            metadata={
                'fetch_time': metadata['fetch_time'],
                'method': metadata.get('method', 'playwright_yaml'),
                'cached': metadata.get('cached', False),
            }
        )

        print("\n" + "="*80)
        print("SUCCESS: Snapshot stored in database")
        print("="*80)
        print(f"\nSnapshot ID: {snapshot_id}")
        print(f"URL: {url}")
        print(f"Size: {metadata['yaml_size_bytes']:,} bytes")
        print(f"Tokens: {metadata['token_estimate']:,}")

        # Update status if leagues were extracted
        if leagues:
            league_ids = [l.get('id') for l in leagues if l.get('id')]
            status = "extracted" if leagues else "pending"
            update_snapshot_status(snapshot_id, status, league_ids)
            print(f"Status: {status} ({len(leagues)} leagues)")
        else:
            print(f"Status: pending (ready for league extraction)")

        return snapshot_id

    except Exception as e:
        logger.error(f"Failed to store snapshot: {e}", exc_info=True)
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Fetch, inspect, and store YAML accessibility tree snapshots using Playwright"
    )

    parser.add_argument(
        "url",
        help="URL to fetch YAML from (e.g., https://ottawavolleysixes.com)"
    )

    parser.add_argument(
        "--mode",
        choices=["summary", "full", "links", "header"],
        default="summary",
        help="Display mode (default: summary)"
    )

    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract league data from YAML using GPT-4"
    )

    parser.add_argument(
        "--store",
        action="store_true",
        help="Store the snapshot (and extracted leagues) in the database"
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-fetch, don't use cached YAML"
    )

    # Convenience flags (map to --mode)
    parser.add_argument("--summary", action="store_const", const="summary", dest="mode")
    parser.add_argument("--full", action="store_const", const="full", dest="mode")
    parser.add_argument("--links", action="store_const", const="links", dest="mode")
    parser.add_argument("--header", action="store_const", const="header", dest="mode")

    args = parser.parse_args()

    # Fetch and inspect
    yaml_content, metadata, yaml_tree = fetch_and_inspect(
        args.url,
        args.mode,
        use_cache=not args.no_cache
    )

    if yaml_content is None:
        return 1

    # Extract leagues if requested
    leagues = None
    if args.extract:
        leagues = extract_leagues(yaml_content, args.url, metadata)
        if leagues is None:
            return 1

    # Store if requested
    if args.store:
        snapshot_id = store_snapshot(args.url, yaml_content, metadata, leagues)
        if not snapshot_id:
            return 1

    return 0


if __name__ == "__main__":
    exit(main())
