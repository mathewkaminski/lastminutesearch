#!/usr/bin/env python
"""Smart scraper: deterministic BFS Playwright + Haiku classifier + GPT-4o extraction.

Replaces mcp_agent_scraper.py as the primary pipeline for most sites.

Usage:
    python scripts/smart_scraper.py --url https://www.ottawavolleysixes.com
    python scripts/smart_scraper.py --url https://... --dry-run
    python scripts/smart_scraper.py --url https://... --log-level DEBUG
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

LOG_DIR = Path(__file__).parent.parent / "logs"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smart crawler: BFS Playwright + Haiku classifier + GPT-4o extraction"
    )
    parser.add_argument("--url", required=True, help="Base URL to crawl")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print results without writing to DB"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def setup_logging(log_level: str) -> None:
    from datetime import datetime
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"smart_scraper_{ts}.log"
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger(__name__).info(f"Logging to {log_file}")


def run(url: str, dry_run: bool) -> dict:
    from src.scraper.smart_crawler import crawl
    from src.extractors.yaml_extractor import extract_league_data_from_yaml
    from src.database.writer import insert_league

    logger = logging.getLogger(__name__)
    result = {
        "url": url,
        "pages_with_leagues": 0,
        "leagues_extracted": 0,
        "leagues_written": 0,
        "skipped_low_quality": 0,
        "errors": [],
    }

    # Phase 1+2: Navigate + classify
    logger.info(f"Starting smart crawl: {url}")
    league_pages = crawl(url)
    result["pages_with_leagues"] = len(league_pages)

    if not league_pages:
        result["errors"].append("No league pages found after full crawl")
        return result

    # Phase 3: Extract + write
    for page_url, yaml_content in league_pages:
        logger.info(f"Extracting leagues from: {page_url}")
        try:
            leagues = extract_league_data_from_yaml(yaml_content, page_url)
            result["leagues_extracted"] += len(leagues)
        except Exception as e:
            msg = f"Extraction failed for {page_url}: {e}"
            logger.warning(msg)
            result["errors"].append(msg)
            continue

        for league in leagues:
            pct = league.get("identifying_fields_pct", 0)
            label = (
                f"{league.get('day_of_week')} | "
                f"{(league.get('venue_name') or '')[:25]} | "
                f"{league.get('gender_eligibility')}"
            )

            if dry_run:
                logger.info(f"  DRY-RUN ({pct:.0f}%): {label}")
                result["leagues_written"] += 1
                continue

            try:
                league_id, is_new = insert_league(league)
                if league_id is None:
                    logger.info(f"  SKIP (writer rejected, low quality {pct:.0f}%): {label}")
                    result["skipped_low_quality"] += 1
                else:
                    status = "NEW" if is_new else "MERGED"
                    logger.info(f"  [{status}] {league_id[:8]}... ({pct:.0f}%): {label}")
                    result["leagues_written"] += 1
            except Exception as e:
                msg = f"DB write failed for {label}: {e}"
                logger.warning(msg)
                result["errors"].append(msg)

    return result


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    logger.info(f"Smart scraper starting")
    logger.info(f"  URL:      {args.url}")
    logger.info(f"  Dry-run:  {args.dry_run}")

    result = run(args.url, args.dry_run)

    print(f"\n{'='*60}")
    print("SMART SCRAPER RESULTS")
    print(f"{'='*60}")
    print(f"Pages with leagues:   {result['pages_with_leagues']}")
    print(f"Leagues extracted:    {result['leagues_extracted']}")
    print(f"Leagues written:      {result['leagues_written']}")
    print(f"Skipped (low quality): {result['skipped_low_quality']}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
        for err in result["errors"]:
            print(f"  ERROR: {err}")

    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
