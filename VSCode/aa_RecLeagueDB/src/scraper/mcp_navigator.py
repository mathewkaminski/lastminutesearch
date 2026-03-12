"""Claude agent navigator using Playwright MCP browser tools."""

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MAX_PAGES = 25
MAX_AGENT_TURNS = 40  # Safety cap on agent loop iterations

# Keyword scoring config — single source of truth for navigation priority.
# Used by _build_navigation_system_prompt() to embed scoring rubric in agent prompt.
NAVIGATION_KEYWORDS: dict[str, list[str]] = {
    # HIGH_PRIORITY (100 pts) — Always navigate these.
    # These pages contain structured league data: fees, dates, format, capacity.
    "high_priority": [
        # League discovery / detail pages
        "details", "more info", "view league", "league info", "league details",
        "upcoming leagues", "upcoming", "seasons", "all leagues", "programs",
        # Registration
        "register", "registration", "signup", "sign up", "join", "enroll",
        # Pricing / fees
        "schedule", "standings", "results", "pricing", "fees", "cost",
        "prices", "rates", "fee",
    ],
    # MEDIUM_PRIORITY (50 pts) — Navigate if page cap allows.
    "medium_priority": [
        "rules", "format", "teams", "divisions", "division", "competition",
        "bracket", "playoffs", "roster", "scores", "ranking", "leaderboard",
        "games", "calendar", "fixtures", "times", "program", "leagues",
        "league", "sport", "sports",
    ],
    # LOW_PRIORITY (25 pts) — Only if nothing higher-priority remains.
    "low_priority": [
        "about", "news", "facility", "venues", "location", "map",
    ],
    # EXCLUDE (0 pts) — Never navigate. Skip regardless of any other context.
    "exclude": [
        # Social media
        "facebook", "instagram", "twitter", "tiktok", "youtube", "linkedin",
        "reddit", "pinterest", "snapchat",
        # Auth / account flow
        "login", "logout", "sign in", "signin", "account", "admin",
        "dashboard", "profile", "checkout", "cart", "my account",
        # Legal / boilerplate
        "privacy", "terms", "legal", "cookie", "cookies", "gdpr",
        "copyright", "disclaimer",
        # Dead-end pages
        "contact", "careers", "jobs", "sitemap", "accessibility",
    ],
    # LEAGUE_CARD_INDICATORS — patterns that identify a league entry on a listing page.
    # When a page row/card contains several of these, it is a league entry.
    # Always click any Details/More Info button associated with it.
    "league_card_indicators": [
        # Days of week
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        # Sports
        "volleyball", "soccer", "football", "basketball", "softball", "baseball",
        "hockey", "lacrosse", "tennis", "badminton", "pickleball", "dodgeball",
        "ultimate", "frisbee", "flag football",
        # Gender / format
        "co-ed", "coed", "men's", "women's", "mixed", "open",
        # Surface / environment
        "indoor", "outdoor", "beach", "grass", "turf", "court",
        # Team format
        "6 v 6", "6v6", "4 v 4", "4v4", "5 v 5", "5v5", "7 v 7", "7v7",
        "8 v 8", "8v8",
        # Season
        "spring", "summer", "fall", "autumn", "winter",
    ],
}

def _build_navigation_system_prompt() -> str:
    """Build the navigation system prompt with NAVIGATION_KEYWORDS embedded.

    Renders the keyword scoring rubric and league card indicators into the
    agent's natural-language instructions so the prompt always reflects
    the current NAVIGATION_KEYWORDS config.

    Returns:
        Formatted system prompt string
    """
    kw = NAVIGATION_KEYWORDS

    def fmt(lst: list[str]) -> str:
        return ", ".join(lst)

    return f"""You are a web scraping agent for an adult recreational sports league database.

Your job: navigate a sports league website and collect accessibility-tree snapshots from pages
that contain league information (schedules, registration, pricing, team details).

---

LINK SCORING RUBRIC — use this to decide which links to follow:

  HIGH PRIORITY (100 pts) — Always navigate these first:
    {fmt(kw["high_priority"])}

  MEDIUM PRIORITY (50 pts) — Navigate if page cap allows:
    {fmt(kw["medium_priority"])}

  LOW PRIORITY (25 pts) — Only if nothing higher-priority remains:
    {fmt(kw["low_priority"])}

  EXCLUDE (0 pts) — Never navigate under any circumstances:
    {fmt(kw["exclude"])}

Navigate pages in score order (100 → 50 → 25). Skip all EXCLUDE links entirely.

---

LEAGUE CARD DETECTION — run this check on EVERY page snapshot:

Look for rows, cards, table rows, or grid entries that contain league indicators such as:
  {fmt(kw["league_card_indicators"])}

If you see a league listing (a row/card with a day-of-week + sport/format + venue), check
whether it has a "Details", "More Info", "View", or similar button or link. If yes, navigate
to that detail URL immediately. Repeat for EVERY league entry on the page — do not skip any.

Individual league detail pages contain the complete data needed: team fee/price, exact start
and end dates, num_weeks, start times, skill level, and remaining spots.

---

INSTRUCTIONS:
1. Start by taking a snapshot of the current page with browser_snapshot
2. Score all visible links using the rubric above
3. Navigate to HIGH PRIORITY pages first (score = 100)
4. On EVERY page: run the LEAGUE CARD DETECTION check and navigate to ALL detail URLs found
5. AFTER EVERY browser_navigate OR browser_click call, you MUST immediately call
   browser_snapshot before doing anything else — this is mandatory, no exceptions
6. For EACH league detail page visited: look for "Schedule" or "Standings" links associated
   with that league and navigate to them. On those pages, identify and count all unique team
   names listed in the standings table or weekly schedule grid — this is the num_teams value
   for that league. Note it in your done() summary.
7. Continue until all league detail AND their schedule/standings pages are visited, then call done()

DO NOT navigate to EXCLUDE links under any circumstances.

After collecting snapshots from all individual league detail pages and their schedule/standings
pages, call done() with a summary that includes for each league:
- League name / day / venue
- start_time (earliest), time_played_per_week, players_per_side (e.g., 6 for "6v6")
- stat_holidays (any "no games" dates and reasons)
- num_teams (count of unique team names from standings or schedule, or null if not yet available)
"""


