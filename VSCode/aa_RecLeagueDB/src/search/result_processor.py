"""Process search results: validate, prioritize, and store."""

import logging
from typing import Dict, List, Optional
from src.database.supabase_client import get_client
from src.search.url_validator import validate_url, extract_organization_name, canonicalize_url
from src.config.search_filters import KNOWN_ADULT_REC_ORGS, ADULT_REC_KEYWORDS

logger = logging.getLogger(__name__)


def calculate_priority_score(
    url: str,
    title: str,
    snippet: str,
    rank: int,
    org_name: str,
    validation_reason: str
) -> int:
    """Calculate priority using weighted scoring system.

    Scoring Components:
    - Known organization: +40 points
    - Adult rec keywords: +10 each (max 30)
    - Search rank: Diminishing returns (20 → 5 points)
    - League keywords: +10 points
    - Domain quality (.org, .ca): +10 points
    - Explicit adult rec validation: +20 points

    Priority Thresholds:
    - Priority 1 (High): 40+ points
    - Priority 2 (Medium): 20-39 points
    - Priority 3 (Low): <20 points

    Args:
        url: URL string
        title: Page title
        snippet: Page snippet/description
        rank: Search result rank (1-10+)
        org_name: Extracted organization name
        validation_reason: Validation result from validate_url()

    Returns:
        Priority level (1-3)
    """
    score = 0
    content = (title + " " + snippet).lower()

    # 1. Known organization bonus (+40 points)
    if org_name and org_name.upper() in KNOWN_ADULT_REC_ORGS:
        score += 40

    # 2. Adult rec keyword scoring (+30 points max)
    adult_matches = sum(1 for kw in ADULT_REC_KEYWORDS if kw in content)
    adult_score = min(adult_matches * 10, 30)  # Max 30 points
    score += adult_score

    # 3. Search rank bonus (diminishing returns)
    if rank <= 3:
        rank_score = 15
    elif rank <= 6:
        rank_score = 15
    elif rank <= 10:
        rank_score = 10
    else:
        rank_score = 5
    score += rank_score

    # 4. League keyword bonus (+10 points)
    league_keywords = ['league', 'register', 'registration', 'schedule']
    if any(kw in content for kw in league_keywords):
        score += 10

    # 5. Domain quality bonus (+10 points for .org, .ca)
    if any(ext in url.lower() for ext in ['.org', '.ca']):
        score += 10

    # 6. Validation reason bonus
    if validation_reason == "valid_adult_rec_league":
        score += 20

    # Convert score to priority (1-3)
    if score >= 40:
        return 1
    elif score >= 20:
        return 2
    else:
        return 3


def process_search_results(
    query_id: str,
    results: List[Dict],
    city: str = "",
    sport: str = "",
    sport_season_code: str = None
) -> Dict:
    """Process search results and store in database.

    For each result:
    1. Validate URL
    2. Extract org name
    3. Assign priority if valid
    4. Store in search_results table

    Returns:
        Summary dict with counts
    """
    client = get_client()
    valid_count = 0
    failed_count = 0

    for rank, result in enumerate(results, 1):
        try:
            url_raw = result.get("url_raw")
            page_title = result.get("page_title", "")
            page_snippet = result.get("page_snippet", "")
            search_rank = result.get("search_rank", rank)

            # Validate URL
            is_valid, validation_reason = validate_url(url_raw, page_title, page_snippet)

            # Extract org name
            org_name = extract_organization_name(url_raw, page_title)

            # Assign priority if valid
            priority = calculate_priority_score(
                url_raw, page_title, page_snippet, search_rank, org_name, validation_reason
            ) if is_valid else None

            # Canonicalize URL
            url_canonical = canonicalize_url(url_raw)

            # Build result record
            result_data = {
                'query_id': query_id,
                'url_raw': url_raw,
                'url_canonical': url_canonical,
                'search_rank': search_rank,
                'page_title': page_title,
                'page_snippet': page_snippet,
                'validation_status': 'PASSED' if is_valid else 'FAILED',
                'validation_reason': validation_reason,
                'organization_name': org_name if org_name else None,
                'priority': priority,
                'added_to_scrape_queue': False
            }

            # Insert into database
            client.table('search_results').insert(result_data).execute()

            if is_valid:
                valid_count += 1
            else:
                failed_count += 1

            logger.debug(f"Processed result {rank}/{len(results)}: {url_canonical}")

        except Exception as e:
            logger.error(f"Error processing result {rank}: {str(e)}")
            failed_count += 1
            continue

    # Update search_queries with valid count
    try:
        client.table('search_queries').update({
            'valid_results': valid_count
        }).eq('query_id', query_id).execute()
    except Exception as e:
        logger.error(f"Failed to update search_queries: {str(e)}")

    return {
        'total_results': len(results),
        'valid_results': valid_count,
        'failed_results': failed_count
    }
