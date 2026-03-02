#!/usr/bin/env python3
"""One-time backfill: set base_domain and listing_type on existing records.

Usage:
    python scripts/backfill_listing_type.py           # dry-run
    python scripts/backfill_listing_type.py --write   # apply to DB
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.database.supabase_client import get_client
from src.utils.domain_extractor import extract_base_domain
from src.utils.listing_classifier import classify_listing_type

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def backfill(write: bool = False) -> None:
    client = get_client()

    # Fetch all records needing backfill
    result = (
        client.table("leagues_metadata")
        .select("league_id, url_scraped, num_weeks, team_fee, individual_fee, base_domain, listing_type")
        .execute()
    )
    rows = result.data or []
    logger.info(f"Fetched {len(rows)} total records")

    to_update = []
    for row in rows:
        new_domain = extract_base_domain(row.get("url_scraped"))
        new_type = classify_listing_type(row) if row.get("listing_type") in (None, "unknown") else row["listing_type"]
        needs_update = (row.get("base_domain") != new_domain) or (row.get("listing_type") != new_type)
        if needs_update:
            to_update.append({
                "league_id": row["league_id"],
                "base_domain": new_domain,
                "listing_type": new_type,
            })

    counts = {"league": 0, "drop_in": 0, "unknown": 0}
    for item in to_update:
        counts[item["listing_type"]] += 1

    logger.info(f"Records to update: {len(to_update)}")
    logger.info(f"  league={counts['league']}  drop_in={counts['drop_in']}  unknown={counts['unknown']}")

    if not write:
        logger.info("DRY RUN — pass --write to apply changes")
        return

    # Batch upsert
    for i in range(0, len(to_update), BATCH_SIZE):
        batch = to_update[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        try:
            client.table("leagues_metadata").upsert(batch, on_conflict="league_id").execute()
            logger.info(f"  Updated batch {batch_num} ({len(batch)} records)")
        except Exception as exc:
            logger.error(f"  Batch {batch_num} failed: {exc}")
            raise

    logger.info("Backfill complete.")


if __name__ == "__main__":
    write_mode = "--write" in sys.argv
    backfill(write=write_mode)
