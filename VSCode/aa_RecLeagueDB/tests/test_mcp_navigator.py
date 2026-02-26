"""Tests for the MCP navigation agent."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_done_tool_definition():
    """done tool should have correct schema."""
    from src.scraper.mcp_navigator import DONE_TOOL
    assert DONE_TOOL["name"] == "done"
    assert "input_schema" in DONE_TOOL
    assert DONE_TOOL["input_schema"]["type"] == "object"


def test_system_prompt_mentions_league_priorities():
    """System prompt should instruct agent to prioritize league-relevant pages."""
    from src.scraper.mcp_navigator import NAVIGATION_SYSTEM_PROMPT
    prompt_lower = NAVIGATION_SYSTEM_PROMPT.lower()
    assert "registration" in prompt_lower
    assert "schedule" in prompt_lower
    assert "done" in prompt_lower


def test_extract_snapshots_from_tool_calls_empty():
    """Should return empty dict when no browser_snapshot calls present."""
    from src.scraper.mcp_navigator import _extract_snapshot_from_result

    snapshot_store = {}
    url_store = ["https://example.com"]
    _extract_snapshot_from_result(
        tool_name="browser_navigate",
        tool_result="ok",
        snapshot_store=snapshot_store,
        url_store=url_store,
    )
    assert snapshot_store == {}


def test_extract_snapshots_from_tool_calls_snapshot():
    """Should store snapshot when tool_name is browser_snapshot."""
    from src.scraper.mcp_navigator import _extract_snapshot_from_result

    snapshot_store = {}
    url_store = ["https://example.com/schedule"]
    _extract_snapshot_from_result(
        tool_name="browser_snapshot",
        tool_result="- heading: League Schedule",
        snapshot_store=snapshot_store,
        url_store=url_store,
    )
    assert len(snapshot_store) == 1
    assert "- heading: League Schedule" in list(snapshot_store.values())[0]
