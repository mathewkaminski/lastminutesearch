"""MCP client utilities for connecting to the Playwright MCP server."""

import logging
from typing import Any

from mcp import StdioServerParameters

logger = logging.getLogger(__name__)


def get_playwright_server_params(headless: bool = True) -> StdioServerParameters:
    """Return StdioServerParameters to launch the Playwright MCP server.

    Args:
        headless: Run browser in headless mode (default True)

    Returns:
        StdioServerParameters configured for npx @playwright/mcp
    """
    args = ["@playwright/mcp@latest"]
    if headless:
        args.append("--headless")

    return StdioServerParameters(
        command="npx",
        args=args,
    )


def mcp_tools_to_anthropic_format(mcp_tools: list) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic tool format.

    Args:
        mcp_tools: List of MCP Tool objects from session.list_tools()

    Returns:
        List of dicts in Anthropic tool format:
        [{"name": str, "description": str, "input_schema": dict}, ...]
    """
    anthropic_tools = []
    for tool in mcp_tools:
        anthropic_tools.append({
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {
                "type": "object",
                "properties": {},
            },
        })
    return anthropic_tools
