"""LLM-based league data extraction from YAML accessibility trees."""

import json
import logging
import re
from typing import Optional, Dict, Any, List

import anthropic

from src.config.sss_codes import validate_sss_code, build_sss_code
from src.utils.comp_level_normalizer import normalize_comp_level

logger = logging.getLogger(__name__)


def extract_league_data_from_yaml(
    yaml_content: str,
    url: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    full_text: str = "",
) -> List[Dict[str, Any]]:
    """Extract ALL structured league metadata from YAML using Claude.

    YAML accessibility trees are:
    - Already semantic (no cleaning needed)
    - Self-documenting (includes roles like grid, row, gridcell, link)
    - Much smaller than HTML (~95% reduction)
    - Already tokenized efficiently

    Process:
    1. No cleaning needed (YAML is clean)
    2. No truncation needed (fits in context)
    3. Build extraction prompt with YAML structure guide
    4. Call Claude with JSON output instruction
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
    prompt = _build_yaml_extraction_prompt(yaml_content, url, full_text=full_text)
    logger.debug(f"Prompt length: {len(prompt)} chars")

    # Step 2: Call Claude
    response = _call_claude(prompt)

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

        # Derive SSS code from sport_name + season_name (primary path)
        sport_name = league.get("sport_name")
        season_name = league.get("season_name")
        if sport_name and season_name:
            # Normalize season: "Late Winter" -> "Winter", "Early Spring" -> "Spring"
            season_normalized = season_name.strip()
            for prefix in ("Late ", "Early ", "Mid ", "Mid-"):
                if season_normalized.lower().startswith(prefix.lower()):
                    season_normalized = season_normalized[len(prefix):]
            derived_sss = build_sss_code(season_normalized, sport_name)
            if derived_sss:
                league["sport_season_code"] = derived_sss
            elif not league.get("sport_season_code"):
                logger.warning(
                    f"Could not derive SSS from sport={sport_name}, "
                    f"season={season_name}"
                )

        # Validate SSS code if present (from LLM or derived)
        sss_code = league.get("sport_season_code")
        if sss_code and not validate_sss_code(sss_code):
            logger.warning(f"Invalid SSS code: {sss_code}")
            league["sport_season_code"] = None

        # Validate required fields (sport_name replaces sport_season_code)
        required_fields = ["organization_name", "sport_name", "url_scraped"]
        missing = [f for f in required_fields if not league.get(f)]
        if missing:
            logger.warning(f"Skipping league with missing fields {missing}")
            continue

        # Validate players_per_side against URL NvN patterns
        url_nvn = _extract_nvn_from_url(league.get("url_scraped", ""))
        llm_pps = league.get("players_per_side")
        if url_nvn and llm_pps and url_nvn != llm_pps:
            logger.info(
                f"Overriding players_per_side: LLM={llm_pps} → URL={url_nvn} "
                f"(from {league.get('url_scraped', '')})"
            )
            league["players_per_side"] = url_nvn

        # Normalize standardized_comp_level via fallback if LLM didn't set it
        # Coerce empty strings to None
        if league.get("standardized_comp_level") in ("", None):
            league["standardized_comp_level"] = None
        # Validate LLM output: must be single uppercase A-Z letter
        std = league.get("standardized_comp_level")
        if std and (len(str(std)) != 1 or not str(std).isalpha()):
            league["standardized_comp_level"] = None
        elif std:
            league["standardized_comp_level"] = str(std).upper()
        # Fallback: derive from source_comp_level if still null
        if league.get("standardized_comp_level") is None and league.get("source_comp_level"):
            league["standardized_comp_level"] = normalize_comp_level(league["source_comp_level"])

        # Default "None Found" when no comp level was extracted
        if not league.get("source_comp_level") or not str(league["source_comp_level"]).strip():
            league["source_comp_level"] = "None Found"
            league["standardized_comp_level"] = "A"

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


def _extract_nvn_from_url(url: str) -> Optional[int]:
    """Extract players_per_side from NvN patterns in URL.

    Matches patterns like: 7v7, 7vs7, 7-v-7, 6v6, 5vs5, 4on4
    Returns the number (e.g., 7) or None if no pattern found.
    """
    if not url:
        return None
    match = re.search(r'(\d+)\s*(?:v|vs|on|-v-)\s*(\d+)', url, re.IGNORECASE)
    if match and match.group(1) == match.group(2):
        return int(match.group(1))
    return None


_MAX_YAML_CHARS = 60000  # ~15-18K tokens; only trim truly huge pages (standings tables)
_TRIM_HEAD = 30000
_TRIM_MID = 20000
_TRIM_TAIL = 10000


def _trim_yaml(yaml_content: str) -> str:
    """Sample head + middle + tail to stay within token budget.

    Large pages (e.g. full standings tables) often have most league metadata
    at the top.  We take a generous head, a mid-section, and a tail so we
    don't miss registration details buried after the standings.
    """
    if len(yaml_content) <= _MAX_YAML_CHARS:
        return yaml_content
    head = yaml_content[:_TRIM_HEAD]
    mid_start = (len(yaml_content) - _TRIM_MID) // 2
    mid = yaml_content[mid_start: mid_start + _TRIM_MID]
    tail = yaml_content[-_TRIM_TAIL:]
    return head + "\n[...]\n" + mid + "\n[...]\n" + tail


def _build_yaml_extraction_prompt(yaml_content: str, url: str, full_text: str = "") -> str:
    """Build extraction prompt for LLM with YAML structure guide.

    When full_text is provided, uses a two-tier prompt that combines the YAML
    accessibility tree with the full page text for richer field extraction.

    Args:
        yaml_content: YAML accessibility tree content
        url: Source URL
        full_text: Optional full page text for detail pages

    Returns:
        Formatted prompt string
    """
    yaml_content = _trim_yaml(yaml_content)

    schema_instructions = f"""OUTPUT SCHEMA (use exact field names, return null for missing fields):
{{
  "leagues": [
    {{
      "organization_name": "string (required) - League organization name",
      "sport_name": "string (required) - Sport name exactly as described on the page (e.g., 'Soccer', 'Volleyball', 'Flag Football', 'Ball Hockey', 'Dodgeball', '3-Pitch Softball')",
      "season_name": "string (required) - Season label exactly as described on the page (e.g., 'Late Winter', 'Winter', 'Spring', 'Summer', 'Fall'). Use the page's own wording.",
      "season_start_date": "string YYYY-MM-DD or null",
      "season_end_date": "string YYYY-MM-DD or null",
      "day_of_week": "string (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) or null",
      "start_time": "string HH:MM:SS (earliest listed start time) or null",
      "num_weeks": "integer or null",
      "time_played_per_week": "integer (game duration in minutes, e.g. 60) or null",
      "stat_holidays": "array of objects [{{"date": "YYYY-MM-DD", "reason": "string"}}] for excluded/no-game dates, or null",
      "venue_name": "string or null",
      "source_comp_level": "string - competition level EXACTLY as described on the page (e.g., 'A League', 'Gold Division', 'Competitive', 'Recreational'). Preserve the league's own wording. null if not specified.",
      "standardized_comp_level": "string - single letter A-Z ranking. A=most competitive, then B, C, D descending. Map: Competitive/A/Gold/Premier/Division 1 → A, Intermediate/B/Silver → B, Recreational/C/Bronze/House → C. Use the league's own hierarchy. null if unclear.",
      "gender_eligibility": "string (Mens|Womens|CoEd|Other) or null",
      "players_per_side": "integer — parse from format strings like '7v7'→7, '6 v 6'→6, '5vs5'→5, '4 on 4'→4. Check headings, URLs, and league names FIRST. Do NOT guess from roster size or other indirect clues. null if no NvN pattern found.",
      "team_fee": "number (in dollars) or null",
      "individual_fee": "number (in dollars) or null",
      "registration_deadline": "string YYYY-MM-DD or null",
      "num_teams": "integer (count of unique team names if visible in standings/schedule) or null",
      "slots_left": "integer or null",
      "has_referee": "boolean or null",
      "requires_insurance": "boolean or null",
      "insurance_policy_link": "string (URL to insurance or waiver policy page) or null",
      "team_capacity": "integer (max roster size per team) or null",
      "tshirts_included": "boolean (whether league provides jerseys/pinnies/t-shirts) or null",
      "end_time": "string HH:MM:SS (latest game end time, e.g. if games run 7-11pm use 23:00:00) or null"
    }}
  ]
}}

