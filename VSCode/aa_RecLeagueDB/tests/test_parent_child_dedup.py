"""Verify parent-aware dedup merges leagues with relaxed overlap."""
from src.utils.league_id_generator import deduplicate_batch


def test_parent_child_merge_with_sport_match():
    """Two leagues from parent/child pages with same sport merge even with <3 overlap."""
    parent_league = {
        "organization_name": "Edmonton Sports Club",
        "sport_name": "Soccer",
        "day_of_week": "Monday",
        "source_url": "https://edmontonsportsclub.com/programs",
    }
    child_league = {
        "organization_name": "Edmonton Sports Club",
        "sport_name": "Soccer",
        "source_comp_level": "Recreational",
        "gender_eligibility": "CoEd",
        "venue_name": "Commonwealth Stadium",
        "source_url": "https://edmontonsportsclub.com/sports/soccer",
    }
    parent_map = {
        "https://edmontonsportsclub.com/sports/soccer": "https://edmontonsportsclub.com/programs",
    }
    result = deduplicate_batch([parent_league, child_league], parent_map=parent_map)
    assert len(result) == 1
    merged = result[0]
    assert merged["source_comp_level"] == "Recreational"
    assert merged["day_of_week"] == "Monday"


def test_parent_child_no_merge_sport_mismatch():
    """Parent-child with different sports should NOT get relaxed merge."""
    parent_league = {
        "organization_name": "Edmonton Sports Club",
        "sport_name": "Soccer",
        "source_url": "https://edmontonsportsclub.com/programs",
    }
    child_league = {
        "organization_name": "Edmonton Sports Club",
        "sport_name": "Volleyball",
        "source_comp_level": "Recreational",
        "source_url": "https://edmontonsportsclub.com/sports/volleyball",
    }
    parent_map = {
        "https://edmontonsportsclub.com/sports/volleyball": "https://edmontonsportsclub.com/programs",
    }
    # With only 1 overlapping field (org_name) and sport mismatch, these stay separate
    result = deduplicate_batch([parent_league, child_league], parent_map=parent_map)
    assert len(result) == 2


def test_deduplicate_batch_without_parent_map():
    """Existing behavior unchanged when no parent_map is passed."""
    leagues = [
        {"organization_name": "Foo", "sport_name": "Soccer", "day_of_week": "Mon",
         "source_comp_level": "Rec"},
        {"organization_name": "Foo", "sport_name": "Soccer", "day_of_week": "Mon",
         "source_comp_level": "Rec", "venue_name": "Field A"},
    ]
    result = deduplicate_batch(leagues)
    assert len(result) == 1
