"""Tests for competition level normalization."""
from src.utils.comp_level_normalizer import normalize_comp_level


class TestNormalizeCompLevel:
    def test_competitive_maps_to_a(self):
        assert normalize_comp_level("Competitive") == "A"

    def test_a_league_maps_to_a(self):
        assert normalize_comp_level("A League") == "A"

    def test_gold_maps_to_a(self):
        assert normalize_comp_level("Gold") == "A"

    def test_intermediate_maps_to_b(self):
        assert normalize_comp_level("Intermediate") == "B"

    def test_b_league_maps_to_b(self):
        assert normalize_comp_level("B League") == "B"

    def test_recreational_maps_to_c(self):
        assert normalize_comp_level("Recreational") == "C"

    def test_house_maps_to_c(self):
        assert normalize_comp_level("House") == "C"

    def test_division_1_maps_to_a(self):
        assert normalize_comp_level("Division 1") == "A"

    def test_unknown_returns_none(self):
        assert normalize_comp_level("Super Elite Pro") is None

    def test_none_returns_none(self):
        assert normalize_comp_level(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_comp_level("") is None

    def test_case_insensitive(self):
        assert normalize_comp_level("RECREATIONAL") == "C"

    def test_whitespace_trimmed(self):
        assert normalize_comp_level("  Competitive  ") == "A"

    def test_single_letter_a(self):
        assert normalize_comp_level("A") == "A"

    def test_single_letter_b(self):
        assert normalize_comp_level("B") == "B"

    def test_premier_maps_to_a(self):
        assert normalize_comp_level("Premier") == "A"

    def test_novice_maps_to_d(self):
        assert normalize_comp_level("Novice") == "D"