INSTRUCTIONS:
- Extract ALL distinct leagues from this page
- sport_name: Use the ACTUAL sport name from the page. "Ball Hockey" not "Ice Hockey". "3-Pitch Softball" not "Baseball". Read the page heading and content carefully.
- season_name: Use the page's own season label. If the page says "Late Winter 2026 Leagues", use "Late Winter". If it says "Summer", use "Summer".
- If a page lists multiple divisions/formats (e.g., 6v6 and 8v8), extract both as separate leagues
- CRITICAL: If a page describes multiple divisions, tiers, or skill levels for the SAME sport (e.g., "A League" and "B League", "Division 1" and "Division 2", "Gold" and "Silver", "Competitive" and "Recreational"), extract EACH division as a SEPARATE league entry. Each gets its own source_comp_level and standardized_comp_level. Example: "Women's A League (competitive)" and "Women's B League (recreational)" on the same night = TWO separate league entries.
- For dates, infer year from context (e.g., "June-August" = current/next year context)
- For time, convert "7pm" → "19:00:00", "7:30pm" → "19:30:00". If multiple start times are listed (rotating schedule), use the EARLIEST one.
- For time_played_per_week: look for patterns like "60 min", "1 hour", "90 minutes" in the league description or detail section.
- For stat_holidays: look for "No games on", "No game", "except", or holiday callouts. Convert to [{{date, reason}}] array. If month/day listed without year, infer year from season context.
- For players_per_side: extract ONLY from explicit NvN format strings ("7v7"→7, "6 v 6"→6, "5vs5"→5, "4 on 4"→4). Check the URL, page heading, and league name first — these are the most reliable sources. Do NOT infer from roster sizes, team lists, or other indirect information. Return null if no NvN pattern is found.
- For prices, extract the team_fee (most common) from currency patterns like "$875" or "$ 875 + TAX"
- For num_teams: grab from ANY source — explicit "X teams registered/enrolled", counting unique team names in a standings/schedule table, or any visible "N of X spots filled" language. Count ALL teams across all divisions for a given day/venue/gender combo. Do NOT infer or fabricate.
- For insurance_policy_link: extract any URL linked from insurance/waiver text (e.g., "policy at https://...", "insurance form here")
- For team_capacity: look for "max roster", "roster limit", "up to N players per team", "max N per roster". Return the integer limit or null.
- For tshirts_included: look for "jerseys provided", "t-shirts included", "pinnies provided", "shirts included". Return true/false or null if not mentioned.
- For end_time: if a time window is given (e.g., "games 7-11pm", "7:00 PM - 10:30 PM"), extract the END time. Convert to HH:MM:SS format. If only a start time is given, return null for end_time.
- Use null for any missing field
- Return ONLY the JSON object with "leagues" array, no other text"""

    if full_text.strip():
        prompt = f"""You are extracting structured league data. You have two inputs:

