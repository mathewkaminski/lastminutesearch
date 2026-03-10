"""Tests for FieldEnricher."""
import pytest
from unittest.mock import MagicMock, patch
from src.enrichers.field_enricher import FieldEnricher, FieldEnrichResult, ENRICHABLE_FIELDS


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def enricher():
    return FieldEnricher(supabase_client=MagicMock(), anthropic_api_key="test-key")


def _make_league(**overrides) -> dict:
    """Return a minimal league dict. All enrichable fields null by default."""
    base = {
        "league_id": "uuid-1",
        "organization_name": "Ottawa Volley Sixes",
        "url_scraped": "https://ottawavolleysixes.com/register",
        "sport_season_code": "411",
    }
    # All enrichable fields null
    for f in ENRICHABLE_FIELDS:
        base[f] = None
    base.update(overrides)
    return base


# ── _get_null_fields ──────────────────────────────────────────────────────────

def test_get_null_fields_all_null(enricher):
    """Returns all ENRICHABLE_FIELDS when all are null."""
    league = _make_league()
    result = enricher._get_null_fields(league)
    assert set(result) == set(ENRICHABLE_FIELDS)


def test_get_null_fields_excludes_populated(enricher):
    """Excludes fields that already have values."""
    league = _make_league(venue_name="Nepean Sportsplex", team_fee=875.0)
    result = enricher._get_null_fields(league)
    assert "venue_name" not in result
    assert "team_fee" not in result
    # Others still returned
    assert "day_of_week" in result


def test_get_null_fields_excludes_num_teams(enricher):
    """num_teams is never in the enrichable list."""
    league = _make_league(num_teams=None)
    result = enricher._get_null_fields(league)
    assert "num_teams" not in result


def test_get_null_fields_all_populated(enricher):
    """Returns empty list when all enrichable fields have values."""
    league = _make_league(**{f: "x" for f in ENRICHABLE_FIELDS})
    assert enricher._get_null_fields(league) == []


# ── _build_prompt ─────────────────────────────────────────────────────────────

def test_build_prompt_contains_null_fields(enricher):
    """Prompt includes all requested null fields."""
    leagues = [_make_league()]
    null_fields = ["venue_name", "team_fee", "day_of_week"]
    prompt = enricher._build_prompt("some page content", null_fields, leagues)
    for f in null_fields:
        assert f in prompt


def test_build_prompt_excludes_populated_fields(enricher):
    """Prompt schema does not mention fields not in null_fields."""
    leagues = [_make_league(venue_name="Nepean Sportsplex")]
    null_fields = ["team_fee", "day_of_week"]  # venue_name NOT in null_fields
    prompt = enricher._build_prompt("some content", null_fields, leagues)
    assert "team_fee" in prompt
    assert "day_of_week" in prompt
    # venue_name should not appear in the schema section
    # (split on OUTPUT SCHEMA to check only schema part)
    schema_part = prompt.split("OUTPUT SCHEMA")[1] if "OUTPUT SCHEMA" in prompt else prompt
    assert "venue_name" not in schema_part


def test_build_prompt_includes_league_context(enricher):
    """Prompt includes org name in the context section."""
    leagues = [_make_league(organization_name="Ottawa Volley Sixes", day_of_week="Monday")]
    null_fields = ["venue_name", "team_fee"]
    prompt = enricher._build_prompt("content", null_fields, leagues)
    assert "Ottawa Volley Sixes" in prompt


def test_build_prompt_includes_content(enricher):
    """Prompt includes the page content."""
    leagues = [_make_league()]
    prompt = enricher._build_prompt("UNIQUE_MARKER_XYZ", ["venue_name"], leagues)
    assert "UNIQUE_MARKER_XYZ" in prompt