NAVIGATION_SYSTEM_PROMPT = _build_navigation_system_prompt()

DONE_TOOL = {
    "name": "done",
    "description": "Signal that navigation is complete and all relevant snapshots have been collected.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Brief summary of pages visited and data found",
            }
        },
        "required": [],
    },
}


def _extract_snapshot_from_result(
    tool_name: str,
    tool_result: str,
    snapshot_store: dict[str, str],
    url_store: list[str],
) -> None:
    """Store snapshot result keyed by current URL path.

    Args:
        tool_name: Name of the tool that was called
        tool_result: Text result from the tool
        snapshot_store: Dict to store snapshots in (mutated in place)
        url_store: List tracking current URL (last item is current)
    """
    if tool_name != "browser_snapshot":
        return

    current_url = url_store[-1] if url_store else "unknown"
    path = urlparse(current_url).path.strip("/").replace("/", "_") or "home"

    # Avoid duplicate keys
    key = path
    counter = 1
    while key in snapshot_store:
        key = f"{path}_{counter}"
        counter += 1

    snapshot_store[key] = tool_result
    logger.info(f"Snapshot collected: {key} ({len(tool_result)} chars) from {current_url}")


def _resolve_snapshot_content(result_text: str) -> str:
    """Resolve full snapshot content when Playwright MCP returns a file link.

    Some @playwright/mcp versions write the accessibility tree to a temp .md
    file and return a stub like:
        ### Snapshot
        - [Snapshot](snapshot_main.md)

    This function detects that pattern and reads the actual file from the
    Windows temp playwright-mcp-output directory.

    Args:
        result_text: Raw text returned by browser_snapshot tool

    Returns:
        Full accessibility tree text, or original result_text if no link found
    """
    match = re.search(r'\[Snapshot\]\(([^)]+)\)', result_text)
    if not match:
        return result_text

    linked_file = Path(match.group(1)).name

    # @playwright/mcp writes snapshot files relative to process.cwd() when no
    # --output-dir or MCP roots are configured. Check multiple candidate paths.
    candidate_dirs = [
        Path.cwd(),                                              # project root (most common)
        Path(tempfile.gettempdir()) / "playwright-mcp-output",  # temp dir fallback
    ]

    for candidate_dir in candidate_dirs:
        snapshot_path = candidate_dir / linked_file
        if snapshot_path.exists():
            try:
                content = snapshot_path.read_text(encoding="utf-8")
                logger.debug(f"Resolved snapshot from file: {snapshot_path} ({len(content)} chars)")
                # Return the header (page URL/title) + the actual tree
                return result_text + "\n" + content
            except Exception as e:
                logger.warning(f"Failed to read snapshot file {snapshot_path}: {e}")

    logger.warning(f"Snapshot file not found: {linked_file} (checked {[str(d) for d in candidate_dirs]})")
    return result_text


async def _call_with_rate_limit_retry(
    client: Any,
    *,
    max_outer_retries: int = 8,
    **kwargs: Any,
) -> Any:
    """Call client.messages.create with outer retry loop for RateLimitError.

    The Anthropic SDK auto-retries up to ~8 times with backoff, but then raises.
    This adds an outer layer that sleeps a full 65 seconds before trying again,
    preventing crashes on sustained 30K-token/min rate-limit pressure.
    """
    for attempt in range(max_outer_retries):
        try:
            return await client.messages.create(**kwargs)
        except Exception as e:
            # Only retry on RateLimitError; let everything else propagate
            if "rate_limit" not in str(e).lower() and "429" not in str(e):
                raise
            if attempt < max_outer_retries - 1:
                wait = 65
                logger.info(
                    f"Rate limit hit (outer retry {attempt + 1}/{max_outer_retries}), "
                    f"waiting {wait}s..."
                )
                await asyncio.sleep(wait)
            else:
                raise


