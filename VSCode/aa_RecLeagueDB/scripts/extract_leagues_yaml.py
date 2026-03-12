#!/usr/bin/env python
"""Extract leagues from URLs using automated YAML snapshots.

Workflow:
1. Crawl URL with smart_crawler (home + linked pages, 4-way classifier)
2. Extract league data using GPT-4 from all YAML
3. Store snapshot and extracted leagues to database

Usage:
    python extract_leagues_yaml.py https://ottawavolleysixes.com
    python extract_leagues_yaml.py https://ottawavolleysixes.com --dry-run
    python extract_leagues_yaml.py https://ottawavolleysixes.com --no-cache
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

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

from src.scraper.smart_crawler import crawl as smart_crawl
from src.extractors.yaml_extractor import extract_league_data_from_yaml
from src.database.snapshot_store import store_page_snapshot, update_snapshot_status
from src.database.writer import insert_league

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def extract_leagues_from_url(
    url: str,
    max_pages: int = 5,
    use_cache: bool = True,
    dry_run: bool = False,
    result_id: str = None,
) -> Dict[str, Any]:
    """Extract leagues from URL using smart_crawler + GPT-4 extraction.

    Process:
    1. Crawl URL with smart_crawler (home + linked pages, 4-way classifier)
    2. Extract leagues from all YAML using GPT-4
    3. Optionally store to database

    Args:
        url: URL to extract from
        max_pages: Unused — smart_crawler controls its own page budget
        use_cache: Use cached YAML (default True)
        dry_run: Don't store to database (default False)
        result_id: Optional result_id from search_results table for tracking

    Returns:
        Result dict with stats and extracted leagues
    """
    logger.info(f"Starting extraction: {url}")
    logger.info(f"  Use cache: {use_cache}, Dry run: {dry_run}")
    if result_id:
        logger.info(f"  Tracking result_id: {result_id}")

    result = {
        "url": url,
        "success": False,
        "pages_fetched": 0,
        "total_leagues": 0,
        "leagues_by_page": {},
        "leagues_stored": 0,
        "snapshot_ids": [],
        "discovered_links_count": 0,
        "errors": [],
    }

    try:
        # Step 1: Crawl URL with smart_crawler
        logger.info("\n" + "="*80)
        logger.info("STEP 1: Crawling URL with smart_crawler")
        logger.info("="*80)

        crawled_pages, category_coverage = smart_crawl(
            url,
            use_cache=use_cache,
            force_refresh=not use_cache,
        )

        logger.info(f"Crawled {len(crawled_pages)} pages")
        logger.info(f"Category coverage: { {k: len(v) for k, v in category_coverage.items()} }")

        result["pages_fetched"] = len(crawled_pages)

        # crawled_pages is List[Tuple[str, str, str]]: (url, yaml_content, full_text)
        page_data = {
            page_url: {"yaml": yaml_content, "full_text": full_text}
            for page_url, yaml_content, full_text in crawled_pages
        }
        logger.info(f"Total size: {sum(len(d['yaml'].encode()) for d in page_data.values()):,} bytes")

        # Step 2: Extract leagues from each YAML
        logger.info("\n" + "="*80)
        logger.info("STEP 2: Extracting leagues from all YAML")
        logger.info("="*80)

        all_leagues = []
        for page_url, data in page_data.items():
            yaml_content = data["yaml"]
            full_text = data.get("full_text", "")
            logger.info(f"\nExtracting from {page_url}...")

            try:
                leagues = extract_league_data_from_yaml(
                    yaml_content,
                    url=page_url,
                    full_text=full_text,
                )
                result["leagues_by_page"][page_url] = len(leagues)
                all_leagues.extend(leagues)

                logger.info(f"  Found {len(leagues)} league(s) on {page_url}")

            except Exception as e:
                error_msg = f"Failed to extract from {page_url}: {e}"
                logger.warning(error_msg)
                result["errors"].append(error_msg)

        result["total_leagues"] = len(all_leagues)

        if not all_leagues:
            raise ValueError("No leagues extracted from any page")

        logger.info(f"\nTotal: {len(all_leagues)} league(s) from {len(page_data)} page(s)")

        # Step 2.5: Insert leagues into leagues_metadata table
        if not dry_run:
            logger.info("\n" + "="*80)
            logger.info("STEP 2.5: Storing leagues to leagues_metadata")
            logger.info("="*80)

            leagues_stored = 0
            for league in all_leagues:
                try:
                    league_id, is_new = insert_league(league, metadata={"url": url})
                    leagues_stored += 1
                    status = "NEW" if is_new else "UPDATED"
                    logger.info(f"  [{status}] {league.get('organization_name')}: {league_id}")

                except ValueError as e:
                    error_msg = f"Validation error for {league.get('organization_name')}: {e}"
                    logger.warning(error_msg)
                    result["errors"].append(error_msg)

                except Exception as e:
                    error_msg = f"Failed to insert {league.get('organization_name')}: {e}"
                    logger.error(error_msg)
                    result["errors"].append(error_msg)

            result["leagues_stored"] = leagues_stored
            logger.info(f"Stored {leagues_stored}/{len(all_leagues)} leagues to leagues_metadata")
        else:
            result["leagues_stored"] = len(all_leagues)
            logger.info(f"Would store {len(all_leagues)} leagues (dry run)")

        # Step 3: Store to database (unless dry run)
        if not dry_run:
            logger.info("\n" + "="*80)
            logger.info("STEP 3: Storing to database")
            logger.info("="*80)

            for page_url, data in page_data.items():
                yaml_content = data["yaml"]
                try:
                    snapshot_id = store_page_snapshot(
                        url=url,
                        content=yaml_content,
                        snapshot_type="playwright_yaml",
                        content_format="yaml",
                        size_bytes=len(yaml_content.encode("utf-8")),
                        token_estimate=0,  # not tracked by smart_crawler
                        metadata={
                            "page_url": page_url,
                            "method": "smart_crawler",
                            "category_coverage": category_coverage,
                        },
                    )

                    result["snapshot_ids"].append(snapshot_id)
                    logger.info(f"  Stored {page_url}: {snapshot_id}")

                except Exception as e:
                    error_msg = f"Failed to store {page_url}: {e}"
                    logger.error(error_msg)
                    result["errors"].append(error_msg)

        result["success"] = True
        return result

    except Exception as e:
        logger.error(f"Extraction failed: {e}", exc_info=True)
        result["errors"].append(str(e))
        return result


def print_results(result: Dict[str, Any]):
    """Print extraction results in human-readable format."""
    print("\n" + "="*80)
    print("EXTRACTION RESULTS")
    print("="*80)

    print(f"\nURL: {result['url']}")
    status = "SUCCESS" if result['success'] else "FAILED"
    print(f"Status: {status}")
    print(f"\nPages Fetched: {result['pages_fetched']}")
    print(f"Total Leagues Extracted: {result['total_leagues']}")
    print(f"Leagues Stored to DB: {result['leagues_stored']}")

    if result["leagues_by_page"]:
        print("\nLeagues by page:")
        for page_url, count in result["leagues_by_page"].items():
            print(f"  {page_url[:60]:60s}: {count:3d} leagues")

    if result["snapshot_ids"]:
        print(f"\nSnapshots Stored: {len(result['snapshot_ids'])}")
        for snapshot_id in result["snapshot_ids"][:3]:
            print(f"  {snapshot_id}")
        if len(result["snapshot_ids"]) > 3:
            print(f"  ... and {len(result['snapshot_ids']) - 3} more")

    if result["errors"]:
        print(f"\nErrors: {len(result['errors'])}")
        for error in result["errors"][:3]:
            print(f"  WARNING: {error}")
        if len(result["errors"]) > 3:
            print(f"  ... and {len(result['errors']) - 3} more")


def main():
    parser = argparse.ArgumentParser(
        description="Extract leagues from URLs using YAML snapshots"
    )

    parser.add_argument(
        "url",
        help="URL to extract leagues from (e.g., https://ottawavolleysixes.com)",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Maximum pages to fetch (default: 5, unused — smart_crawler controls page budget)",
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-fetch, don't use cached YAML",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and display leagues without storing to database",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    # Extract leagues
    result = extract_leagues_from_url(
        args.url,
        max_pages=args.max_pages,
        use_cache=not args.no_cache,
        dry_run=args.dry_run,
    )

    # Display results
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_results(result)

    # Exit with appropriate code
    return 0 if result["success"] else 1


if __name__ == "__main__":
    exit(main())
