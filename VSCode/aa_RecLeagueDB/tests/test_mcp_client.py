"""Tests for MCP client utilities."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_get_playwright_server_params_returns_npx_command():
    """Server params should use npx to start @playwright/mcp."""
    from src.scraper.mcp_client import get_playwright_server_params
    params = get_playwright_server_params(headless=True)
    assert params.command == "npx"
    assert "@playwright/mcp" in " ".join(params.args)


def test_get_playwright_server_params_headless_flag():
    """headless=True should include --headless in args."""
    from src.scraper.mcp_client import get_playwright_server_params
    params = get_playwright_server_params(headless=True)
    assert "--headless" in params.args


def test_get_playwright_server_params_no_headless_flag():
    """headless=False should not include --headless in args."""
    from src.scraper.mcp_client import get_playwright_server_params
    params = get_playwright_server_params(headless=False)
    assert "--headless" not in params.args


def test_mcp_tools_to_anthropic_format():
    """Should convert MCP tool definitions to Anthropic tool format."""
    from src.scraper.mcp_client import mcp_tools_to_anthropic_format

    mock_tool = MagicMock()
    mock_tool.name = "browser_navigate"
    mock_tool.description = "Navigate to a URL"
    mock_tool.inputSchema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    }

    result = mcp_tools_to_anthropic_format([mock_tool])

    assert len(result) == 1
    assert result[0]["name"] == "browser_navigate"
    assert result[0]["description"] == "Navigate to a URL"
    assert result[0]["input_schema"]["type"] == "object"
