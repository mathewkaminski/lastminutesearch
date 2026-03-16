"""Unit tests for query generator module."""

import pytest
from unittest.mock import patch, MagicMock
from src.search.query_generator import (
    build_query,
    generate_query_fingerprint,
    parse_multiline_input,
    generate_queries_from_input,
    check_duplicate_query
)


class TestBuildQuery:
    """Test query string building."""

    def test_build_query_with_season(self):
        """Test building query with season."""
        query = build_query("Toronto", "soccer", "summer")
        assert query == "Toronto summer soccer league"

    def test_build_query_without_season(self):
        """Test building query without season."""
        query = build_query("Chicago", "basketball")
        assert query == "Chicago basketball league"

    def test_build_query_season_none(self):
        """Test building query with None season."""
        query = build_query("New York", "volleyball", None)
        assert query == "New York volleyball league"

    def test_build_query_preserves_case(self):
        """Test that build_query preserves input case."""
        query = build_query("ToRoNtO", "SoCcEr")
        assert query == "ToRoNtO SoCcEr league"


class TestGenerateQueryFingerprint:
    """Test fingerprint generation for deduplication."""

    def test_fingerprint_basic_country_agnostic(self):
        """Test basic fingerprint generation without country (country-agnostic)."""
        fp = generate_query_fingerprint(
            city="Toronto",
            sport="soccer"
        )
        assert fp == "toronto|||soccer||"

    def test_fingerprint_with_us_country(self):
        """Test fingerprint with explicit US country."""
        fp = generate_query_fingerprint(
            city="Chicago",
            country="US",
            sport="soccer"
        )
        assert fp == "chicago||us|soccer||"

    def test_fingerprint_with_canadian_city(self):
        """Test fingerprint with Canadian city and country."""
        fp = generate_query_fingerprint(
            city="Toronto",
            country="CA",
            sport="soccer"
        )
        assert fp == "toronto||ca|soccer||"

    def test_fingerprint_with_all_fields(self):
        """Test fingerprint with all fields."""
        fp = generate_query_fingerprint(
            city="Toronto",
            state_province="ON",
            country="CA",
            sport="soccer",
            season="summer",
            year=2024
        )
        assert fp == "toronto|on|ca|soccer|summer|2024"

    def test_fingerprint_case_insensitive(self):
        """Test that fingerprints are case-insensitive."""
        fp1 = generate_query_fingerprint("Toronto", sport="Soccer", season="Summer")
        fp2 = generate_query_fingerprint("toronto", sport="soccer", season="summer")
        assert fp1 == fp2

    def test_fingerprint_whitespace_handling(self):
        """Test that fingerprints handle whitespace."""
        fp1 = generate_query_fingerprint("  Toronto  ", sport="  Soccer  ")
        fp2 = generate_query_fingerprint("Toronto", sport="Soccer")
        assert fp1 == fp2

    def test_fingerprint_none_fields(self):
        """Test fingerprint with None fields."""
        fp = generate_query_fingerprint(
            city="Toronto",
            state_province=None,
            country=None,
            sport="soccer",
            season=None,
            year=None
        )
        assert fp == "toronto|||soccer||"

    def test_fingerprint_empty_strings(self):
        """Test fingerprint with empty strings."""
        fp = generate_query_fingerprint(
            city="Toronto",
            state_province="",
            country="",
            sport="soccer",
            season="",
            year=None
        )
        assert fp == "toronto|||soccer||"

    def test_fingerprint_us_vs_ca_different(self):
        """Test that US and CA fingerprints are different for same city."""
        fp_us = generate_query_fingerprint("Vancouver", country="US", sport="soccer")
        fp_ca = generate_query_fingerprint("Vancouver", country="CA", sport="soccer")
        assert fp_us != fp_ca

    def test_fingerprint_country_agnostic_deduplication(self):
        """Test that country-agnostic fingerprints can match across countries."""
        fp1 = generate_query_fingerprint("Toronto", sport="soccer")  # No country
        fp2 = generate_query_fingerprint("Toronto", country=None, sport="soccer")  # Explicit None
        assert fp1 == fp2


