#!/usr/bin/env python
"""Navigate standings/schedule pages and update num_teams for leagues in the DB.

Finds team counts from standings (current or historical) and writes num_teams
back to leagues_metadata. Useful when the main scraper didn't capture team
counts (e.g., registration not yet open, or standings on a separate page).

Usage:
    python scripts/count_teams_scraper.py --url https://www.ottawavolleysixes.com
    python scripts/count_teams_scraper.py --org-name "Ottawa Volley Sixes"
    python scripts/count_teams_scraper.py --url https://... --dry-run
    python scripts/count_teams_scraper.py --url https://... --log-level DEBUG
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

LOG_DIR = Path(__file__).parent.parent / "logs"

TEAM_COUNT_SYSTEM_PROMPT = """\
You are a team counter for a sports league database.

Your job: navigate to standings or schedule pages for a list of target leagues,
count the UNIQUE team names visible, and report back.

---

TARGET LEAGUES (find standings/schedule for each of these):
{league_list}

---

STRATEGY:
1. Take a snapshot of the current page with browser_snapshot
2. Look for navigation links labelled "Standings", "Schedule", "Teams", "Divisions", or a
   league-history / past-seasons section
3. For each target league: match by day-of-week + venue + gender, then navigate to that
   league's standings or schedule page
4. Count ALL unique team names visible. If the page shows multiple divisions, add them all.
5. If the current season has no data yet (registration ongoing), look for PREVIOUS season
   standings (e.g., a "2025" or "Fall 2025" archive). Historical data is fine as an estimate.
6. AFTER EVERY browser_navigate or browser_click, call browser_snapshot immediately.
7. Once you have counts for all leagues (or have confirmed none are available), call done().

---

DONE SUMMARY FORMAT — include one line per target league:
  <Day> | <Venue short name> | <Gender>: <N> teams (from <season label>)
  or
  <Day> | <Venue short name> | <Gender>: null (no standings found)

