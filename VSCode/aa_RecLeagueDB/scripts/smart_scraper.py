#!/usr/bin/env python
"""Smart scraper: deterministic BFS Playwright + Haiku classifier + GPT-4o extraction.

Replaces mcp_agent_scraper.py as the primary pipeline for most sites.

Usage:
    python scripts/smart_scraper.py --url https://www.ottawavolleysixes.com
    python scripts/smart_scraper.py --url https://... --dry-run
    python scripts/smart_scraper.py --url https://... --log-level DEBUG
"""
import argparse
import csv
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

CSV_COLUMNS = [
    "organization_name", "url_scraped", "sport_name", "season_name",
    "sport_season_code", "season_year", "season_start_date", "season_end_date",
    "day_of_week", "start_time", "end_time", "num_weeks", "time_played_per_week",
    "stat_holidays", "venue_name", "competition_level", "gender_eligibility",
    "team_fee", "individual_fee", "registration_deadline",
    "num_teams", "slots_left", "has_referee", "requires_insurance",
    "insurance_policy_link", "players_per_side", "team_capacity",
    "tshirts_included", "quality_score", "identifying_fields_pct",
    "page_has_multi_leagues", "base_domain", "listing_type",
    "source_url", "is_true_child",
]


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
    from src.utils.league_id_generator import deduplicate_batch, league_display_name, normalize_for_comparison

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
    crawled_pages, category_coverage, parent_map = crawl(url)
    result["pages_with_leagues"] = len(crawled_pages)

    if not crawled_pages:
        result["errors"].append("No league pages found after full crawl")
        return result

    # Phase 3: Extract from all pages
    all_leagues = []
    for page_url, yaml_content, full_text in crawled_pages:
        logger.info(f"Extracting leagues from: {page_url}")
        try:
            leagues = extract_league_data_from_yaml(
                yaml_content, page_url, full_text=full_text,
            )
            all_leagues.extend(leagues)
        except Exception as e:
            msg = f"Extraction failed for {page_url}: {e}"
            logger.warning(msg)
            result["errors"].append(msg)

    result["leagues_extracted"] = len(all_leagues)

    # Batch dedup: merge duplicates across pages before DB insert
    all_leagues = deduplicate_batch(all_leagues, parent_map=parent_map)

    # Phase 4: Write to DB
    for league in all_leagues:
        pct = league.get("identifying_fields_pct", 0)
        label = league_display_name(league)

        # Compute is_true_child for both dry-run and live paths
        source_url = league.get("source_url", league.get("url_scraped", ""))
        is_true_child = False
        if source_url in parent_map:
            parent_url = parent_map[source_url]
            parent_leagues = [
                l for l in all_leagues
                if l.get("source_url", l.get("url_scraped", "")) == parent_url
            ]
            child_sport = normalize_for_comparison(league.get("sport_name"))
            if child_sport and any(
                normalize_for_comparison(pl.get("sport_name")) == child_sport
                for pl in parent_leagues
            ):
                is_true_child = True

        league["is_true_child"] = is_true_child

        if dry_run:
            threshold = 25 if is_true_child else 50
            if pct < threshold:
                logger.info(f"  DRY-RUN SKIP ({pct:.0f}% < {threshold}%): {label}")
                result["skipped_low_quality"] += 1
            else:
                logger.info(f"  DRY-RUN ({pct:.0f}%{'*' if is_true_child else ''}): {label}")
                result["leagues_written"] += 1
            continue

        try:
            league_id, is_new = insert_league(league, is_true_child=is_true_child)
            if league_id is None:
                threshold = 25 if is_true_child else 50
                logger.info(f"  SKIP ({pct:.0f}% < {threshold}%): {label}")
                result["skipped_low_quality"] += 1
            else:
                status = "NEW" if is_new else "MERGED"
                logger.info(f"  [{status}] {league_id[:8]}... ({pct:.0f}%): {label}")
                result["leagues_written"] += 1
        except Exception as e:
            msg = f"DB write failed for {label}: {e}"
            logger.warning(msg)
            result["errors"].append(msg)

    if dry_run and all_leagues:
        from urllib.parse import urlparse
        # Only include rows that would pass the quality gate
        csv_leagues = [
            l for l in all_leagues
            if l.get("identifying_fields_pct", 0) >= (25 if l.get("is_true_child") else 50)
        ]
        domain = urlparse(url).netloc.replace("www.", "")
        csv_path = Path(__file__).parent.parent / f"dry_run_{domain}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(csv_leagues)
        logger.info(f"Dry-run CSV written: {csv_path} ({len(csv_leagues)} rows)")
        result["csv_path"] = str(csv_path)

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
