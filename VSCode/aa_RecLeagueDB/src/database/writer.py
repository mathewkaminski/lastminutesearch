"""Database insert/update operations for leagues_metadata."""

import logging
from typing import Tuple, Optional, Dict, Any
from datetime import datetime

from src.database.supabase_client import get_client
from src.database.validators import validate_extracted_data, calculate_quality_score
from src.utils.league_id_generator import (
    generate_league_id,
    check_duplicate_league,
    extract_season_year,
)

logger = logging.getLogger(__name__)

MIN_INSERT_IDENTIFYING_PCT = 50  # New records below this threshold are not inserted


def _merge_league_records(existing_data: dict, new_data: dict) -> dict:
    """Merge two league records, filling null fields from the supplementary record.

    Strategy:
    - Higher quality_score record becomes the base
    - Null fields in the base are filled from the supplement
    - league_id and created_at always preserved from existing_data

    Args:
        existing_data: Full existing record from the database
        new_data: Newly extracted record (prepared for insert)

    Returns:
        Merged record ready for update
    """
    existing_quality = existing_data.get("quality_score") or 0
    new_quality = new_data.get("quality_score") or 0

    if new_quality >= existing_quality:
        merged = new_data.copy()
        supplement = existing_data
    else:
        merged = existing_data.copy()
        supplement = new_data

    # Fill null fields from supplement
    for field, value in supplement.items():
        if field in ("league_id", "created_at"):
            continue  # Never overwrite identity fields
        if merged.get(field) is None and value is not None:
            merged[field] = value

    # Always preserve existing identity fields
    merged["league_id"] = existing_data["league_id"]
    merged["created_at"] = existing_data.get("created_at", datetime.utcnow().isoformat())

    # Recalculate quality score for the merged record
    merged["quality_score"] = calculate_quality_score(merged)

    # Take max of identifying_fields_pct (merged record is more complete)
    merged["identifying_fields_pct"] = max(
        existing_data.get("identifying_fields_pct") or 0,
        new_data.get("identifying_fields_pct") or 0,
    )

    return merged


