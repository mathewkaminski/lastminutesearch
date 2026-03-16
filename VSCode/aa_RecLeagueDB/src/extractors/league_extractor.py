"""LLM-based league data extraction using GPT-4."""

import json
import logging
from typing import Optional, Dict, Any, List
import tiktoken
from bs4 import BeautifulSoup
from openai import OpenAI

from src.config.sss_codes import validate_sss_code
from src.extractors.html_preprocessor import HtmlPreProcessor

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI()

# Token encoding
encoding = tiktoken.get_encoding("cl100k_base")


def extract_league_data(
    html: str,
    url: str,
    metadata: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Extract ALL structured league metadata from HTML using GPT-4o.

    Process:
    1. Clean HTML (remove scripts, styles, extract text)
    2. Truncate to max 12000 tokens (supports multi-page content)
    3. Build extraction prompt with SSS reference
    4. Call GPT-4o with JSON mode
    5. Parse and validate response
    6. Validate SSS code for each league
    7. Calculate completeness for each league
    8. Return list of league dicts

    Args:
        html: Raw HTML content (possibly multi-page aggregated)
        url: Source URL (added to output as url_scraped)
        metadata: Optional dict from html_fetcher with page info

    Returns:
        List of dicts with extracted league data matching leagues_metadata schema.
        Each dict contains:
        {
            "organization_name": str (required),
            "sport_season_code": str (required, SSS format),
            "url_scraped": str (required),
            "identifying_fields_pct": float (0-100, % of 8 identifying fields),
            "completeness_status": str (COMPLETE|ACCEPTABLE|PARTIAL|FAILED),
            "page_has_multi_leagues": bool (True if page had 3+ leagues with 80%+ completeness),
            "season_start_date": Optional[str] (YYYY-MM-DD),
            "season_end_date": Optional[str],
            ... (all other fields as before)
        }

    Raises:
        ValueError: If no valid leagues can be extracted
    """
    logger.info(f"Extracting league data from: {url}")
    if metadata:
        logger.info(f"  Method: {metadata.get('method')}, Pages: {metadata.get('pages_visited')}")

    # Step 1: Pre-process HTML to extract structured hints
    preprocessor = HtmlPreProcessor()
    preprocessing_result = preprocessor.preprocess(url, html)
    preprocessing_context = preprocessor.to_context_dict(preprocessing_result)
    logger.info(f"Pre-processing: page_type={preprocessing_result.page_type}, "
                f"tables={len(preprocessing_result.extracted_tables)}, "
                f"pricing_hints={len(preprocessing_result.pricing_elements)}, "
                f"team_hints={len(preprocessing_result.team_count_hints)}")

    # Step 2: Clean HTML
    cleaned_text = _clean_html(html)
    logger.debug(f"Cleaned HTML: {len(cleaned_text)} chars")

    # Step 3: Truncate to token limit (12000 for multi-page support)
    truncated_text = _truncate_to_tokens(cleaned_text, max_tokens=12000)
    logger.debug(f"Truncated to: {len(truncated_text)} chars (~12000 tokens max)")

    # Step 4: Build enhanced prompt with preprocessing hints
    prompt = _build_extraction_prompt(truncated_text, url, preprocessing_context)
    logger.debug(f"Prompt length: {len(prompt)} chars")

    # Step 5: Call GPT-4o
    response = _call_gpt4(prompt)

    # Extract leagues from response (array or single object)
    leagues = response.get("leagues", [])
    if isinstance(leagues, dict):  # Handle single league returned as object
        leagues = [leagues]
    if not isinstance(leagues, list):
        raise ValueError(f"Expected 'leagues' to be list, got {type(leagues)}")

    logger.info(f"Extracted {len(leagues)} league(s) from page")

    # Step 6: Process each league
    processed_leagues = []
    for league in leagues:
        # Add url_scraped field
        if "url_scraped" not in league or not league.get("url_scraped"):
            league["url_scraped"] = url

        # Validate SSS code
        sss_code = league.get("sport_season_code")
        if sss_code:
            if not validate_sss_code(sss_code):
                logger.warning(f"Invalid SSS code: {sss_code}")
                league["sport_season_code"] = None

        # Validate required fields
        required_fields = ["organization_name", "sport_season_code", "url_scraped"]
        missing = [f for f in required_fields if not league.get(f)]
        if missing:
            logger.warning(f"Skipping league with missing fields {missing}")
            continue

        # Calculate completeness
        league["identifying_fields_pct"] = _calculate_identifying_completeness(league)
        league["completeness_status"] = _get_completeness_status(league["identifying_fields_pct"])

        processed_leagues.append(league)

    if not processed_leagues:
        raise ValueError(f"No valid leagues extracted from {url}")

    # Step 7: Set page-level quality flag (page_has_multi_leagues)
    high_quality_count = sum(1 for l in processed_leagues if l["identifying_fields_pct"] >= 80)
    page_has_multi = (high_quality_count >= 3)
    for league in processed_leagues:
        league["page_has_multi_leagues"] = page_has_multi

    logger.info(f"Successfully extracted {len(processed_leagues)} league(s) "
                f"({high_quality_count} with 80%+ completeness)")
    logger.debug(f"Extracted: {json.dumps(processed_leagues, indent=2)}")

    return processed_leagues


def _clean_html(html: str) -> str:
    """Clean HTML for LLM processing.

    Process:
    1. Parse with BeautifulSoup
    2. Remove: script, style, noscript tags
    3. Extract text content
    4. Collapse multiple spaces/newlines

    Args:
        html: Raw HTML content

    Returns:
        Clean text suitable for LLM
    """
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Remove unwanted tags
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # Get text
        text = soup.get_text(separator="\n", strip=True)

        # Collapse multiple newlines
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        cleaned = "\n".join(lines)

        # Collapse multiple spaces
        cleaned = " ".join(cleaned.split())

        return cleaned

    except Exception as e:
        logger.warning(f"Error cleaning HTML: {e}, returning raw text")
        return html


def _truncate_to_tokens(text: str, max_tokens: int = 8000) -> str:
    """Truncate text to token limit.

    Strategy: Keep top 6000 tokens + bottom 2000 tokens
    Rationale: Headers/menus at top, pricing/dates often at bottom

    Args:
        text: Text to truncate
        max_tokens: Maximum tokens (default 8000)

    Returns:
        Truncated text
    """
    try:
        tokens = encoding.encode(text)
        token_count = len(tokens)

        if token_count <= max_tokens:
            logger.debug(f"Text fits in token limit: {token_count} <= {max_tokens}")
            return text

        # Need to truncate: keep top + bottom
        top_tokens = int(max_tokens * 0.75)  # 6000
        bottom_tokens = max_tokens - top_tokens  # 2000

        # Get top tokens
        top_indices = tokens[:top_tokens]

        # Get bottom tokens
        bottom_indices = tokens[-bottom_tokens:]

        # Combine
        combined_indices = top_indices + bottom_indices

        # Decode back to text
        truncated = encoding.decode(combined_indices)

        logger.debug(
            f"Truncated {token_count} tokens to {len(encoding.encode(truncated))} tokens"
        )
        return truncated

    except Exception as e:
        logger.warning(f"Error truncating tokens: {e}, returning first 6000 chars")
        return text[:6000]


def _build_extraction_prompt(cleaned_text: str, url: str, preprocessing_context: Optional[Dict[str, Any]] = None) -> str:
    """Build extraction prompt for LLM with preprocessing hints.

    Args:
        cleaned_text: Cleaned HTML text
        url: Source URL
        preprocessing_context: Optional pre-extracted data hints (pricing, team counts, etc.)

    Returns:
        Formatted prompt string
    """
    sss_ref = _build_sss_reference()

    # Build preprocessing hints section if available
    preprocessing_hints = ""
    if preprocessing_context:
        hints_json = json.dumps(preprocessing_context, indent=2)

        # Check for league list hints
        league_list_count = len(preprocessing_context.get("league_list_hints", []))
        league_list_instruction = ""

        if league_list_count > 0:
            league_list_instruction = """
**IMPORTANT: LEAGUE LIST DETECTED**
This page contains a table where EACH ROW is a separate league.
The league_list_hints section below contains pre-parsed league data from table rows.
Extract EACH league from the league_list_hints as a separate record.
DO NOT merge multiple rows into one league.

"""

        preprocessing_hints = f"""
PRE-EXTRACTED STRUCTURED DATA (from HTML preprocessing):
{hints_json}

{league_list_instruction}
Use these hints to improve accuracy, especially for:
- team_fee and individual_fee (from pricing_hints OR league_list_hints)
- num_teams (from team_count_hints)
- day_of_week, start_time, venue_name (from league_list_hints if present)
- Page type identification helps narrow down what content to expect

"""

    prompt = f"""You are a data extraction specialist for recreational sports leagues.

Extract ALL leagues from this website and return ONLY valid JSON (no other text).
{preprocessing_hints}
SPORT/SEASON CODES (SSS Format - 3 digits: XYY):
{sss_ref}

OUTPUT SCHEMA (use exact field names, return null for missing fields):
{{
  "leagues": [
    {{
      "organization_name": "string (required) - League organization name",
      "sport_season_code": "string (required) - 3-digit SSS code (e.g., '201')",
      "season_start_date": "string YYYY-MM-DD or null",
      "season_end_date": "string YYYY-MM-DD or null",
      "day_of_week": "string (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) or null",
      "start_time": "string HH:MM:SS or null",
      "num_weeks": "integer or null",
      "venue_name": "string or null",
      "source_comp_level": "string (e.g., Recreational, Intermediate, Competitive) or null",
      "gender_eligibility": "string (Mens|Womens|CoEd|Other) or null",
      "team_fee": "number (in dollars) or null",
      "individual_fee": "number (in dollars) or null",
      "registration_deadline": "string YYYY-MM-DD or null",
      "num_teams": "integer or null",
      "slots_left": "integer or null",
      "has_referee": "boolean or null",
      "requires_insurance": "boolean or null"
    }}
  ]
}}

INSTRUCTIONS:
- Extract ALL distinct leagues on the page (not just the primary one)
- If a page lists multiple divisions/formats (e.g., 11v11 and 7v7), extract both as separate leagues
- For dates, infer year from context (e.g., "June-August" in 2024 context = 2024)
- For time, infer from "7pm" → "19:00:00", "7:30pm" → "19:30:00"
- Use null for any missing field
- Return ONLY the JSON object with "leagues" array, no other text

WEBSITE HTML:
{cleaned_text}

JSON Output:"""

    return prompt


def _call_gpt4(prompt: str, model: str = "gpt-4o", max_retries: int = 2) -> Dict[str, Any]:
    """Call OpenAI GPT-4o API with structured output.

    Args:
        prompt: Extraction prompt
        model: GPT model to use (default gpt-4o)
        max_retries: Number of retry attempts (default 2)

    Returns:
        Parsed JSON dict

    Raises:
        Exception: If API call fails after retries
    """
    import time
    from openai import RateLimitError

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"Calling {model} (attempt {attempt}/{max_retries})")

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,  # Low variance
                response_format={"type": "json_object"},
                max_tokens=2000
            )

            # Extract response
            content = response.choices[0].message.content

            # Parse JSON
            try:
                data = json.loads(content)
                logger.debug(f"Successfully parsed GPT-4 JSON response")
                return data
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from GPT-4: {content[:200]}")
                raise ValueError(f"GPT-4 returned invalid JSON: {str(e)}")

        except RateLimitError as e:
            wait_time = 2 ** attempt  # 2s, 4s
            logger.warning(f"Rate limit hit, waiting {wait_time}s before retry")
            if attempt < max_retries:
                time.sleep(wait_time)
            else:
                raise

        except Exception as e:
            logger.error(f"GPT-4 API error (attempt {attempt}): {str(e)}")
            if attempt >= max_retries:
                raise

    raise Exception(f"Failed to extract after {max_retries} attempts")


def _calculate_identifying_completeness(league: Dict[str, Any]) -> float:
    """Calculate % of 8 identifying fields present in league data.

    The 8 identifying fields define a unique league (from CLAUDE.md):
    1. organization_name
    2. sport_season_code
    3. season_year (derived from dates)
    4. venue_name
    5. day_of_week
    6. source_comp_level
    7. gender_eligibility
    8. num_weeks

    Args:
        league: League data dict

    Returns:
        Percentage (0-100) of identifying fields present
    """
    identifying_fields = [
        "organization_name",
        "sport_season_code",
        "season_year",
        "venue_name",
        "day_of_week",
        "source_comp_level",
        "gender_eligibility",
        "num_weeks"
    ]

    # season_year can be derived from dates
    has_season_year = bool(
        league.get("season_year") or
        league.get("season_start_date") or
        league.get("season_end_date")
    )

    # Count present fields
    present_count = sum([
        bool(league.get("organization_name")),
        bool(league.get("sport_season_code")),
        has_season_year,
        bool(league.get("venue_name")),
        bool(league.get("day_of_week")),
        bool(league.get("source_comp_level")),
        bool(league.get("gender_eligibility")),
        bool(league.get("num_weeks"))
    ])

    percentage = round((present_count / len(identifying_fields)) * 100, 2)
    return percentage


def _get_completeness_status(identifying_pct: float) -> str:
    """Map identifying field percentage to completeness status enum.

    Args:
        identifying_pct: Percentage of 8 identifying fields (0-100)

    Returns:
        Status string: COMPLETE|ACCEPTABLE|PARTIAL|FAILED
    """
    if identifying_pct >= 100:
        return "COMPLETE"
    elif identifying_pct >= 80:
        return "ACCEPTABLE"
    elif identifying_pct >= 50:
        return "PARTIAL"
    else:
        return "FAILED"


def _build_sss_reference() -> str:
    """Build condensed SSS code reference for prompt.

    Returns:
        Formatted string with season and sport codes
    """
    reference = """Season Codes (first digit):
1=Spring, 2=Summer, 3=Fall, 4=Winter, 5=Spring/Summer, 6=Fall/Winter, 7=Tournament, 9=Other

Common Sport Codes (last two digits):
01=Soccer, 02=Flag Football, 10=Basketball, 11=Volleyball, 20=Beach Volleyball,
30=Hockey, 31=Ringette, 40=Baseball, 41=Softball, 42=Cricket,
50=Swimming, 51=Diving, 60=Tennis, 61=Badminton, 70=Golf, 71=Bowling,
80=Martial Arts, 81=Boxing, 82=Wrestling, 83=Archery,
90=Cycling, 91=Running, 92=Triathlon, 99=Multi-sport

Examples: 201=Summer Soccer, 304=Winter Basketball"""

    return reference
