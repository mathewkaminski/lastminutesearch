import pytest
from unittest.mock import MagicMock, patch


# ── _merge_league_records ──────────────────────────────────────────────────

def test_merge_fills_null_from_supplement():
    """Null fields in the base record are filled from the supplement."""
    from src.database.writer import _merge_league_records

    existing = {
        "league_id": "old-id",
        "organization_name": "TSSC",
        "sport_season_code": "201",
        "url_scraped": "https://x.com",
        "quality_score": 40,
        "venue_name": "Civic",
        "day_of_week": None,    # missing in existing
    }
    new_rec = {
        "organization_name": "TSSC",
        "sport_season_code": "201",
        "url_scraped": "https://x.com",
        "quality_score": 30,
        "venue_name": None,     # missing in new
        "day_of_week": "Monday",
    }
    result = _merge_league_records(existing, new_rec)
    assert result["venue_name"] == "Civic"    # from existing (base — higher quality)
    assert result["day_of_week"] == "Monday"  # filled from new (supplement)
    assert result["league_id"] == "old-id"    # always preserved


def test_merge_prefers_higher_quality_as_base():
    """When new record has higher quality_score, it becomes the base."""
    from src.database.writer import _merge_league_records

    existing = {
        "league_id": "old-id",
        "quality_score": 30,
        "venue_name": "Civic",
        "day_of_week": None,
        "organization_name": "TSSC",
        "sport_season_code": "201",
        "url_scraped": "https://x.com",
    }
    new_rec = {
        "quality_score": 70,  # higher — becomes base
        "venue_name": None,
        "day_of_week": "Monday",
        "organization_name": "TSSC",
        "sport_season_code": "201",
        "url_scraped": "https://x.com",
    }
    result = _merge_league_records(existing, new_rec)
    assert result["day_of_week"] == "Monday"  # from new (base)
    assert result["venue_name"] == "Civic"    # filled from existing (supplement)


def test_merge_preserves_existing_league_id_always():
    """league_id is never overwritten regardless of quality."""
    from src.database.writer import _merge_league_records

    existing = {"league_id": "old-id", "quality_score": 10,
                "organization_name": "X", "sport_season_code": "201", "url_scraped": "h"}
    new_rec  = {"league_id": "new-id", "quality_score": 90,
                "organization_name": "X", "sport_season_code": "201", "url_scraped": "h"}
    result = _merge_league_records(existing, new_rec)
    assert result["league_id"] == "old-id"


# ── insert_league integration ──────────────────────────────────────────────

_BASE_LEAGUE = {
    "organization_name": "Test Org",
    "sport_season_code": "201",
    "url_scraped": "https://example.com",
    "identifying_fields_pct": 60,
}


def test_insert_league_merges_when_duplicate_found():
    """When duplicate found, insert_league always calls update — even if new quality is lower."""
    from src.database.writer import insert_league

    existing_full = {
        "league_id": "existing-id",
        **_BASE_LEAGUE,
        "quality_score": 80,
        "day_of_week": None,
        "venue_name": "Civic",
    }
    new_data = {**_BASE_LEAGUE, "quality_score": 30, "day_of_week": "Monday", "venue_name": None}

    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [existing_full]
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{"league_id": "existing-id"}]

    with (
        patch("src.database.writer.validate_extracted_data", return_value=(True, {})),
        patch("src.database.writer.check_duplicate_league", return_value="existing-id"),
    ):
        league_id, is_new = insert_league(new_data, supabase_client=mock_client)

    assert league_id == "existing-id"
    assert is_new is False
    mock_client.table.return_value.update.assert_called()  # update was called (not skipped)


def test_insert_league_skips_low_quality_new_record():
    """New records with identifying_fields_pct below threshold are not inserted."""
    from src.database.writer import insert_league

    new_data = {**_BASE_LEAGUE, "identifying_fields_pct": 20}  # below threshold

    mock_client = MagicMock()
    with (
        patch("src.database.writer.validate_extracted_data", return_value=(True, {})),
        patch("src.database.writer.check_duplicate_league", return_value=None),
    ):
        league_id, is_new = insert_league(new_data, supabase_client=mock_client)

    assert league_id is None
    assert is_new is False
    mock_client.table.return_value.insert.assert_not_called()