def insert_league(data: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None, supabase_client=None) -> Tuple[str, bool]:
    """Insert league into database with deduplication and quality checks.

    Process:
    1. Validate required fields (org_name, sss_code, url)
    2. Calculate quality score
    3. Derive season_year from dates
    4. Check for duplicates (8-field uniqueness)
    5. If duplicate exists:
        a. Compare quality scores
        b. If new data is better: UPDATE existing record
        c. Else: SKIP insertion, return existing league_id
    6. If new: INSERT with generated league_id
    7. Return (league_id, is_new)

    Args:
        data: Extracted league data dict
        metadata: Optional metadata dict from html_fetcher (method, pages_visited, page_types)
        supabase_client: Optional client (or use default)

    Returns:
        (league_id, is_new)
        is_new: True if inserted, False if updated/skipped
        Returns (None, False) if new record is rejected by quality gate
        (identifying_fields_pct < MIN_INSERT_IDENTIFYING_PCT threshold).
        Note: identifying_fields_pct must be set by the caller (from the
        extractor) for the quality gate to function — if absent, it defaults
        to 0 and all new inserts are blocked.

    Raises:
        ValueError: If validation fails (missing required fields)
        Exception: If database operation fails
    """
    if supabase_client is None:
        supabase_client = get_client()

    logger.info(f"Inserting league: {data.get('organization_name', 'UNKNOWN')}")

    # Step 1: Validate
    is_valid, errors = validate_extracted_data(data)
    if not is_valid:
        error_msg = f"Validation failed: {', '.join(errors.get('errors', errors.get('missing_required', [])))}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Step 2: Prepare data
    prepared_data = _prepare_for_insert(data, metadata)
    league_id = prepared_data.get("league_id")
    quality_score = prepared_data.get("quality_score", 0)

    logger.debug(f"Quality score: {quality_score}")

    # Step 3: Check for duplicates
    existing_id = check_duplicate_league(prepared_data, supabase_client)

    if existing_id:
        logger.info(f"Duplicate detected: {existing_id} — merging records")
        try:
            existing_result = supabase_client.table("leagues_metadata").select(
                "*"
            ).eq("league_id", existing_id).execute()

            if existing_result.data:
                existing_data = existing_result.data[0]
                merged = _merge_league_records(existing_data, prepared_data)
                update_league(existing_id, merged, supabase_client)
                logger.info(
                    f"Merged: {existing_id} "
                    f"(quality: {existing_data.get('quality_score', 0)} → {merged.get('quality_score', 0)})"
                )
                return existing_id, False
        except Exception as e:
            logger.warning(f"Could not merge with existing record {existing_id}: {e}")
        return existing_id, False

    # Quality gate for new inserts only (not for merges — those always proceed)
    new_pct = prepared_data.get("identifying_fields_pct") or 0
    if new_pct < MIN_INSERT_IDENTIFYING_PCT:
        logger.info(
            f"Skipping low-quality new league ({new_pct:.0f}% < {MIN_INSERT_IDENTIFYING_PCT}%): "
            f"{prepared_data.get('organization_name')}"
        )
        return None, False

    # Step 4: Insert new league
    try:
        logger.debug(f"Inserting new league with ID: {league_id}")
        result = supabase_client.table("leagues_metadata").insert(
            prepared_data
        ).execute()

        if result.data:
            logger.info(f"Successfully inserted league: {league_id}")

            # Store vectors for this league if page_htmls are available
            if metadata and metadata.get("page_htmls"):
                try:
                    _store_vectors_for_league(
                        league_id,
                        metadata,
                        data.get("url_scraped"),
                        supabase_client
                    )
                except Exception as e:
                    logger.warning(f"Failed to store vectors for league {league_id}: {e}")
                    # Don't fail the whole operation if vector storage fails

            return league_id, True
        else:
            raise Exception("Insert returned no data")

    except Exception as e:
        error_msg = f"Failed to insert league: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def update_league(
    league_id: str, data: Dict[str, Any], supabase_client=None
) -> bool:
    """Update existing league record.

    Args:
        league_id: UUID of existing league
        data: Updated league data (should include quality_score, updated_at)
        supabase_client: Optional client

    Returns:
        True if updated successfully

    Raises:
        Exception: If update fails
    """
    if supabase_client is None:
        supabase_client = get_client()

    logger.info(f"Updating league: {league_id}")

    try:
        # Add updated_at timestamp
        update_data = data.copy()
        update_data["updated_at"] = datetime.utcnow().isoformat()

        # Execute update
        result = supabase_client.table("leagues_metadata").update(
            update_data
        ).eq("league_id", league_id).execute()

        if result.data:
            logger.info(f"Successfully updated league: {league_id}")
            return True
        else:
            raise Exception("Update returned no data")

    except Exception as e:
        error_msg = f"Failed to update league {league_id}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


