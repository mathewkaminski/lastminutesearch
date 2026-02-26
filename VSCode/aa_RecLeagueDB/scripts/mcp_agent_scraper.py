#!/usr/bin/env python
"""Extract leagues using a Claude agent with Playwright MCP browser tools.

Usage:
    python scripts/mcp_agent_scraper.py --url https://example.com --dry-run
    python scripts/mcp_agent_scraper.py --url https://example.com
    python scripts/mcp_agent_scraper.py --url https://example.com --force-refresh
    python scripts/mcp_agent_scraper.py --url https://example.com --log-level DEBUG
    python scripts/mcp_agent_scraper.py --url https://example.com --max-pages 10
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

CACHE_DIR = Path(__file__).parent.parent / "scrapes"
LOG_DIR = Path(__file__).parent.parent / "logs"


def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Extract leagues using Claude + Playwright MCP agent"
    )
    parser.add_argument("--url", required=True, help="URL to scrape")
    parser.add_argument(
        "--dry-run", action="store_true", help="Extract without writing to database"
    )
    parser.add_argument(
        "--force-refresh", action="store_true", help="Ignore cached snapshots"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=25,
        help="Maximum pages to visit per site (default: 25)",
    )
    return parser.parse_args(argv)


def get_cache_path(url: str, page_key: str) -> Path:
    """Return cache file path for a snapshot.

    Cache structure: scrapes/{domain}/{timestamp}_mcp_{page_key}.yaml

    Args:
        url: Source URL (used to extract domain)
        page_key: Page identifier (e.g., 'home', 'schedule')

    Returns:
        Path object for the cache file
    """
    domain = urlparse(url).netloc
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    cache_dir = CACHE_DIR / domain
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{timestamp}_mcp_{page_key}.yaml"


def load_cached_snapshots(url: str, max_age_days: int = 7) -> dict[str, str] | None:
    """Load cached MCP snapshots if fresh.

    Args:
        url: Source URL
        max_age_days: Max age in days (default 7)

    Returns:
        Dict of {page_key: snapshot_text} or None if no fresh cache
    """
    domain = urlparse(url).netloc
    cache_dir = CACHE_DIR / domain
    if not cache_dir.exists():
        return None

    yaml_files = sorted(cache_dir.glob("*_mcp_*.yaml"))
    if not yaml_files:
        return None

    # Check age of most recent file
    most_recent = yaml_files[-1]
    age_seconds = (
        datetime.utcnow()
        - datetime.fromtimestamp(most_recent.stat().st_mtime)
    ).total_seconds()

    if age_seconds > max_age_days * 86400:
        return None

    # Group files by timestamp prefix to get latest batch
    timestamps = {}
    for f in yaml_files:
        parts = f.name.split("_mcp_")
        if len(parts) == 2:
            ts = parts[0]
            page_key = parts[1].replace(".yaml", "")
            content = f.read_text(encoding="utf-8")
            # Reject stubs: old @playwright/mcp versions returned resource links
            # instead of inline trees, producing files with no real accessibility data
            if len(content) < 1000 or "```yaml" not in content:
                logging.getLogger(__name__).warning(
                    f"Cached snapshot {f.name} looks like a stub ({len(content)} bytes), skipping"
                )
                continue
            if ts not in timestamps:
                timestamps[ts] = {}
            timestamps[ts][page_key] = content

    if not timestamps:
        return None

    latest_ts = sorted(timestamps.keys())[-1]
    snapshots = timestamps[latest_ts]
    logging.getLogger(__name__).info(
        f"Loaded {len(snapshots)} cached snapshots from {latest_ts}"
    )
    return snapshots


def save_snapshots(url: str, snapshots: dict[str, str]) -> None:
    """Save MCP snapshots to cache.

    Args:
        url: Source URL
        snapshots: Dict of {page_key: snapshot_text}
    """
    domain = urlparse(url).netloc
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    cache_dir = CACHE_DIR / domain
    cache_dir.mkdir(parents=True, exist_ok=True)

    for page_key, content in snapshots.items():
        path = cache_dir / f"{timestamp}_mcp_{page_key}.yaml"
        path.write_text(content, encoding="utf-8")
        logging.getLogger(__name__).debug(f"Cached: {path}")


def setup_logging(log_level: str) -> None:
    """Configure logging to console and file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"mcp_agent_{timestamp}.log"

    logging.basicConfig(
        level=getattr(logging, log_level),
        format="[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger(__name__).info(f"Logging to {log_file}")


async def run(url: str, dry_run: bool, force_refresh: bool, max_pages: int = 25) -> dict:
    """Main async pipeline: navigate -> extract -> (write).

    Args:
        url: URL to scrape
        dry_run: If True, skip DB write
        force_refresh: If True, ignore cache
        max_pages: Maximum pages to visit per site (default 25)

    Returns:
        Result dict with stats
    """
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    from src.scraper.mcp_client import get_playwright_server_params, mcp_tools_to_anthropic_format
    from src.scraper.mcp_navigator import navigate_and_collect
    from src.extractors.yaml_extractor import extract_league_data_from_yaml
    from src.database.writer import insert_league

    logger = logging.getLogger(__name__)
    result = {
        "url": url,
        "success": False,
        "snapshots_collected": 0,
        "leagues_extracted": 0,
        "leagues_stored": 0,
        "errors": [],
    }

    # Step 1: Check cache
    snapshots = None
    if not force_refresh:
        snapshots = load_cached_snapshots(url)
        if snapshots:
            logger.info(f"Using {len(snapshots)} cached snapshots")

    # Step 2: Navigate with MCP agent if no cache
    if snapshots is None:
        logger.info("Step 1/3: Navigating with Playwright MCP agent...")
        server_params = get_playwright_server_params(headless=True)

        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_response = await session.list_tools()
                    mcp_tools = mcp_tools_to_anthropic_format(tools_response.tools)
                    logger.info(f"MCP tools available: {[t['name'] for t in mcp_tools]}")

                    snapshots = await navigate_and_collect(url, session, mcp_tools, max_pages=max_pages)

        except Exception as e:
            logger.error(f"MCP navigation failed: {e}", exc_info=True)
            result["errors"].append(f"Navigation failed: {e}")
            return result

        if not snapshots:
            result["errors"].append("No snapshots collected")
            return result

        save_snapshots(url, snapshots)
        logger.info(f"Collected {len(snapshots)} snapshots: {list(snapshots.keys())}")

    result["snapshots_collected"] = len(snapshots)

    # Step 3: Extract leagues from snapshots
    logger.info("Step 2/3: Extracting league data with GPT-4o...")
    all_leagues = []
    for page_key, snapshot_text in snapshots.items():
        try:
            leagues = extract_league_data_from_yaml(snapshot_text, url)
            all_leagues.extend(leagues)
            logger.info(f"  {page_key}: {len(leagues)} league(s)")
        except Exception as e:
            logger.warning(f"Extraction failed for {page_key}: {e}")
            result["errors"].append(f"Extraction error ({page_key}): {e}")

    result["leagues_extracted"] = len(all_leagues)

    if not all_leagues:
        result["errors"].append("No leagues extracted from snapshots")
        return result

    # Step 4: Write to DB (unless dry-run)
    if dry_run:
        logger.info(f"Step 3/3: Dry-run -- would insert {len(all_leagues)} league(s)")
        result["leagues_stored"] = len(all_leagues)
        _print_leagues(all_leagues)
    else:
        logger.info("Step 3/3: Writing to Supabase...")
        stored = 0
        for league in all_leagues:
            try:
                league_id, is_new = insert_league(
                    league,
                    metadata={"url": url, "method": "playwright_mcp"},
                )
                status = "NEW" if is_new else "UPDATED"
                logger.info(f"  [{status}] {league.get('organization_name')}: {league_id}")
                stored += 1
            except Exception as e:
                logger.warning(f"Insert failed: {e}")
                result["errors"].append(f"Insert error: {e}")
        result["leagues_stored"] = stored

    result["success"] = True
    return result


def _print_leagues(leagues: list[dict]) -> None:
    """Print extracted leagues to console."""
    print(f"\n{'='*60}")
    print(f"EXTRACTED {len(leagues)} LEAGUE(S):")
    print(f"{'='*60}")
    for i, league in enumerate(leagues, 1):
        print(f"\n[{i}] {league.get('organization_name', 'Unknown')}")
        print(f"  Sport/Season: {league.get('sport_season_code', '?')}")
        print(f"  Day: {league.get('day_of_week', '?')}")
        print(f"  Fee: ${league.get('team_fee', '?')}")
        print(f"  Venue: {league.get('venue_name', '?')}")
        print(f"  Completeness: {league.get('identifying_fields_pct', 0):.0f}%")


def main(argv=None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    logger.info(f"Starting MCP agent scraper")
    logger.info(f"  URL: {args.url}")
    logger.info(f"  Dry-run: {args.dry_run}")
    logger.info(f"  Force-refresh: {args.force_refresh}")

    result = asyncio.run(run(args.url, args.dry_run, args.force_refresh, args.max_pages))

    print(f"\n{'='*60}")
    print("RESULT SUMMARY")
    print(f"{'='*60}")
    print(f"URL:                {result['url']}")
    print(f"Status:             {'SUCCESS' if result['success'] else 'FAILED'}")
    print(f"Snapshots:          {result['snapshots_collected']}")
    print(f"Leagues extracted:  {result['leagues_extracted']}")
    print(f"Leagues stored:     {result['leagues_stored']}")
    if result["errors"]:
        print(f"Errors:             {len(result['errors'])}")
        for err in result["errors"]:
            print(f"  - {err}")

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