def _trim_message_history(messages: list, keep_turns: int = 5) -> list:
    """Keep initial user message + last `keep_turns` assistant/user pairs.

    Prevents conversation history from growing unboundedly and sending too many
    input tokens per minute (Anthropic limit: 30K tokens/min on new accounts).
    Each trimmed turn reduces the request by ~1-3K tokens.
    """
    # messages[0] = initial user instruction (always keep)
    # messages[1..] = alternating assistant / user-tool-results pairs
    if len(messages) <= keep_turns * 2 + 1:
        return messages
    initial = messages[:1]
    recent = messages[-(keep_turns * 2):]
    logger.debug(
        f"Trimmed history from {len(messages)} → {len(initial) + len(recent)} messages"
    )
    return initial + recent


async def navigate_and_collect(
    url: str,
    mcp_session: Any,
    mcp_tools: list[dict],
    max_pages: int = MAX_PAGES,
) -> dict[str, str]:
    """Run Claude navigation agent and collect accessibility-tree snapshots.

    Args:
        url: Starting URL to navigate from
        mcp_session: Active MCP ClientSession with Playwright tools
        mcp_tools: MCP tools in Anthropic format (from mcp_tools_to_anthropic_format)
        max_pages: Maximum pages to visit (default 25)

    Returns:
        Dict mapping page_key -> accessibility_tree_text
        e.g. {"home": "...", "schedule": "...", "registration": "..."}
    """
    import anthropic

    client = anthropic.AsyncAnthropic()
    all_tools = mcp_tools + [DONE_TOOL]

    snapshots: dict[str, str] = {}
    url_tracker: list[str] = [url]

    messages = [
        {
            "role": "user",
            "content": f"Navigate to {url} and collect snapshots of all pages containing league data. Start now.",
        }
    ]

    for turn in range(MAX_AGENT_TURNS):
        logger.debug(f"Agent turn {turn + 1}/{MAX_AGENT_TURNS}")

        # Keep history compact to stay under 30K input-tokens/min.
        # 5 turns × ~2K tokens/turn + system prompt ≈ 11-12K tokens per request.
        messages = _trim_message_history(messages, keep_turns=5)

        response = await _call_with_rate_limit_retry(
            client,
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=NAVIGATION_SYSTEM_PROMPT,
            tools=all_tools,
            messages=messages,
        )

        # Append assistant response
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            logger.info("Agent stopped (end_turn)")
            break

        # Process tool calls
        tool_results = []
        agent_done = False

        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input or {}

            logger.debug(f"Tool call: {tool_name}({tool_input})")

            # Handle done() — agent signals completion
            if tool_name == "done":
                summary = tool_input.get("summary", "")
                logger.info(f"Agent done: {summary}")
                agent_done = True
                # Capture the agent's summary as a fallback snapshot.
                # If the agent visited pages via browser_click without snapshotting,
                # its done() summary still contains the extracted data.
                if summary and len(summary) > 200:
                    snapshots["agent_summary"] = f"### Agent Navigation Summary\n\n{summary}"
                    logger.info(f"Stored agent summary as fallback snapshot ({len(summary)} chars)")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Navigation complete.",
                })
                break

            # Track URL changes
            if tool_name == "browser_navigate":
                nav_url = tool_input.get("url", url)
                url_tracker.append(nav_url)

            # Execute tool via MCP session
            try:
                mcp_result = await mcp_session.call_tool(tool_name, arguments=tool_input)
                result_text = "\n".join(
                    item.text
                    for item in mcp_result.content
                    if hasattr(item, "text")
                )
                # Resolve file-link snapshots (some @playwright/mcp versions
                # write the accessibility tree to a temp file instead of inline)
                if tool_name == "browser_snapshot":
                    result_text = _resolve_snapshot_content(result_text)
                    # Extract actual page URL from snapshot header so browser_click
                    # navigation (which doesn't trigger the browser_navigate tracker)
                    # still gets the correct URL key for snapshot storage.
                    page_url_match = re.search(r'- Page URL: (.+?)(?:\n|$)', result_text)
                    if page_url_match:
                        actual_url = page_url_match.group(1).strip()
                        if actual_url != url_tracker[-1]:
                            url_tracker.append(actual_url)
                            logger.debug(f"URL updated from snapshot header: {actual_url}")
            except Exception as e:
                result_text = f"Error: {e}"
                logger.warning(f"Tool {tool_name} failed: {e}")

            # Collect snapshot if applicable
            _extract_snapshot_from_result(
                tool_name=tool_name,
                tool_result=result_text,
                snapshot_store=snapshots,
                url_store=url_tracker,
            )

            # Enforce page cap
            if len(snapshots) >= max_pages:
                logger.info(f"Page cap reached ({max_pages}), stopping navigation")
                agent_done = True

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text[:3000],  # Truncate: keep history small for token/min budget
            })

        # Append tool results
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        if agent_done:
            break

        # Proactive pacing: 30K tokens/min ÷ ~6K tokens/turn ≈ 5 safe turns/min.
        # Sleep 10s per turn so we never burst above ~6 calls/min.
        await asyncio.sleep(10)

    logger.info(f"Navigation complete: {len(snapshots)} snapshots collected")
    return snapshots
