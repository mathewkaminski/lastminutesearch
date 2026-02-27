"""LLM-based league data extraction from YAML accessibility trees."""

import json
import logging
from typing import Optional, Dict, Any, List

import tiktoken
from openai import OpenAI

from src.config.sss_codes import validate_sss_code

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI()

# Token encoding
encoding = tiktoken.get_encoding("cl100k_base")


def extract_league_data_from_yaml(
    yaml_content: str,
    url: str,
    metadata: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Extract ALL structured league metadata from YAML using GPT-4o.

    YAML accessibility trees are:
    - Already semantic (no cleaning needed)
    - Self-documenting (includes roles like grid, row, gridcell, link)
    - Much smaller than HTML (~95% reduction)
    - Already tokenized efficiently

    Process:
    1. No cleaning needed (YAML is clean)
    2. No truncation needed (fits in context)
    3. Build extraction prompt with YAML structure guide
    4. Call GPT-4o with JSON mode
    5. Parse and validate response
    6. Validate SSS code for each league
    7. Calculate completeness for each league
    8. Return list of league dicts (same format as HTML extractor)

    Args:
        yaml_content: YAML accessibility tree content
        url: Source URL (added to output as url_scraped)
        metadata: Optional dict from yaml_fetcher with page info

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
    logger.info(f"Extracting league data from YAML: {url}")
    if metadata:
        yaml_size = metadata.get("yaml_size_bytes", 0)
        token_count = metadata.get("token_estimate", 0)
        logger.info(f"  YAML size: {yaml_size:,} bytes, ~{token_count:,} tokens")

    # Step 1: Build extraction prompt with YAML structure guide
    prompt = _build_yaml_extraction_prompt(yaml_content, url)
    logger.debug(f"Prompt length: {len(prompt)} chars")

    # Step 2: Call GPT-4o
    response = _call_gpt4(prompt)

    # Extract leagues from response (array or single object)
    leagues = response.get("leagues", [])
    if isinstance(leagues, dict):  # Handle single league returned as object
        leagues = [leagues]
    if not isinstance(leagues, list):
        raise ValueError(f"Expected 'leagues' to be list, got {type(leagues)}")

    logger.info(f"Extracted {len(leagues)} league(s) from YAML")

    # Step 3: Process each league
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
        league["completeness_status"] = _get_completeness_status(
            league["identifying_fields_pct"]
        )

        processed_leagues.append(league)

    if not processed_leagues:
        raise ValueError(f"No valid leagues extracted from {url}")

    # Step 4: Set page-level quality flag (page_has_multi_leagues)
    high_quality_count = sum(1 for l in processed_leagues if l["identifying_fields_pct"] >= 80)
    page_has_multi = high_quality_count >= 3
    for league in processed_leagues:
        league["page_has_multi_leagues"] = page_has_multi

    logger.info(
        f"Successfully extracted {len(processed_leagues)} league(s) "
        f"({high_quality_count} with 80%+ completeness)"
    )
    logger.debug(f"Extracted: {json.dumps(processed_leagues, indent=2)}")

    return processed_leagues


def _build_yaml_extraction_prompt(yaml_content: str, url: str) -> str:
    """Build extraction prompt for LLM with YAML structure guide.

    Args:
        yaml_content: YAML accessibility tree content
        url: Source URL

    Returns:
        Formatted prompt string
    """
    sss_ref = _build_sss_reference()

    prompt = f"""You are a data extraction specialist for recreational sports leagues.

Extract ALL leagues from this YAML accessibility tree and return ONLY valid JSON (no other text).

YAML STRUCTURE GUIDE:
====================
This YAML represents a page's accessibility tree with semantic roles:

- role: The semantic role (e.g., 'text', 'link', 'grid', 'row', 'gridcell', 'button', 'heading')
- name: The visible text content or aria-label
- url: (in links only) The link URL
- children: Array of child elements

COMMON PATTERNS:
- Tables: role='grid' with role='row' children containing role='gridcell' elements
- Links: role='link' with 'url' property and 'name' property
- Text: role='text' with 'name' containing the content
- Headings: role='heading' with 'name' containing text
- Nested structure shows page hierarchy

EXAMPLE YAML PATTERN (League Registration Table):
```yaml
- role: grid
  name: "Upcoming Leagues"
  children:
    - role: row
      name: "Monday Volleyball - Jan 4"
      children:
        - role: gridcell
          name: "Monday 4 Jan"
        - role: gridcell
          name: "VOLLEYBALL Co-Ed, 6v6, Indoor"
        - role: gridcell
          name: "12 weeks"
        - role: gridcell
          name: "60 min"
        - role: gridcell
          name: "$875 + TAX"
        - role: link
          name: "Register Now"
          url: "/registration/volleyball-monday"
```

From this, extract:
- organization_name: "Ottawa Volley Sixes" (from page context)
- day_of_week: "Monday"
- season_start_date: "2026-01-04" (infer year if missing)
- sport_season_code: "411" (4=Winter, 11=Volleyball)
- gender_eligibility: "CoEd"
- num_weeks: 12
- time_played_per_week: 60 (minutes)
- team_fee: 875.00

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
      "start_time": "string HH:MM:SS (earliest listed start time) or null",
      "num_weeks": "integer or null",
      "time_played_per_week": "integer (game duration in minutes, e.g. 60) or null",
      "stat_holidays": "array of objects [{{"date": "YYYY-MM-DD", "reason": "string"}}] for excluded/no-game dates, or null",
      "venue_name": "string or null",
      "competition_level": "string (e.g., Recreational, Intermediate, Competitive) or null",
      "gender_eligibility": "string (Mens|Womens|CoEd|Other) or null",
      "players_per_side": "integer (players per side on court/field, e.g. 4 for '4v4', 6 for '6v6') or null",
      "team_fee": "number (in dollars) or null",
      "individual_fee": "number (in dollars) or null",
      "registration_deadline": "string YYYY-MM-DD or null",
      "num_teams": "integer (count of unique team names if visible in standings/schedule) or null",
      "slots_left": "integer or null",
      "has_referee": "boolean or null",
      "requires_insurance": "boolean or null"
    }}
  ]
}}

INSTRUCTIONS:
- Extract ALL distinct leagues from this page
- If a page lists multiple divisions/formats (e.g., 6v6 and 8v8), extract both as separate leagues
- For dates, infer year from context (e.g., "June-August" = current/next year context)
- For time, convert "7pm" → "19:00:00", "7:30pm" → "19:30:00". If multiple start times are listed (rotating schedule), use the EARLIEST one.
- For time_played_per_week: look for patterns like "60 min", "1 hour", "90 minutes" in the league description or detail section.
- For stat_holidays: look for "No games on", "No game", "except", or holiday callouts. Convert to [{{date, reason}}] array. If month/day listed without year, infer year from season context.
- For players_per_side: extract from format strings like "6 v 6" → 6, "4 v 4" → 4, "5v5" → 5.
- For prices, extract the team_fee (most common) from currency patterns like "$875" or "$ 875 + TAX"
- For num_teams: grab from ANY source — explicit "X teams registered/enrolled", counting unique team names in a standings/schedule table, or any visible "N of X spots filled" language. Count ALL teams across all divisions for a given day/venue/gender combo. Do NOT infer or fabricate.
- Use null for any missing field
- Return ONLY the JSON object with "leagues" array, no other text

YAML ACCESSIBILITY TREE:
{yaml_content}

JSON Output:"""

    return prompt


def _build_sss_reference() -> str:
    """Build SSS code reference from config.

    Returns:
        Formatted SSS reference string
    """
    # Import here to avoid circular imports
    from src.config.sss_codes import SEASON_CODES, SPORT_CODES

    # Build reference string
    ref_lines = [
        "Format: XYY where X=Season (1-digit), YY=Sport (2-digit)",
        "",
        "SEASONS (first digit):",
    ]

    # Add season codes
    for code, season in sorted(SEASON_CODES.items()):
        ref_lines.append(f"{code} = {season}")

    ref_lines.append("")
    ref_lines.append("SPORTS (last two digits):")

    # Add common sport codes (limit to first 20 for brevity)
    for code, sport in sorted(SPORT_CODES.items())[:20]:
        ref_lines.append(f"{code} = {sport}")

    ref_lines.extend([
        "... (and more)",
        "",
        f"EXAMPLES: 101=Spring Soccer, 211=Summer Volleyball, 407=Fall Basketball",
    ])

    return "\n".join(ref_lines)


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
                temperature=0,  # Deterministic for extraction
            )

            # Parse response
            response_text = response.choices[0].message.content.strip()
            logger.debug(f"GPT-4 response: {response_text[:200]}...")

            # Try to parse JSON
            try:
                parsed = json.loads(response_text)
                return parsed
            except json.JSONDecodeError:
                # Try to extract JSON from response
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                if start >= 0 and end > start:
                    json_str = response_text[start:end]
                    parsed = json.loads(json_str)
                    return parsed
                raise ValueError(f"Could not parse JSON from response: {response_text[:200]}")

        except RateLimitError:
            if attempt < max_retries:
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                time.sleep(wait_time)
            else:
                raise

        except Exception as e:
            logger.error(f"Error calling {model}: {e}")
            if attempt < max_retries:
                logger.info(f"Retrying ({attempt}/{max_retries})")
            else:
                raise

    raise Exception(f"Failed to get response from {model} after {max_retries} retries")


