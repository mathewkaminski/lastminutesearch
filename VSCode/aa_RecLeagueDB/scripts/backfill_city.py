#!/usr/bin/env python3
"""Backfill leagues_metadata.city using two passes:

  Pass 1 — URL path extraction (highest accuracy, per-league)
            e.g. javelin.com/calgary/vball -> "Calgary"

  Pass 2 — Search query fallback (for remaining nulls only)
            Domain-level match: if a search for "Ottawa volleyball"
            found this org's root URL, use "Ottawa" as the city.
            Only applied when Pass 1 finds nothing AND only one distinct
            city is associated with that domain in search_queries (safe
            to assign; skips ambiguous multi-city orgs).

Usage:
    python scripts/backfill_city.py           # dry-run (prints plan)
    python scripts/backfill_city.py --write   # apply to DB
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.database.supabase_client import get_client
from src.utils.city_from_url import extract_city_from_url

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def _fetch_leagues(client) -> list[dict]:
    result = (
        client.table("leagues_metadata")
        .select("league_id, url_scraped, city")
        .is_("city", "null")
        .not_.is_("url_scraped", "null")
        .execute()
    )
    return result.data or []


def _build_domain_city_map(client) -> dict[str, str]:
    """Return {base_domain: city} for domains that map to exactly ONE city
    in search_queries. Skips ambiguous multi-city domains (e.g. javelin.com).
    """
    result = client.rpc("get_domain_city_map", {}).execute()
    # Fallback: build manually if RPC not available
    if not result.data:
        return _build_domain_city_map_fallback(client)
    return {row["domain"]: row["city"] for row in result.data}


def _build_domain_city_map_fallback(client) -> dict[str, str]:
    """Build domain->city map directly via Python if no RPC available."""
    result = client.table("search_results").select(
        "url_canonical, query_id"
    ).execute()
    sr_rows = result.data or []

    result2 = client.table("search_queries").select(
        "query_id, city"
    ).not_.is_("city", "null").execute()
    query_city = {r["query_id"]: r["city"] for r in (result2.data or [])}

    domain_cities: dict[str, set] = defaultdict(set)
    for row in sr_rows:
        url = row.get("url_canonical") or ""
        city = query_city.get(row.get("query_id"))
        if not city or not url:
            continue
        try:
            from urllib.parse import urlparse
            import re
            netloc = urlparse(url if "://" in url else f"https://{url}").netloc
            netloc = re.sub(r"^www\.", "", netloc).split(":")[0].lower()
            parts = netloc.split(".")
            domain = ".".join(parts[-2:]) if len(parts) > 2 else netloc
        except Exception:
            continue
        domain_cities[domain].add(city)

    # Only keep domains that map to exactly one city (unambiguous)
    return {
        domain: next(iter(cities))
        for domain, cities in domain_cities.items()
        if len(cities) == 1
    }


def _get_domain(url: str) -> str:
    """Extract bare domain (e.g. 'torontossc.com') from a URL."""
    try:
        from urllib.parse import urlparse
        import re
        netloc = urlparse(url if "://" in url else f"https://{url}").netloc
        netloc = re.sub(r"^www\.", "", netloc).split(":")[0].lower()
        parts = netloc.split(".")
        return ".".join(parts[-2:]) if len(parts) > 2 else netloc
    except Exception:
        return ""


def backfill(write: bool = False) -> None:
    client = get_client()

    leagues = _fetch_leagues(client)
    logger.info(f"Leagues with null city: {len(leagues)}")

    domain_city_map = _build_domain_city_map_fallback(client)
    logger.info(f"Unambiguous domain->city mappings: {len(domain_city_map)}")

    pass1: list[dict] = []   # URL path found city
    pass2: list[dict] = []   # search query fallback
    skipped: list[dict] = [] # no city found

    for league in leagues:
        url = league["url_scraped"]
        league_id = league["league_id"]

        # Pass 1: city from URL path
        city = extract_city_from_url(url)
        if city:
            pass1.append({"league_id": league_id, "city": city, "url": url})
            continue

        # Pass 2: search query fallback (unambiguous domains only)
        domain = _get_domain(url)
        city = domain_city_map.get(domain)
        if city:
            pass2.append({"league_id": league_id, "city": city, "url": url})
            continue

        skipped.append({"league_id": league_id, "url": url})

    # --- Summary ---
    logger.info(f"\nPass 1 (URL path):        {len(pass1)} leagues")
    logger.info(f"Pass 2 (search fallback): {len(pass2)} leagues")
    logger.info(f"Still no city:            {len(skipped)} leagues")

    # Show city distribution for pass1
    from collections import Counter
    p1_cities = Counter(r["city"] for r in pass1)
    logger.info("\nPass 1 city breakdown:")
    for city, count in p1_cities.most_common():
        logger.info(f"  {city}: {count}")

    p2_cities = Counter(r["city"] for r in pass2)
    logger.info("\nPass 2 city breakdown:")
    for city, count in p2_cities.most_common():
        logger.info(f"  {city}: {count}")

    if skipped:
        logger.info(f"\nSample unresolved URLs:")
        for r in skipped[:10]:
            logger.info(f"  {r['url'][:80]}")

    if not write:
        logger.info("\nDRY RUN — pass --write to apply changes")
        return

    # --- Write ---
    # Group by city and UPDATE with .in_() — avoids upsert INSERT issues
    all_updates = pass1 + pass2
    city_to_ids: dict[str, list[str]] = defaultdict(list)
    for r in all_updates:
        city_to_ids[r["city"]].append(r["league_id"])

    total_updated = 0
    for city, ids in city_to_ids.items():
        for i in range(0, len(ids), BATCH_SIZE):
            batch_ids = ids[i:i + BATCH_SIZE]
            client.table("leagues_metadata").update(
                {"city": city}
            ).in_("league_id", batch_ids).execute()
            total_updated += len(batch_ids)
        logger.info(f"  {city}: {len(ids)} records updated")

    logger.info(f"Total updated: {total_updated}")

    logger.info("City backfill complete.")


if __name__ == "__main__":
    write_mode = "--write" in sys.argv
    backfill(write=write_mode)
