"""Extraction pipeline orchestrator - ties all phases together."""

import argparse
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
import sys
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.database.supabase_client import get_client
from src.scraper.html_fetcher import fetch_html_multi_page
from src.extractors.league_extractor import extract_league_data
from src.database.writer import insert_league


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure logging to console + file.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured logger
    """
    # Create logs directory
    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Timestamp for log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"extraction_{timestamp}.log"

    # Root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_format = logging.Formatter(
        "[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(console_format)
    logger.addHandler(file_handler)

    logger.info(f"Logging initialized. Log file: {log_file}")
    return logging.getLogger(__name__)


def pull_from_queue(limit: int = 1, supabase_client=None) -> List[Dict[str, Any]]:
    """Pull URLs from scrape_queue.

    Query:
        SELECT scrape_id, url, organization_name, sport_season_code
        FROM scrape_queue
        WHERE status = 'PENDING'
        ORDER BY priority ASC, created_at ASC
        LIMIT {limit}

    Args:
        limit: Number of URLs to pull (0 = all)
        supabase_client: Optional Supabase client

    Returns:
        List of dicts with scrape_id, url, metadata
    """
    if supabase_client is None:
        supabase_client = get_client()

    logger = logging.getLogger(__name__)
    logger.info(f"Pulling URLs from queue (limit={limit})")

    try:
        query = supabase_client.table("scrape_queue").select(
            "scrape_id, url, organization_name, sport_season_code, priority"
        ).eq("status", "PENDING").order("priority", desc=False).order(
            "created_at", desc=False
        )

        if limit > 0:
            query = query.limit(limit)

        result = query.execute()

        urls = result.data
        logger.info(f"Pulled {len(urls)} URL(s) from queue")
        return urls

    except Exception as e:
        logger.error(f"Failed to pull from queue: {e}")
        raise


def update_queue_status(
    scrape_id: str, status: str, error_msg: str = None, supabase_client=None
) -> bool:
    """Update scrape_queue status.

    Args:
        scrape_id: UUID of scrape_queue record
        status: New status (PENDING, IN_PROGRESS, COMPLETED, FAILED)
        error_msg: Error message if FAILED
        supabase_client: Optional client

    Returns:
        True if successful
    """
    if supabase_client is None:
        supabase_client = get_client()

    logger = logging.getLogger(__name__)

    try:
        update_data = {
            "status": status,
            "last_scraped_at": datetime.utcnow().isoformat(),
        }

        if error_msg:
            update_data["error_message"] = error_msg

        if status == "IN_PROGRESS":
            update_data["scrape_attempts"] = supabase_client.table(
                "scrape_queue"
            ).select("scrape_attempts").eq("scrape_id", scrape_id).execute().data[0][
                "scrape_attempts"
            ] + 1

        result = supabase_client.table("scrape_queue").update(update_data).eq(
            "scrape_id", scrape_id
        ).execute()

        logger.debug(f"Updated scrape_queue {scrape_id} → {status}")
        return True

    except Exception as e:
        logger.error(f"Failed to update queue status: {e}")
        return False


def process_url(
    url: str,
    scrape_id: Optional[str] = None,
    dry_run: bool = False,
    use_cache: bool = True,
    force_refresh: bool = False,
    supabase_client=None,
) -> Dict[str, Any]:
    """Process a single URL through the extraction pipeline.

    Process:
    1. Update queue status → IN_PROGRESS
    2. Fetch HTML with multi-page navigation
    3. Extract league data with GPT-4o
    4. Validate and insert into database
    5. Update queue status → COMPLETED
    6. Return result

    Args:
        url: URL to process
        scrape_id: Optional queue ID (for status updates)
        dry_run: If True, skip database insert
        use_cache: If True, use cached HTML if available
        force_refresh: If True, skip cache and re-scrape
        supabase_client: Optional client

    Returns:
        Result dict:
        {
            'url': str,
            'success': bool,
            'league_id': str or None,
            'quality_score': int or None,
            'pages_visited': int,
            'manual_review_flag': str or None,
            'error': str or None,
            'duration_seconds': float
        }
    """
    if supabase_client is None:
        supabase_client = get_client()

    logger = logging.getLogger(__name__)
    start_time = time.time()

    result = {
        "url": url,
        "success": False,
        "league_id": None,
        "quality_score": None,
        "pages_visited": None,
        "manual_review_flag": None,
        "error": None,
        "duration_seconds": 0,
    }

    try:
        # Update status to IN_PROGRESS
        if scrape_id:
            update_queue_status(scrape_id, "IN_PROGRESS", supabase_client=supabase_client)

        logger.info(f"Processing: {url}")

        # Step 1: Fetch HTML with multi-page navigation
        logger.info("Step 1/4: Fetching HTML with multi-page navigation...")
        html, fetch_metadata = fetch_html_multi_page(url, use_cache=use_cache and not force_refresh)
        logger.info(
            f"  Fetched {fetch_metadata.get('pages_visited')} pages "
            f"({', '.join(fetch_metadata.get('page_types', []))})"
        )

        # Step 2: Extract league data (returns list of leagues)
        logger.info("Step 2/4: Extracting league data with GPT-4o...")
        leagues = extract_league_data(html, url, fetch_metadata)
        logger.info(f"  Extracted {len(leagues)} league(s)")

        # Calculate average completeness
        completeness_values = [l.get("identifying_fields_pct", 0) for l in leagues]
        avg_completeness = round(sum(completeness_values) / len(completeness_values), 2) if completeness_values else 0

        result["leagues_extracted"] = len(leagues)
        result["avg_completeness"] = avg_completeness
        result["pages_visited"] = fetch_metadata.get("pages_visited")
        result["manual_review_flag"] = fetch_metadata.get("manual_review_flag")

        # Step 3: Insert into database (if not dry-run)
        if dry_run:
            logger.info("Step 3/4: Dry-run mode - skipping database insert")
            result["league_ids"] = ["DRY_RUN"] * len(leagues)
            result["success"] = True
        else:
            logger.info("Step 3/4: Inserting into database...")
            league_ids = []
            for i, league_data in enumerate(leagues):
                league_id, is_new = insert_league(league_data, fetch_metadata, supabase_client)
                league_ids.append(league_id)
                completeness = league_data.get("completeness_status", "UNKNOWN")
                logger.info(
                    f"  [{i+1}/{len(leagues)}] Inserted {league_id} "
                    f"(completeness={completeness}, new={is_new})"
                )
            result["league_ids"] = league_ids
            result["success"] = True

        # Step 4: Update queue status
        if scrape_id:
            logger.info("Step 4/4: Updating queue status...")
            update_queue_status(
                scrape_id, "COMPLETED", supabase_client=supabase_client
            )
            logger.info(f"Updated scrape_queue {scrape_id} → COMPLETED")

        duration = time.time() - start_time
        result["duration_seconds"] = round(duration, 2)

        logger.info(
            f"[SUCCESS] Processed {url} in {duration:.1f}s, "
            f"leagues={len(leagues)}, avg_completeness={avg_completeness}%"
        )

        return result

    except Exception as e:
        error_msg = str(e)
        result["error"] = error_msg
        result["success"] = False

        logger.error(f"❌ Error processing {url}: {error_msg}")
        logger.exception("Full traceback:")

        # Update queue status to FAILED
        if scrape_id:
            update_queue_status(
                scrape_id, "FAILED", error_msg=error_msg[:200],
                supabase_client=supabase_client
            )

        duration = time.time() - start_time
        result["duration_seconds"] = round(duration, 2)

        return result


def main():
    """Main pipeline orchestrator with CLI interface."""
    parser = argparse.ArgumentParser(
        description="RecSportsDB Extraction Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with single URL (bypass queue)
  python scripts/extract_pipeline.py --url https://ottawaadultsoccer.com

  # Process 1 URL from queue
  python scripts/extract_pipeline.py --limit 1

  # Process all URLs in queue
  python scripts/extract_pipeline.py --limit 0

  # Dry-run mode (no database insert)
  python scripts/extract_pipeline.py --url https://ottawaadultsoccer.com --dry-run
        """,
    )

    parser.add_argument(
        "--url",
        type=str,
        help="Process single URL (bypasses queue)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Number of URLs to process from queue (default: 1, 0=all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip database insert (test mode)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Skip cache and re-scrape URLs",
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.log_level)
    logger.info("=" * 60)
    logger.info("RecSportsDB Extraction Pipeline")
    logger.info("=" * 60)

    try:
        supabase_client = get_client()

        # Determine URLs to process
        if args.url:
            # Single URL mode
            logger.info(f"Single URL mode: {args.url}")
            urls = [{"url": args.url, "scrape_id": None}]
        else:
            # Queue mode
            urls = pull_from_queue(limit=args.limit, supabase_client=supabase_client)

        if not urls:
            logger.info("No URLs to process")
            return

        logger.info(f"Processing {len(urls)} URL(s)")

        # Process each URL
        results = []
        for idx, url_record in enumerate(urls, 1):
            url = url_record.get("url")
            scrape_id = url_record.get("scrape_id")

            logger.info(f"\n[{idx}/{len(urls)}] {url}")

            result = process_url(
                url,
                scrape_id=scrape_id,
                dry_run=args.dry_run,
                use_cache=True,
                force_refresh=args.force_refresh,
                supabase_client=supabase_client,
            )

            results.append(result)

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 60)

        total = len(results)
        success = sum(1 for r in results if r["success"])
        failed = total - success
        avg_quality = (
            sum(r["quality_score"] for r in results if r["quality_score"])
            / success
            if success > 0
            else 0
        )
        total_duration = sum(r["duration_seconds"] for r in results)

        logger.info(f"Total URLs: {total}")
        logger.info(f"Success: {success}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Success Rate: {success/total*100:.1f}%")
        logger.info(f"Avg Quality Score: {avg_quality:.0f}")
        logger.info(f"Total Duration: {total_duration:.1f}s")
        logger.info(f"Avg Duration per URL: {total_duration/total:.1f}s")

        # Print failures
        failures = [r for r in results if not r["success"]]
        if failures:
            logger.warning(f"\nFailed URLs ({len(failures)}):")
            for r in failures:
                logger.warning(f"  - {r['url']}: {r['error'][:100]}")

        logger.info("=" * 60)

        # Exit code
        sys.exit(0 if failed == 0 else 1)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    main()