1. YAML ACCESSIBILITY TREE - shows page structure, headings, links, form elements
2. FULL PAGE TEXT - contains the actual text content visible to users

Use the YAML tree to understand page layout and navigation.
Extract ALL field values from the full page text. Look carefully for:
- Specific times ("7:00 PM", "games start at 8pm")
- Durations ("10-week season", "60-minute games", "12 games")
- Dates ("Season runs Jan 6 - Mar 24", "Registration closes Dec 15")
- Fees ("$150/player", "$1200/team")
- Venue details ("Games played at Greenwood Arena")
- Format details ("6v6", "refereed games", "insurance required")
- Insurance policy URLs

These values are often in paragraph text, list items, or table cells.
Do NOT return null if the information appears anywhere in the text.

--- YAML ACCESSIBILITY TREE ---
{yaml_content}

--- FULL PAGE TEXT ---
{full_text}

{schema_instructions}

JSON Output:"""
    else:
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
- sport_name: "Volleyball" (from the gridcell text)
- season_name: "Winter" (from page context / heading)
- day_of_week: "Monday"
- season_start_date: "2026-01-04" (infer year if missing)
- gender_eligibility: "CoEd"
- num_weeks: 12
- time_played_per_week: 60 (minutes)
- team_fee: 875.00

{schema_instructions}

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


def _call_claude(prompt: str, model: str = "claude-sonnet-4-6", max_retries: int = 2) -> Dict[str, Any]:
    """Call Claude API for structured league extraction.

    Args:
        prompt: Extraction prompt
        model: Claude model to use (default claude-sonnet-4-6)
        max_retries: Number of retry attempts (default 2)

    Returns:
        Parsed JSON dict

    Raises:
        Exception: If API call fails after retries
    """
    import time
    from anthropic import RateLimitError

    client = anthropic.Anthropic()

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"Calling {model} (attempt {attempt}/{max_retries})")

            response = client.messages.create(
                model=model,
                max_tokens=4096,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()
            logger.debug(f"Claude response: {response_text[:200]}...")

            # Try to parse JSON directly
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                # Strip markdown code fences if present
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                if start >= 0 and end > start:
                    candidate = response_text[start:end]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # Response is truncated mid-object (output token limit hit).
                        # Salvage complete league objects by trimming at last valid '},'
                        # boundary and closing the array/wrapper.
                        last_complete = candidate.rfind("},")
                        if last_complete > 0:
                            salvaged = candidate[: last_complete + 1] + "\n  ]\n}"
                            try:
                                return json.loads(salvaged)
                            except json.JSONDecodeError:
                                pass
                raise ValueError(f"Could not parse JSON from response: {response_text[:200]}")

        except RateLimitError:
            if attempt < max_retries:
                wait_time = 65  # wait for the per-minute window to reset
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
    """Calculate completeness based on the 9-field identity key.

    Uses the same IDENTIFYING_FIELDS as league_id_generator to keep the
    quality gate aligned with the dedup identity model:
    1. organization_name
    2. sport_name
    3. season_year (derived from season_start_date / season_end_date)
    4. venue_name
    5. day_of_week
    6. source_comp_level
    7. gender_eligibility
    8. num_weeks
    9. players_per_side

    Args:
        league: League dict

    Returns:
        Percentage (0-100) of identity fields present
    """
    from src.utils.league_id_generator import IDENTIFYING_FIELDS, extract_season_year

    # Derive season_year from dates so it counts toward completeness
    if not league.get("season_year"):
        sy = extract_season_year(league)
        if sy:
            league["season_year"] = sy

    filled = sum(
        1 for f in IDENTIFYING_FIELDS
        if league.get(f) is not None and league.get(f) != ""
    )
    return (filled / len(IDENTIFYING_FIELDS)) * 100


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
