"""Tests for src/database/writer.py — _prepare_for_insert enrichment."""

from unittest.mock import patch, MagicMock
from src.database.writer import _prepare_for_insert


def test_prepare_for_insert_sets_base_domain():
    data = {
        "organization_name": "Javelin",
        "url_scraped": "https://www.javelin.com/calgary/vball",
        "sport_season_code": "V10",
        "identifying_fields_pct": 75,
    }
    result = _prepare_for_insert(data)
    assert result["base_domain"] == "javelin.com"


def test_prepare_for_insert_sets_listing_type_league():
    data = {
        "organization_name": "TSSC",
        "url_scraped": "https://torontossc.com",
        "sport_season_code": "S10",
        "num_weeks": 10,
        "identifying_fields_pct": 75,
    }
    result = _prepare_for_insert(data)
    assert result["listing_type"] == "league"


def test_prepare_for_insert_sets_listing_type_dropin():
    data = {
        "organization_name": "ZogSports",
        "url_scraped": "https://zogsports.com",
        "sport_season_code": "S10",
        "league_name": "Friday Drop-In",
        "identifying_fields_pct": 75,
    }
    result = _prepare_for_insert(data)
    assert result["listing_type"] == "drop_in"


def test_prepare_for_insert_unknown_listing_type():
    data = {
        "organization_name": "Mystery Org",
        "url_scraped": "https://example.com",
        "sport_season_code": "S10",
        "identifying_fields_pct": 75,
    }
    result = _prepare_for_insert(data)
    assert result["listing_type"] == "unknown"
