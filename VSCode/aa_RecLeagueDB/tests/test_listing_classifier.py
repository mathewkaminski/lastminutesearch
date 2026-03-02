import pytest
from src.utils.listing_classifier import classify_listing_type


# --- Drop-in via keywords ---

def test_dropin_keyword_drop_in():
    assert classify_listing_type({"league_name": "Friday Drop-In Volleyball"}) == "drop_in"

def test_dropin_keyword_pickup():
    assert classify_listing_type({"division_name": "Pick-Up Basketball"}) == "drop_in"

def test_dropin_keyword_one_time():
    assert classify_listing_type({"league_name": "One-Time Social Night"}) == "drop_in"

def test_dropin_keyword_case_insensitive():
    assert classify_listing_type({"league_name": "OPEN PLAY TENNIS"}) == "drop_in"

def test_dropin_keyword_casual():
    assert classify_listing_type({"division_name": "Casual Badminton"}) == "drop_in"


# --- Drop-in via duration + price ---

def test_dropin_short_duration_low_price():
    assert classify_listing_type({"num_weeks": 1, "individual_fee": 15.0}) == "drop_in"

def test_dropin_null_weeks_low_price():
    assert classify_listing_type({"num_weeks": None, "individual_fee": 10.0}) == "drop_in"

def test_not_dropin_short_duration_high_price():
    # num_weeks=1 but price is $50 — not a drop-in
    result = classify_listing_type({"num_weeks": 1, "individual_fee": 50.0})
    assert result != "drop_in"

def test_not_dropin_no_price_info():
    # num_weeks=None, no price — not enough signal for drop_in
    result = classify_listing_type({"num_weeks": None})
    assert result == "unknown"


# --- League ---

def test_league_multi_week():
    assert classify_listing_type({"num_weeks": 10}) == "league"

def test_league_has_team_fee():
    assert classify_listing_type({"team_fee": 800.0}) == "league"

def test_league_four_weeks():
    assert classify_listing_type({"num_weeks": 4}) == "league"


# --- Unknown ---

def test_unknown_empty_record():
    assert classify_listing_type({}) == "unknown"

def test_unknown_no_relevant_fields():
    assert classify_listing_type({"organization_name": "TSSC", "venue_name": "Lamport"}) == "unknown"


# --- Keyword takes priority over other rules ---

def test_keyword_beats_league_signal():
    # Has team_fee but also drop-in keyword → drop_in wins
    assert classify_listing_type({"league_name": "Drop-In Night", "team_fee": 200.0}) == "drop_in"
