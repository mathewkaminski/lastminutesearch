"""Tests for the MCP agent scraper CLI."""
import pytest
from unittest.mock import patch, MagicMock
import sys


def test_parse_args_url_required(capsys):
    """--url is required, script should exit without it."""
    with pytest.raises(SystemExit):
        from scripts.mcp_agent_scraper import parse_args
        parse_args([])


def test_parse_args_defaults():
    """Default flags: dry_run=False, force_refresh=False, log_level=INFO."""
    from scripts.mcp_agent_scraper import parse_args
    args = parse_args(["--url", "https://example.com"])
    assert args.url == "https://example.com"
    assert args.dry_run is False
    assert args.force_refresh is False
    assert args.log_level == "INFO"


def test_parse_args_dry_run():
    """--dry-run flag sets dry_run=True."""
    from scripts.mcp_agent_scraper import parse_args
    args = parse_args(["--url", "https://example.com", "--dry-run"])
    assert args.dry_run is True


def test_parse_args_max_pages_default():
    """--max-pages defaults to 25."""
    from scripts.mcp_agent_scraper import parse_args
    args = parse_args(["--url", "https://example.com"])
    assert args.max_pages == 25


def test_parse_args_max_pages_custom():
    """--max-pages accepts a custom integer."""
    from scripts.mcp_agent_scraper import parse_args
    args = parse_args(["--url", "https://example.com", "--max-pages", "10"])
    assert args.max_pages == 10


def test_cache_key_is_deterministic():
    """Same URL and page_key should produce same cache filename structure."""
    from scripts.mcp_agent_scraper import get_cache_path
    path1 = get_cache_path("https://example.com", "home")
    path2 = get_cache_path("https://example.com", "home")
    # Same domain → same parent directory
    assert path1.parent == path2.parent
    assert "home" in path1.name


def test_cache_path_uses_domain():
    """Cache path should include domain as directory."""
    from scripts.mcp_agent_scraper import get_cache_path
    path = get_cache_path("https://ottawavolleysixes.com/home", "home")
    assert "ottawavolleysixes.com" in str(path)


def test_parse_args_max_pages_rejects_zero(capsys):
    """--max-pages 0 should cause a parse error."""
    with pytest.raises(SystemExit):
        from scripts.mcp_agent_scraper import parse_args
        parse_args(["--url", "https://example.com", "--max-pages", "0"])
