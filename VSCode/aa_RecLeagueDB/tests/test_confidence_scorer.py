# tests/test_confidence_scorer.py
from src.enrichers.confidence_scorer import score

GOOD_RESULT = {
    "name": "Ashbridges Bay Park",
    "formatted_address": "1561 Lake Shore Blvd E, Toronto, ON M4L 3W6, Canada",
    "types": ["park", "point_of_interest", "establishment"],
    "user_ratings_total": 500,
}


def test_perfect_match_scores_100():
    s = score("Ashbridges Bay Park", "Toronto", GOOD_RESULT)
    assert s == 100


def test_none_result_scores_zero():
    assert score("Any Venue", "Any City", None) == 0


def test_wrong_city_loses_city_points():
    result = {**GOOD_RESULT, "formatted_address": "123 Main St, Ottawa, ON K1A 0A9, Canada"}
    s = score("Ashbridges Bay Park", "Toronto", result)
    assert s <= 70  # lost 30 city points


def test_no_ratings_loses_quality_points():
    result = {**GOOD_RESULT, "user_ratings_total": 0}
    s = score("Ashbridges Bay Park", "Toronto", result)
    assert s == 90  # lost 10 quality points


def test_non_sports_type_loses_type_points():
    result = {**GOOD_RESULT, "types": ["restaurant", "food"]}
    s = score("Ashbridges Bay Park", "Toronto", result)
    assert s <= 80  # lost type points


def test_partial_name_match_reduces_name_score():
    s = score("Ashbridges Park", "Toronto", GOOD_RESULT)
    assert 70 <= s <= 99


def test_score_is_bounded_0_to_100():
    s = score("Completely Wrong Name", "Wrong City", {
        "name": "Something Else",
        "formatted_address": "456 Other St, Different City, AB T1A 0A0, Canada",
        "types": ["restaurant"],
        "user_ratings_total": 0,
    })
    assert 0 <= s <= 100