Do NOT navigate to social media, login, privacy, contact, or careers pages.
"""

DONE_TOOL = {
    "name": "done",
    "description": "Signal that team counting is complete.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One line per league: day|venue|gender: N teams (season) or null",
            }
        },
        "required": [],
    },
}

MAX_AGENT_TURNS = 60


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count teams from standings pages and update num_teams in DB"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Base URL of the sports org site to scrape")
    group.add_argument("--org-name", help="Organization name to look up in DB")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing to DB")
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def setup_logging(log_level: str) -> None:
    from datetime import datetime
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"count_teams_{ts}.log"
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger(__name__).info(f"Logging to {log_file}")


def fetch_leagues(url: str | None, org_name: str | None) -> list[dict]:
    """Load target leagues from DB filtered by URL domain or org name."""
    from src.database.supabase_client import get_client
    client = get_client()

    query = client.table("leagues_metadata").select(
        "league_id, organization_name, url_scraped, day_of_week, venue_name, "
        "gender_eligibility, num_weeks, num_teams, sport_season_code"
    ).eq("is_archived", False)

    if org_name:
        query = query.ilike("organization_name", f"%{org_name}%")
    elif url:
        domain = urlparse(url).netloc
        query = query.ilike("url_scraped", f"%{domain}%")

    result = query.execute()
    return result.data or []


def _build_league_list(leagues: list[dict]) -> str:
    lines = []
    for lg in leagues:
        day = lg.get("day_of_week") or "?"
        venue = (lg.get("venue_name") or "?")[:35]
        gender = lg.get("gender_eligibility") or "?"
        weeks = lg.get("num_weeks") or "?"
        current = lg.get("num_teams")
        note = f" [currently null]" if current is None else f" [currently {current}]"
        lines.append(f"  - {day} | {venue} | {gender} | {weeks} weeks{note}")
    return "\n".join(lines)


async def _call_with_rate_limit_retry(client, *, max_outer_retries: int = 8, **kwargs):
    """Call client.messages.create with manual outer retry for RateLimitError.

    The Anthropic SDK retries automatically, but gives up after ~8 attempts.
    This wraps it with an additional outer loop that waits a full minute before
    trying again, preventing crashes on sustained rate-limit pressure.
    """
    import anthropic
    import asyncio

    for attempt in range(max_outer_retries):
        try:
            return await client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            if attempt < max_outer_retries - 1:
                wait = 65
                logging.getLogger(__name__).info(
                    f"Rate limit hit (outer retry {attempt + 1}/{max_outer_retries}), "
                    f"waiting {wait}s..."
                )
                await asyncio.sleep(wait)
            else:
                raise


def _trim_history(messages: list, keep_turns: int = 5) -> list:
    """Keep initial user message + last `keep_turns` assistant/user pairs.

    Prevents conversation history from growing indefinitely and blowing the
    30K tokens/min rate limit.

    Always starts `recent` on an assistant message so we never have a leading
    user-with-tool-results block whose tool_use_ids were trimmed out (which
    causes a 400 Bad Request from the Anthropic API).
    """
    if len(messages) <= keep_turns * 2 + 1:
        return messages
    initial = messages[:1]
    recent = messages[-(keep_turns * 2):]
    # Drop a leading user message — its tool_use_ids would reference an
    # assistant message that was trimmed, triggering a 400 from the API.
    if recent and recent[0].get("role") != "assistant":
        recent = recent[1:]
    return initial + recent


async def _run_agent(start_url: str, leagues: list[dict]) -> str:
    """Run MCP navigation agent and return done() summary text."""
    import anthropic
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from src.scraper.mcp_client import get_playwright_server_params, mcp_tools_to_anthropic_format

    logger = logging.getLogger(__name__)

    league_list = _build_league_list(leagues)
    system_prompt = TEAM_COUNT_SYSTEM_PROMPT.format(league_list=league_list)

    server_params = get_playwright_server_params(headless=True)
    ant_client = anthropic.AsyncAnthropic()

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            mcp_tools = mcp_tools_to_anthropic_format(tools_response.tools)
            all_tools = mcp_tools + [DONE_TOOL]

            messages = [{
                "role": "user",
                "content": (
                    f"Navigate to {start_url} and count teams in standings/schedule "
                    f"for the target leagues listed. Start now."
                ),
            }]

            summary = ""
            for turn in range(MAX_AGENT_TURNS):
                logger.info(f"Agent turn {turn + 1}/{MAX_AGENT_TURNS}")
                # Trim history: keep initial message + last 5 turns.
                # 5 turns gives enough context to remember prior pages without blowing the budget.
                messages = _trim_history(messages, keep_turns=5)
                response = await _call_with_rate_limit_retry(
                    ant_client,
                    model="claude-sonnet-4-6",
                    max_tokens=4096,
                    system=system_prompt,
                    tools=all_tools,
                    messages=messages,
                )
                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason == "end_turn":
                    logger.info("Agent stopped (end_turn)")
                    break

                tool_results = []
                agent_done = False

                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    tool_name = block.name
                    tool_input = block.input or {}
                    if tool_name == "browser_navigate":
                        logger.info(f"  Tool: browser_navigate → {tool_input.get('url', '?')}")
                    else:
                        logger.info(f"  Tool: {tool_name}({list(tool_input.keys())})")

                    if tool_name == "done":
                        summary = tool_input.get("summary", "")
                        logger.info(f"Agent done. Summary:\n{summary}")
                        agent_done = True
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Team counting complete.",
                        })
                        break

                    try:
                        mcp_result = await session.call_tool(tool_name, arguments=tool_input)
                        result_text = "\n".join(
                            item.text for item in mcp_result.content if hasattr(item, "text")
                        )
                    except Exception as e:
                        result_text = f"Error: {e}"
                        logger.warning(f"Tool {tool_name} failed: {e}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text[:2000],  # Truncate to stay under 30K tokens/min
                    })

                # On the second-to-last turn, force the agent to call done().
                # Inject the prompt into the current tool_results content so we
                # never create two consecutive user messages (which the API rejects).
                if turn == MAX_AGENT_TURNS - 2:
                    forced_text = (
                        "You are almost out of turns. Call done() NOW with whatever team "
                        "counts you have found so far. Use null for any leagues you could "
                        "not find. Do not navigate any more pages."
                    )
                    if tool_results:
                        # Embed as a text block alongside the tool_result blocks
                        tool_results.append({"type": "text", "text": forced_text})
                    else:
                        # No tool calls this turn — safe to add a standalone message
                        messages.append({"role": "user", "content": forced_text})
                    logger.info("Sending final-turn prompt to force done() call")

                if tool_results:
                    messages.append({"role": "user", "content": tool_results})
                if agent_done:
                    break

                # Proactive pacing: 30K tokens/min limit ÷ ~6K tokens/turn ≈ 5 safe turns/min.
                # Sleep 12s between turns to stay well clear of the limit.
                await asyncio.sleep(12)

    return summary


def _extract_counts_from_summary(summary: str, leagues: list[dict]) -> list[dict]:
    """Use GPT-4o to parse team counts from agent summary and match to league_ids."""
    import openai

    if not summary.strip():
        return []

    # Build matching context — include full UUID so GPT-4o returns the real league_id
    league_context = "\n".join(
        f"  league_id={lg['league_id']} | {lg.get('day_of_week')} | "
        f"{(lg.get('venue_name') or '')[:30]} | {lg.get('gender_eligibility')}"
        for lg in leagues
    )

    prompt = f"""Parse team count results from this agent summary and match each to a league_id.

