"""Tests for field coverage gap reporting."""
import pytest
from src.extractors.gap_reporter import compute_field_coverage, map_fields_to_categories, ALL_LEAGUE_FIELDS


class TestComputeFieldCoverage:
    def test_empty_leagues_returns_all_missing(self):
        result = compute_field_coverage([])
        assert result["coverage_pct"] == 0.0
        assert set(result["missing"]) == set(ALL_LEAGUE_FIELDS)
        assert result["covered"] == []

    def test_all_fields_covered(self):
        league = {field: "value" for field in ALL_LEAGUE_FIELDS}
        result = compute_field_coverage([league])
        assert result["coverage_pct"] == 100.0
        assert result["missing"] == []

    def test_partial_coverage(self):
        league = {
            "day_of_week": "Monday",
            "start_time": "19:00:00",
            "venue_name": "Greenwood Arena",
        }
        result = compute_field_coverage([league])
        assert "day_of_week" in result["covered"]
        assert "team_fee" in result["missing"]
        assert 0 < result["coverage_pct"] < 100

    def test_union_across_multiple_leagues(self):
        """Coverage is union — a field covered in any league counts as covered."""
        league1 = {"team_fee": 150.0}
        league2 = {"venue_name": "Arena"}
        result = compute_field_coverage([league1, league2])
        assert "team_fee" in result["covered"]
        assert "venue_name" in result["covered"]

    def test_null_values_count_as_missing(self):
        league = {"team_fee": None, "venue_name": "Arena"}
        result = compute_field_coverage([league])
        assert "team_fee" in result["missing"]
        assert "venue_name" in result["covered"]


class TestMapFieldsToCategories:
    def test_team_fee_maps_to_registration(self):
        result = map_fields_to_categories(["team_fee", "individual_fee"])
        assert "REGISTRATION" in result
        assert "team_fee" in result["REGISTRATION"]

    def test_num_teams_maps_to_schedule(self):
        result = map_fields_to_categories(["num_teams", "day_of_week"])
        assert "SCHEDULE" in result

    def test_insurance_maps_to_policy(self):
        result = map_fields_to_categories(["insurance_policy_link", "has_referee"])
        assert "POLICY" in result


class TestStoreGapReport:
    def test_store_gap_report_calls_supabase_update(self):
        """store_gap_report() updates page_snapshots.metadata with gap_report key."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        # Simulate finding one existing snapshot row
        mock_client.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = [
                {"id": "abc-123", "metadata": {"existing_key": "value"}}
            ]

        with patch("src.database.snapshot_store.get_client", return_value=mock_client):
            from src.database.snapshot_store import store_gap_report
            store_gap_report("example.com", {"covered": ["day_of_week"], "missing": [], "coverage_pct": 100.0})

        # Verify update was called with merged metadata including gap_report
        update_call = mock_client.table.return_value.update
        update_call.assert_called_once()
        call_kwargs = update_call.call_args[0][0]
        assert "gap_report" in call_kwargs["metadata"]
        assert call_kwargs["metadata"]["existing_key"] == "value"  # existing keys preserved