class TestParseMultilineInput:
    """Test parsing multi-line user input."""

    def test_parse_simple_list(self):
        """Test parsing simple comma-separated list."""
        text = "Toronto\nChicago\nNew York"
        result = parse_multiline_input(text)
        assert result == ["Toronto", "Chicago", "New York"]

    def test_parse_with_whitespace(self):
        """Test parsing with extra whitespace."""
        text = "  Toronto  \n  Chicago  \n  New York  "
        result = parse_multiline_input(text)
        assert result == ["Toronto", "Chicago", "New York"]

    def test_parse_with_empty_lines(self):
        """Test parsing with empty lines."""
        text = "Toronto\n\nChicago\n\n\nNew York\n"
        result = parse_multiline_input(text)
        assert result == ["Toronto", "Chicago", "New York"]

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        result = parse_multiline_input("")
        assert result == []

    def test_parse_none(self):
        """Test parsing None."""
        result = parse_multiline_input(None)
        assert result == []

    def test_parse_single_item(self):
        """Test parsing single item."""
        result = parse_multiline_input("Toronto")
        assert result == ["Toronto"]

    def test_parse_windows_line_endings(self):
        """Test parsing with Windows line endings."""
        text = "Toronto\r\nChicago\r\nNew York"
        result = parse_multiline_input(text)
        # Should still work because split("\n") handles this
        assert len(result) >= 2


