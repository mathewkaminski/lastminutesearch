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
