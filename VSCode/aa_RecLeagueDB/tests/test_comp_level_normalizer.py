"""Tests for competition level normalization."""
from src.utils.comp_level_normalizer import normalize_comp_level


class TestNormalizeCompLevel:
    # --- Exact matches (existing) ---
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
        assert normalize_comp_level("Platinum Tier X") is None

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

    def test_none_found_maps_to_a(self):
        assert normalize_comp_level("None Found") == "A"

    def test_none_found_case_insensitive(self):
        assert normalize_comp_level("none found") == "A"

    # --- New exact matches ---
    def test_prem_maps_to_a(self):
        assert normalize_comp_level("PREM") == "A"

    def test_div_a_maps_to_a(self):
        assert normalize_comp_level("Div A") == "A"

    def test_div_b_maps_to_b(self):
        assert normalize_comp_level("Div B") == "B"

    def test_open_maps_to_b(self):
        assert normalize_comp_level("Open") == "B"

    def test_all_skill_levels_maps_to_b(self):
        assert normalize_comp_level("All Skill Levels") == "B"

    def test_rec_maps_to_c(self):
        assert normalize_comp_level("Rec") == "C"

    # --- Compound labels (fallback parser) ---
    def test_high_intermediate(self):
        assert normalize_comp_level("High Intermediate") == "B+"

    def test_high_rec(self):
        assert normalize_comp_level("High Rec") == "C+"

    def test_high_recreational(self):
        assert normalize_comp_level("High Recreational") == "C+"

    def test_upper_recreational(self):
        assert normalize_comp_level("Upper Recreational") == "C+"

    def test_recreational_plus(self):
        assert normalize_comp_level("Recreational Plus") == "C+"

    def test_intermediate_plus(self):
        assert normalize_comp_level("Intermediate Plus") == "B+"

    def test_beginner_rec(self):
        assert normalize_comp_level("Beginner Rec") == "C-"

    def test_really_rec(self):
        assert normalize_comp_level("Really Rec") == "C-"

    def test_rec_intermediate_slash(self):
        assert normalize_comp_level("Rec/Intermediate") == "B+"
