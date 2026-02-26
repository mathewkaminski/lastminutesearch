"""Tests for the MCP navigation agent."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_done_tool_definition():
    """done tool should have correct schema."""
    from src.scraper.mcp_navigator import DONE_TOOL
    assert DONE_TOOL["name"] == "done"
    assert "input_schema" in DONE_TOOL
    assert DONE_TOOL["input_schema"]["type"] == "object"


def test_max_pages_default_is_25():
    """MAX_PAGES default should be 25 to support sites with many individual league pages."""
    from src.scraper.mcp_navigator import MAX_PAGES
    assert MAX_PAGES == 25


def test_system_prompt_mentions_league_priorities():
    """System prompt must contain link scoring rubric and league card detection."""
    from src.scraper.mcp_navigator import NAVIGATION_SYSTEM_PROMPT
    prompt_lower = NAVIGATION_SYSTEM_PROMPT.lower()

    # Scoring rubric must be present
    assert "high priority" in prompt_lower
    assert "medium priority" in prompt_lower
    assert "exclude" in prompt_lower

    # League card detection section must be present
    assert "league card" in prompt_lower or "league entry" in prompt_lower or "league listing" in prompt_lower

    # Done instruction must be present
    assert "done" in prompt_lower

    # Old hardcoded cap must be gone
    assert "5 total" not in NAVIGATION_SYSTEM_PROMPT
    assert "4 sub-pages" not in NAVIGATION_SYSTEM_PROMPT


def test_system_prompt_embeds_keywords():
    """System prompt must embed key keywords from NAVIGATION_KEYWORDS."""
    from src.scraper.mcp_navigator import NAVIGATION_SYSTEM_PROMPT, NAVIGATION_KEYWORDS
    prompt_lower = NAVIGATION_SYSTEM_PROMPT.lower()

    # Spot-check: a few high-priority keywords must appear in the prompt
    for kw in ["register", "schedule", "details", "fees"]:
        assert kw in prompt_lower, f"Expected '{kw}' in prompt (high_priority)"

    # Spot-check: key exclude terms must appear
    for kw in ["facebook", "login", "privacy"]:
        assert kw in prompt_lower, f"Expected '{kw}' in prompt (exclude)"

    # Spot-check: league card indicators must appear
    for kw in ["monday", "volleyball", "co-ed"]:
        assert kw in prompt_lower, f"Expected '{kw}' in prompt (league_card_indicators)"


def test_build_navigation_system_prompt_is_callable():
    """_build_navigation_system_prompt() must return a non-empty string."""
    from src.scraper.mcp_navigator import _build_navigation_system_prompt
    result = _build_navigation_system_prompt()
    assert isinstance(result, str)
    assert len(result) > 500


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


def test_navigation_keywords_structure():
    """NAVIGATION_KEYWORDS must have all required scoring tiers."""
    from src.scraper.mcp_navigator import NAVIGATION_KEYWORDS
    required_tiers = {"high_priority", "medium_priority", "low_priority", "exclude", "league_card_indicators"}
    assert required_tiers == set(NAVIGATION_KEYWORDS.keys())
    for tier, keywords in NAVIGATION_KEYWORDS.items():
        assert isinstance(keywords, list), f"{tier} must be a list"
        assert len(keywords) > 0, f"{tier} must not be empty"


def test_navigation_keywords_content():
    """Key keywords must appear in correct scoring tiers."""
    from src.scraper.mcp_navigator import NAVIGATION_KEYWORDS
    high = NAVIGATION_KEYWORDS["high_priority"]
    exclude = NAVIGATION_KEYWORDS["exclude"]
    league_indicators = NAVIGATION_KEYWORDS["league_card_indicators"]

    # High-value league data pages
    assert "register" in high
    assert "schedule" in high
    assert "details" in high
    assert "fees" in high

    # Must never navigate to social/auth
    assert "facebook" in exclude
    assert "login" in exclude
    assert "privacy" in exclude

    # Must detect day-of-week + sport patterns as league cards
    assert "monday" in league_indicators
    assert "volleyball" in league_indicators
    assert "co-ed" in league_indicators
