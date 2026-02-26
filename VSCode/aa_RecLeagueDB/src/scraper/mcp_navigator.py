"""Claude agent navigator using Playwright MCP browser tools."""

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MAX_PAGES = 5
MAX_AGENT_TURNS = 20  # Safety cap on agent loop iterations

NAVIGATION_SYSTEM_PROMPT = """You are a web scraping agent for an adult recreational sports league database.

Your job: navigate a sports league website and collect accessibility-tree snapshots from pages
that contain league information (schedules, registration, pricing, team details).

INSTRUCTIONS:
1. Start by taking a snapshot of the current page with browser_snapshot
2. Look for links to: registration, schedule, standings, pricing, specific league pages
3. Navigate to relevant sub-pages and take snapshots (up to 4 sub-pages, 5 total)
4. AFTER EVERY browser_navigate call, you MUST immediately call browser_snapshot before moving to the next navigation
5. When you have collected enough data, call done()

PRIORITIZE navigating to:
- Registration or signup pages
- Schedule or calendar pages
- Specific league detail pages
- Standings or team count pages

DO NOT navigate to:
- Social media links (facebook, instagram, twitter)
- Login or account pages
- Contact or about pages
- External websites

After collecting snapshots from all relevant pages, call done() with a summary.
"""

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
        max_pages: Maximum pages to visit (default 5)

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

        response = await client.messages.create(
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
                "content": result_text[:8000],  # Truncate long snapshots in history
            })

        # Append tool results
        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        if agent_done:
            break

    logger.info(f"Navigation complete: {len(snapshots)} snapshots collected")
    return snapshots
