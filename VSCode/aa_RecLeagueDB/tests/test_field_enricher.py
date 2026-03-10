"""Tests for FieldEnricher."""
import json
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


# ── _extract ──────────────────────────────────────────────────────────────────

def test_extract_returns_field_patches(enricher):
    """_extract calls Claude and parses JSON array response."""
    leagues = [_make_league()]
    null_fields = ["venue_name", "team_fee"]
    api_response = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex", "team_fee": 875.0}]

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(api_response))]
    enricher._anthropic.messages.create = MagicMock(return_value=mock_message)

    result = enricher._extract("page content", null_fields, leagues)
    assert len(result) == 1
    assert result[0]["venue_name"] == "Nepean Sportsplex"
    assert result[0]["team_fee"] == 875.0


def test_extract_strips_null_values(enricher):
    """_extract removes null values from patches."""
    leagues = [_make_league()]
    null_fields = ["venue_name", "team_fee"]
    api_response = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex", "team_fee": None}]

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(api_response))]
    enricher._anthropic.messages.create = MagicMock(return_value=mock_message)

    result = enricher._extract("content", null_fields, leagues)
    assert "team_fee" not in result[0]
    assert result[0].get("venue_name") == "Nepean Sportsplex"


def test_extract_handles_invalid_json(enricher):
    """_extract returns empty list on parse error (does not raise)."""
    leagues = [_make_league()]
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="not json at all")]
    enricher._anthropic.messages.create = MagicMock(return_value=mock_message)

    result = enricher._extract("content", ["venue_name"], leagues)
    assert result == []


def test_write_back_updates_patched_fields(enricher):
    """_write_back calls Supabase update with patch + recalculated quality_score."""
    # Mock DB fetch of current record
    current_league = _make_league(league_id="uuid-1")
    enricher._db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [current_league]
    enricher._db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    enricher._write_back("uuid-1", {"venue_name": "Nepean Sportsplex", "team_fee": 875.0})

    update_call = enricher._db.table.return_value.update
    update_call.assert_called_once()
    updated_data = update_call.call_args[0][0]
    assert updated_data["venue_name"] == "Nepean Sportsplex"
    assert updated_data["team_fee"] == 875.0
    assert "quality_score" in updated_data
    assert "updated_at" in updated_data