def _calculate_identifying_completeness(league: Dict[str, Any]) -> float:
    """Calculate completeness based on 8 identifying fields.

    Identifying fields (from database schema):
    1. sport_season_code
    2. season_year (derived from season_start_date)
    3. venue_name
    4. day_of_week
    5. start_time
    6. competition_level
    7. gender_eligibility
    8. num_weeks

    Args:
        league: League dict

    Returns:
        Percentage (0-100) of identifying fields present
    """
    identifying_fields = [
        "sport_season_code",
        "season_start_date",  # Use for year derivation
        "venue_name",
        "day_of_week",
        "start_time",
        "competition_level",
        "gender_eligibility",
        "num_weeks",
    ]

    filled = 0
    for field in identifying_fields:
        if league.get(field) is not None:
            # For season_start_date, check if it can derive year
            if field == "season_start_date" and league.get("season_start_date"):
                filled += 1
            elif field != "season_start_date" and league.get(field):
                filled += 1

    return (filled / len(identifying_fields)) * 100


def _get_completeness_status(completeness_pct: float) -> str:
    """Get completeness status based on percentage.

    Args:
        completeness_pct: Percentage of identifying fields (0-100)

    Returns:
        Status string: COMPLETE, ACCEPTABLE, PARTIAL, or FAILED
    """
    if completeness_pct >= 80:
        return "COMPLETE"
    elif completeness_pct >= 60:
        return "ACCEPTABLE"
    elif completeness_pct >= 30:
        return "PARTIAL"
    else:
        return "FAILED"