AGENT SUMMARY:
{summary}

AVAILABLE LEAGUES (match by day-of-week + venue fragment + gender):
{league_context}

Return ONLY valid JSON — an array of objects. Use null for num_teams if not found.
[
  {{"league_id": "full-uuid-here", "num_teams": 12, "source": "2025 standings"}},
  {{"league_id": "full-uuid-here", "num_teams": null, "source": "no standings found"}}
]
Include an entry for every league in the list above. Output only the JSON array."""

    oai = openai.OpenAI()
    resp = oai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    text = resp.choices[0].message.content.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


async def run(url: str | None, org_name: str | None, dry_run: bool) -> dict:
    logger = logging.getLogger(__name__)
    result = {"leagues_found": 0, "updated": 0, "errors": []}

    # Determine start URL
    if url:
        start_url = url
    else:
        # Look up URL from DB
        from src.database.supabase_client import get_client
        client = get_client()
        row = client.table("leagues_metadata").select("url_scraped").ilike(
            "organization_name", f"%{org_name}%"
        ).limit(1).execute()
        if not row.data:
            result["errors"].append(f"No leagues found for org_name={org_name!r}")
            return result
        start_url = row.data[0]["url_scraped"]
        domain = urlparse(start_url).netloc
        start_url = f"https://{domain}"

    leagues = fetch_leagues(url, org_name)
    if not leagues:
        result["errors"].append("No leagues found in DB matching filter")
        return result

    result["leagues_found"] = len(leagues)
    logger.info(f"Found {len(leagues)} league(s) in DB to check:")
    for lg in leagues:
        logger.info(
            f"  {lg.get('day_of_week')} | {lg.get('venue_name')} | "
            f"{lg.get('gender_eligibility')} | num_teams={lg.get('num_teams')}"
        )

    # Run agent
    logger.info(f"Starting team-count agent at {start_url} ...")
    summary = await _run_agent(start_url, leagues)

    if not summary:
        result["errors"].append("Agent returned empty summary")
        return result

    # Extract counts
    logger.info("Extracting team counts from summary with GPT-4o...")
    counts = _extract_counts_from_summary(summary, leagues)

    # Print results
    print(f"\n{'='*60}")
    print("TEAM COUNT RESULTS")
    print(f"{'='*60}")
    for entry in counts:
        lid = entry.get("league_id", "?")
        n = entry.get("num_teams")
        source = entry.get("source", "")
        # Find league name for display
        match = next((lg for lg in leagues if lg["league_id"] == lid), None)
        label = (
            f"{match.get('day_of_week')} | {(match.get('venue_name') or '')[:25]} | "
            f"{match.get('gender_eligibility')}"
            if match else lid[:8]
        )
        print(f"  {label:<50}  num_teams={n}  ({source})")

    if dry_run:
        logger.info("Dry-run — skipping DB updates")
        return result

    # Write to DB
    from src.database.supabase_client import get_client
    client = get_client()
    for entry in counts:
        lid = entry.get("league_id")
        n = entry.get("num_teams")
        if not lid or n is None:
            continue
        try:
            client.table("leagues_metadata").update({"num_teams": int(n)}).eq(
                "league_id", lid
            ).execute()
            logger.info(f"Updated {lid[:8]}... num_teams={n}")
            result["updated"] += 1
        except Exception as e:
            logger.warning(f"Failed to update {lid[:8]}: {e}")
            result["errors"].append(str(e))

    return result


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    logger.info("Starting team-count scraper")
    logger.info(f"  Target:   {args.url or args.org_name}")
    logger.info(f"  Dry-run:  {args.dry_run}")

    result = asyncio.run(run(args.url, args.org_name, args.dry_run))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Leagues found in DB:  {result['leagues_found']}")
    print(f"Records updated:      {result['updated']}")
    if result["errors"]:
        for err in result["errors"]:
            print(f"  ERROR: {err}")

    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