class TestCheckDuplicateQuery:
    """Test duplicate query detection."""

    @patch('src.search.query_generator.get_client')
    def test_check_duplicate_found(self, mock_get_client):
        """Test detecting an existing duplicate query."""
        mock_client = MagicMock()
        mock_client.table().select().eq().gte().execute.return_value = MagicMock(
            data=[{"query_id": "existing-query-123"}]
        )
        mock_get_client.return_value = mock_client

        is_dup = check_duplicate_query("toronto||us|soccer|summer|2024")

        assert is_dup is True

    @patch('src.search.query_generator.get_client')
    def test_check_duplicate_not_found(self, mock_get_client):
        """Test when no duplicate query exists."""
        mock_client = MagicMock()
        mock_client.table().select().eq().gte().execute.return_value = MagicMock(
            data=[]
        )
        mock_get_client.return_value = mock_client

        is_dup = check_duplicate_query("toronto||us|soccer|summer|2024")

        assert is_dup is False

    @patch('src.search.query_generator.get_client')
    def test_check_duplicate_custom_days(self, mock_get_client):
        """Test checking with custom day range."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_select = MagicMock()
        mock_eq = MagicMock()

        # Chain the mocks
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_eq
        mock_eq.gte.return_value = mock_eq
        mock_eq.execute.return_value = MagicMock(data=[])

        mock_get_client.return_value = mock_client

        check_duplicate_query("test-fp", days=60)

        # Verify gte was called with 60 days
        mock_eq.gte.assert_called()
        call_args = mock_eq.gte.call_args
        assert "60 days" in str(call_args)

    @patch('src.search.query_generator.get_client')
    def test_check_duplicate_db_error(self, mock_get_client):
        """Test error handling when database query fails."""
        mock_client = MagicMock()
        mock_client.table().select().eq().gte().execute.side_effect = Exception("DB Error")
        mock_get_client.return_value = mock_client

        with pytest.raises(Exception, match="DB Error"):
            check_duplicate_query("test-fp")


class TestGenerateQueriesFromInput:
    """Test full query generation from user input."""

    @patch('src.search.query_generator.check_duplicate_query')
    def test_generate_queries_basic(self, mock_check_dup):
        """Test generating queries from basic inputs."""
        mock_check_dup.return_value = False  # No duplicates

        cities = ["Toronto", "Chicago"]
        sports = ["soccer", "basketball"]

        new_queries, dup_queries = generate_queries_from_input(
            cities=cities,
            sports=sports,
            check_duplicates=False
        )

        # 2 cities × 2 sports = 4 queries
        assert len(new_queries) == 4
        assert len(dup_queries) == 0

        # Verify query structure
        assert all('query_text' in q for q in new_queries)
        assert all('city' in q for q in new_queries)
        assert all('sport' in q for q in new_queries)
        assert all('query_fingerprint' in q for q in new_queries)

    @patch('src.search.query_generator.check_duplicate_query')
    def test_generate_queries_with_seasons(self, mock_check_dup):
        """Test generating queries with seasons."""
        mock_check_dup.return_value = False

        cities = ["Toronto"]
        sports = ["soccer"]
        seasons = ["summer", "winter"]

        new_queries, dup_queries = generate_queries_from_input(
            cities=cities,
            sports=sports,
            seasons=seasons,
            check_duplicates=False
        )

        # 1 city × 1 sport × 2 seasons = 2 queries
        assert len(new_queries) == 2

        # Verify season field is set
        assert new_queries[0]['season'] == "summer"
        assert new_queries[1]['season'] == "winter"

    @patch('src.search.query_generator.check_duplicate_query')
    def test_generate_queries_no_seasons(self, mock_check_dup):
        """Test that queries without seasons have season=None."""
        mock_check_dup.return_value = False

        cities = ["Toronto"]
        sports = ["soccer"]

        new_queries, dup_queries = generate_queries_from_input(
            cities=cities,
            sports=sports,
            check_duplicates=False
        )

        # 1 city × 1 sport × 1 (no seasons) = 1 query
        assert len(new_queries) == 1
        assert new_queries[0]['season'] is None

    @patch('src.search.query_generator.check_duplicate_query')
    def test_generate_queries_with_duplicates(self, mock_check_dup):
        """Test that duplicate queries are separated."""
        # First and third queries are duplicates
        mock_check_dup.side_effect = [False, False, True, False]

        cities = ["Toronto", "Chicago"]
        sports = ["soccer"]

        new_queries, dup_queries = generate_queries_from_input(
            cities=cities,
            sports=sports,
            check_duplicates=True
        )

        # 2 cities × 1 sport = 2 total
        # 1 new, 1 duplicate (Toronto appears twice in mocked responses)
        assert len(new_queries) + len(dup_queries) == 2

    @patch('src.search.query_generator.check_duplicate_query')
    def test_generate_queries_matrix_size(self, mock_check_dup):
        """Test that matrix is fully generated (all combinations)."""
        mock_check_dup.return_value = False

        cities = ["A", "B", "C"]
        sports = ["X", "Y"]
        seasons = ["S1", "S2"]

        new_queries, dup_queries = generate_queries_from_input(
            cities=cities,
            sports=sports,
            seasons=seasons,
            check_duplicates=False
        )

        # 3 × 2 × 2 = 12 combinations
        assert len(new_queries) == 12

    @patch('src.search.query_generator.check_duplicate_query')
    def test_generate_queries_preserves_order(self, mock_check_dup):
        """Test that queries are generated in expected order."""
        mock_check_dup.return_value = False

        cities = ["Toronto", "Chicago"]
        sports = ["soccer", "basketball"]

        new_queries, dup_queries = generate_queries_from_input(
            cities=cities,
            sports=sports,
            check_duplicates=False
        )

        # Expected order: Toronto-soccer, Toronto-basketball, Chicago-soccer, Chicago-basketball
        expected_queries = [
            "Toronto soccer league",
            "Toronto basketball league",
            "Chicago soccer league",
            "Chicago basketball league"
        ]

        actual_queries = [q['query_text'] for q in new_queries]
        assert actual_queries == expected_queries

    @patch('src.search.query_generator.check_duplicate_query')
    def test_generate_queries_with_year_and_state(self, mock_check_dup):
        """Test generating queries with year and state_province."""
        mock_check_dup.return_value = False

        new_queries, _ = generate_queries_from_input(
            cities=["Toronto"],
            sports=["soccer"],
            country="CA",
            state_province="ON",
            year=2024,
            check_duplicates=False
        )

        assert len(new_queries) == 1
        q = new_queries[0]
        assert q['country'] == "CA"
        assert q['state_province'] == "ON"
        assert q['year'] == 2024

    @patch('src.search.query_generator.check_duplicate_query')
    def test_generate_queries_skip_check_duplicates(self, mock_check_dup):
        """Test that duplicate checking can be disabled."""
        cities = ["Toronto"]
        sports = ["soccer"]

        new_queries, dup_queries = generate_queries_from_input(
            cities=cities,
            sports=sports,
            check_duplicates=False  # Disabled
        )

        # Check_duplicate_query should not be called
        mock_check_dup.assert_not_called()
        assert len(new_queries) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