def _prepare_for_insert(data: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Prepare data dict for database insertion.

    Process:
    1. Copy input dict (don't mutate)
    2. Generate league_id if not present
    3. Calculate quality_score
    4. Extract season_year from dates
    5. Set manual_review_flag and pages_scraped from metadata
    6. Add timestamps
    7. Remove None values that should stay as nulls in DB
    8. Validate data types

    Args:
        data: Raw extracted league data
        metadata: Optional metadata from html_fetcher (method, pages_visited, page_types)

    Returns:
        Prepared dict ready for Supabase insert
    """
    prepared = data.copy()

    # Generate league_id if not present
    if "league_id" not in prepared or not prepared["league_id"]:
        prepared["league_id"] = generate_league_id()

    # Calculate quality_score
    prepared["quality_score"] = calculate_quality_score(prepared)

    # Extract season_year from dates
    season_year = extract_season_year(prepared)
    if season_year:
        prepared["season_year"] = season_year

    # Set manual_review_flag and pages_scraped from metadata
    if metadata:
        method = metadata.get("method")
        pages_visited = metadata.get("pages_visited", 1)
        page_types = metadata.get("page_types", [])

        # Determine manual_review_flag
        if method == "multi_page_selenium" and pages_visited > 1:
            prepared["manual_review_flag"] = "MULTI_PAGE"
        elif method == "single_page_selenium":
            prepared["manual_review_flag"] = "MAIN_PAGE_ONLY"
        else:
            prepared["manual_review_flag"] = None

        # Set pages_scraped array
        if page_types:
            prepared["pages_scraped"] = page_types

        logger.debug(
            f"Set manual_review_flag={prepared.get('manual_review_flag')}, "
            f"pages_scraped={page_types}"
        )

    # Add timestamps
    now_iso = datetime.utcnow().isoformat()
    prepared["created_at"] = now_iso
    prepared["updated_at"] = now_iso
    prepared["is_archived"] = False

    # Convert time_played_per_week from integer minutes to PostgreSQL interval string
    tpw = prepared.get("time_played_per_week")
    if tpw is not None:
        try:
            prepared["time_played_per_week"] = f"{int(tpw)} minutes"
        except (ValueError, TypeError):
            if not isinstance(tpw, str):
                prepared["time_played_per_week"] = None

    # Handle numeric fields - convert strings to numbers if needed
    for field in ["team_fee", "individual_fee", "num_teams", "slots_left", "num_weeks", "players_per_side"]:
        if field in prepared and prepared[field] is not None:
            try:
                if field in ["team_fee", "individual_fee"]:
                    prepared[field] = float(prepared[field])
                else:
                    prepared[field] = int(prepared[field])
            except (ValueError, TypeError):
                logger.warning(f"Could not convert {field}={prepared[field]} to number")
                prepared[field] = None

    # Handle boolean fields
    for field in ["has_referee", "requires_insurance"]:
        if field in prepared and prepared[field] is not None:
            if isinstance(prepared[field], str):
                prepared[field] = prepared[field].lower() in ["true", "yes", "1"]

    # Remove fields not in schema
    schema_fields = {
        "league_id",
        "organization_id",
        "url_id",
        "organization_name",
        "url_scraped",
        "sport_season_code",
        "season_year",
        "season_start_date",
        "season_end_date",
        "day_of_week",
        "start_time",
        "num_weeks",
        "time_played_per_week",
        "stat_holidays",
        "venue_name",
        "competition_level",
        "gender_eligibility",
        "team_fee",
        "individual_fee",
        "registration_deadline",
        "num_teams",
        "slots_left",
        "has_referee",
        "requires_insurance",
        "insurance_policy_link",
        "players_per_side",
        "quality_score",
        "manual_review_flag",
        "pages_scraped",
        "completeness_status",  # NEW: League-level completeness enum
        "identifying_fields_pct",  # NEW: % of 8 identifying fields
        "page_has_multi_leagues",  # NEW: Page-level quality flag
        "created_at",
        "updated_at",
        "is_archived",
    }

    prepared = {k: v for k, v in prepared.items() if k in schema_fields}

    logger.debug(f"Prepared data: {list(prepared.keys())}")
    return prepared


def _store_vectors_for_league(
    league_id: str,
    metadata: Dict[str, Any],
    url: str,
    supabase_client
) -> None:
    """Store page vectors for a league in the league_vectors table.

    Args:
        league_id: UUID of the league
        metadata: Metadata dict containing page_htmls and page_types
        url: URL that was scraped
        supabase_client: Supabase client instance

    Returns:
        None
    """
    try:
        from src.database.vector_store import store_page_content

        page_htmls = metadata.get("page_htmls", {})
        page_types = metadata.get("page_types", [])

        logger.info(f"Storing vectors for league {league_id[:8]}... ({len(page_htmls)} pages)")

        # Store each page as a vector
        for page_type, html in page_htmls.items():
            try:
                vector_id = store_page_content(
                    league_id=league_id,
                    url=url,
                    page_type=page_type,
                    html=html,
                    metadata={"source_url": url},
                    supabase_client=supabase_client
                )
                if vector_id:
                    logger.debug(f"Stored vector {vector_id} for page {page_type}")

            except Exception as e:
                logger.warning(f"Failed to store vector for page {page_type}: {e}")
                # Continue with other pages

    except Exception as e:
        logger.warning(f"Vector storage failed for league {league_id}: {e}")
        # Don't fail the whole operation
