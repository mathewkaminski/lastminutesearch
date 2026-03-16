"""Super scraper: two-pass deep crawl + team count verification + reconciliation.

Usage:
    python scripts/super_scraper.py --url https://guelphsoccerleague.ca
    python scripts/super_scraper.py --url https://... --dry-run
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

from src.scraper.deep_crawler import deep_crawl
from src.extractors.yaml_extractor import extract_league_data_from_yaml
from src.database.writer import insert_league
from src.database.leagues_reader import archive_league
from src.scraper.reconciler import reconcile, ReconcileAction
from src.database.consolidator import find_within_url_duplicates

logger = logging.getLogger(__name__)


def _get_existing_leagues(url: str) -> list[dict]:
    from src.database.supabase_client import get_client
    result = (
        get_client().table("leagues_metadata")
        .select("league_id, organization_name, num_teams, day_of_week, venue_name, "
                "source_comp_level, gender_eligibility, sport_season_code, quality_score, "
                "season_year, url_scraped")
        .eq("url_scraped", url)
        .eq("is_archived", False)
        .execute()
    )
    return result.data or []


def _run_pass2(url: str, run_id: str) -> list[dict]:
    """Pass 2: Playwright navigator → team count extraction. Returns list of extraction dicts."""
    from playwright.sync_api import sync_playwright
    from src.checkers.playwright_navigator import PlaywrightNavigator
    from src.checkers.team_count_extractor import TeamCountExtractor

    navigator = PlaywrightNavigator()
    extractor = TeamCountExtractor()
    results = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            import asyncio
            navigated_pages = asyncio.run(
                navigator.navigate(page, url, run_id, "super_scraper")
            )
            browser.close()

        for nav_page in navigated_pages:
            extraction = extractor.extract(
                nav_page.html, url=nav_page.url, nav_path=nav_page.nav_path
            )
            results.append({
                "division_name": extraction.division_name,
                "num_teams": len(extraction.team_names),
                "team_names": extraction.team_names,
                "nav_path": extraction.nav_path,
            })
    except Exception as e:
        logger.warning(f"Pass 2 failed for {url}: {e}")

    return results


def _queue_for_review(url: str, extracted: dict, existing: dict, reason: str) -> None:
    """Write a record to super_scrape_review for manual resolution."""
    from src.database.supabase_client import get_client
    try:
        get_client().table("super_scrape_review").insert({
            "url": url,
            "extracted": extracted,
            "existing_league_id": existing.get("league_id"),
            "reason": reason,
        }).execute()
    except Exception as e:
        logger.warning(f"Could not write review queue entry: {e}")


def run(url: str, dry_run: bool = False) -> dict:
    result = {
        "url": url,
        "pages_crawled": 0,
        "leagues_extracted": 0,
        "leagues_written": 0,
        "archived": 0,
        "review_queued": 0,
        "auto_consolidated": 0,
        "errors": [],
    }

    run_id = str(uuid4())
    existing_leagues = _get_existing_leagues(url)
    logger.info(f"Super scrape {url} — {len(existing_leagues)} existing records")

    # --- Pass 1: Deep YAML crawl ---
    crawl_result = deep_crawl(url)
    # deep_crawl returns (pages, coverage, parent_map) or empty list on failure
    if isinstance(crawl_result, tuple):
        league_pages = crawl_result[0]
    else:
        league_pages = crawl_result
    result["pages_crawled"] = len(league_pages)

    all_extracted: list[dict] = []
    for page_url, yaml_content, *_rest in league_pages:
        try:
            leagues = extract_league_data_from_yaml(yaml_content, page_url)
            all_extracted.extend(leagues)
        except Exception as e:
            result["errors"].append(f"Extraction failed {page_url}: {e}")

    result["leagues_extracted"] = len(all_extracted)

    # --- Pass 2: Team count verification ---
    pass2_results = _run_pass2(url, run_id)
    logger.info(f"Pass 2 found {len(pass2_results)} division(s)")

    # Enrich Pass 1 extractions with Pass 2 team counts where division matches
    for extracted in all_extracted:
        for p2 in pass2_results:
            if p2.get("num_teams") and not extracted.get("num_teams"):
                extracted["num_teams"] = p2["num_teams"]
                break

    if dry_run:
        logger.info(f"DRY-RUN: would write {len(all_extracted)} league(s)")
        result["leagues_written"] = len(all_extracted)
        return result

    # --- Reconcile + write ---
    for extracted in all_extracted:
        # Find best matching existing record (same day_of_week or first if only one)
        existing = None
        if len(existing_leagues) == 1:
            existing = existing_leagues[0]
        else:
            for ex in existing_leagues:
                if (ex.get("day_of_week") or "").lower() == (extracted.get("day_of_week") or "").lower():
                    existing = ex
                    break

        if existing is None:
            # No match — just write
            try:
                league_id, _ = insert_league(extracted)
                if league_id:
                    result["leagues_written"] += 1
            except Exception as e:
                result["errors"].append(str(e))
            continue

        action, reason = reconcile(extracted, existing)

        if action == ReconcileAction.REPLACE:
            archive_league(existing["league_id"])
            result["archived"] += 1
            try:
                league_id, _ = insert_league(extracted)
                if league_id:
                    result["leagues_written"] += 1
            except Exception as e:
                result["errors"].append(str(e))

        elif action == ReconcileAction.REVIEW:
            _queue_for_review(url, extracted, existing, reason)
            result["review_queued"] += 1

        else:  # MERGE
            try:
                league_id, _ = insert_league(extracted)
                if league_id:
                    result["leagues_written"] += 1
            except Exception as e:
                result["errors"].append(str(e))

    # --- Auto-consolidation ---
    fresh_leagues = _get_existing_leagues(url)
    dup_groups = find_within_url_duplicates(fresh_leagues)
    for group in dup_groups:
        if group.confidence == "AUTO":
            archive_league(group.archive_id)
            result["auto_consolidated"] += 1
            logger.info(f"Auto-consolidated: archived {group.archive_id[:8]} (kept {group.keep_id[:8]})")

    logger.info(
        f"Super scrape done — written={result['leagues_written']} "
        f"archived={result['archived']} review={result['review_queued']} "
        f"consolidated={result['auto_consolidated']}"
    )
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Super scraper: two-pass deep extraction")
    parser.add_argument("--url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="[%(asctime)s] %(levelname)s - %(message)s")

    result = run(args.url, dry_run=args.dry_run)
    print(f"\nSUPER SCRAPER RESULTS for {result['url']}")
    print(f"  Pages crawled:     {result['pages_crawled']}")
    print(f"  Leagues extracted: {result['leagues_extracted']}")
    print(f"  Leagues written:   {result['leagues_written']}")
    print(f"  Auto-archived:     {result['archived']}")
    print(f"  Review queued:     {result['review_queued']}")
    print(f"  Auto-consolidated: {result['auto_consolidated']}")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ERROR: {e}")
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
