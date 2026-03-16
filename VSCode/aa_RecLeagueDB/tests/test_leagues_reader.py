"""Tests for leagues_reader — the shared DB layer for all league management pages."""
from unittest.mock import patch, MagicMock
import pytest


def _make_mock_client(rows: list[dict]) -> MagicMock:
    """Build a mock Supabase client whose .execute() returns rows."""
    mock_result = MagicMock()
    mock_result.data = rows

    mock_q = MagicMock()
    mock_q.execute.return_value = mock_result
    # All query builder methods return self so chains work
    for method in ("select", "eq", "in_", "ilike", "gte", "lte", "lt", "order", "limit"):
        getattr(mock_q, method).return_value = mock_q

    mock_client = MagicMock()
    mock_client.table.return_value = mock_q
    return mock_client


# ---------------------------------------------------------------------------
# get_leagues
# ---------------------------------------------------------------------------

def test_get_leagues_returns_rows():
    rows = [{"league_id": "abc", "organization_name": "TSSC", "quality_score": 80}]
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client(rows)):
        from src.database.leagues_reader import get_leagues
        result = get_leagues()
    assert result == rows


def test_get_leagues_empty_db():
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client([])):
        from src.database.leagues_reader import get_leagues
        result = get_leagues()
    assert result == []


def test_get_leagues_with_org_search_calls_ilike():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import get_leagues
        get_leagues({"org_search": "tssc"})
    mock_client.table.return_value.ilike.assert_called_once_with("organization_name", "%tssc%")


def test_get_leagues_with_sport_codes_calls_in():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import get_leagues
        get_leagues({"sport_season_codes": ["V10", "S10"]})
    mock_client.table.return_value.in_.assert_called_once_with("sport_season_code", ["V10", "S10"])


def test_get_leagues_empty_filter_dict_no_extra_calls():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import get_leagues
        get_leagues({})
    mock_client.table.return_value.ilike.assert_not_called()
    mock_client.table.return_value.in_.assert_not_called()


# ---------------------------------------------------------------------------
# get_quality_summary
# ---------------------------------------------------------------------------

def test_get_quality_summary_basic():
    rows = [{"quality_score": 80}, {"quality_score": 60}, {"quality_score": 40}]
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client(rows)):
        from src.database.leagues_reader import get_quality_summary
        result = get_quality_summary()
    assert result["total"] == 3
    assert result["avg_score"] == round((80 + 60 + 40) / 3, 1)
    assert result["pct_good"] == round(1 / 3 * 100, 1)   # only 80 >= 70
    assert result["pct_poor"] == round(1 / 3 * 100, 1)   # only 40 < 50


def test_get_quality_summary_empty():
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client([])):
        from src.database.leagues_reader import get_quality_summary
        result = get_quality_summary()
    assert result == {"total": 0, "avg_score": 0.0, "pct_good": 0.0, "pct_poor": 0.0}


# ---------------------------------------------------------------------------
# get_field_coverage
# ---------------------------------------------------------------------------

def test_get_field_coverage_full():
    """All fields populated → 100% for every field."""
    row = {
        "day_of_week": "Monday", "start_time": "19:00", "venue_name": "Lamport",
        "team_fee": 800.0, "individual_fee": None, "season_start_date": "2026-01-01",
        "season_end_date": "2026-03-01", "source_comp_level": "Rec",
        "gender_eligibility": "CoEd", "num_weeks": 10, "quality_score": 80,
    }
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client([row])):
        from src.database.leagues_reader import get_field_coverage
        result = get_field_coverage()
    assert result["day_of_week"] == 100.0
    assert result["individual_fee"] == 0.0   # None → not covered


def test_get_field_coverage_empty():
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client([])):
        from src.database.leagues_reader import get_field_coverage
        result = get_field_coverage()
    assert all(v == 0.0 for v in result.values())


# ---------------------------------------------------------------------------
# get_duplicate_groups
# ---------------------------------------------------------------------------

def test_get_duplicate_groups_finds_duplicates():
    rows = [
        {"league_id": "1", "organization_name": "TSSC", "sport_season_code": "V10",
         "season_year": 2026, "venue_name": "Lamport", "day_of_week": "Monday",
         "source_comp_level": "Rec", "quality_score": 80, "url_scraped": "https://a.com"},
        {"league_id": "2", "organization_name": "TSSC", "sport_season_code": "V10",
         "season_year": 2026, "venue_name": "Lamport", "day_of_week": "Monday",
         "source_comp_level": "Rec", "quality_score": 60, "url_scraped": "https://b.com"},
    ]
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client(rows)):
        from src.database.leagues_reader import get_duplicate_groups
        result = get_duplicate_groups()
    assert len(result) == 1
    assert len(result[0]["records"]) == 2


def test_get_duplicate_groups_no_duplicates():
    rows = [
        {"league_id": "1", "organization_name": "TSSC", "sport_season_code": "V10",
         "season_year": 2026, "venue_name": "Lamport", "day_of_week": "Monday",
         "source_comp_level": "Rec", "quality_score": 80, "url_scraped": "https://a.com"},
        {"league_id": "2", "organization_name": "ZogSports", "sport_season_code": "S10",
         "season_year": 2026, "venue_name": "Other", "day_of_week": "Tuesday",
         "source_comp_level": "Int", "quality_score": 70, "url_scraped": "https://b.com"},
    ]
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client(rows)):
        from src.database.leagues_reader import get_duplicate_groups
        result = get_duplicate_groups()
    assert result == []


# ---------------------------------------------------------------------------
# archive_league / add_to_rescrape_queue
# ---------------------------------------------------------------------------

def test_archive_league_calls_update():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import archive_league
        archive_league("abc-123")
    mock_client.table.return_value.update.assert_called_once_with({"is_archived": True})


def test_add_to_rescrape_queue_inserts_urls():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import add_to_rescrape_queue
        add_to_rescrape_queue(["https://example.com", "https://other.com"])
    assert mock_client.table.return_value.upsert.call_count == 1
