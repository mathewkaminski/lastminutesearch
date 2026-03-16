"""Tests for quality score calculation."""
import pytest
from src.database.validators import calculate_quality_score


COMPLETE_LEAGUE = {
    "organization_name": "Ottawa Volleyball",
    "sport_season_code": "201",
    "url_scraped": "https://example.com",
    "season_start_date": "2026-01-06",
    "season_end_date": "2026-03-24",
    "day_of_week": "Monday",
    "start_time": "19:00:00",
    "venue_name": "Greenwood Arena",
    "source_comp_level": "Recreational",
    "gender_eligibility": "CoEd",
    "team_fee": 1200.0,
    "num_weeks": 10,
    "players_per_side": 6,
    "registration_deadline": "2025-12-15",
}


class TestQualityScoreAdditions:
    def test_missing_num_weeks_penalized(self):
        league = {**COMPLETE_LEAGUE}
        del league["num_weeks"]
        score_without = calculate_quality_score(league)
        score_with = calculate_quality_score(COMPLETE_LEAGUE)
        assert score_with > score_without

    def test_missing_players_per_side_penalized(self):
        league = {**COMPLETE_LEAGUE}
        del league["players_per_side"]
        score_without = calculate_quality_score(league)
        score_with = calculate_quality_score(COMPLETE_LEAGUE)
        assert score_with > score_without

    def test_missing_registration_deadline_penalized(self):
        league = {**COMPLETE_LEAGUE}
        del league["registration_deadline"]
        score_without = calculate_quality_score(league)
        score_with = calculate_quality_score(COMPLETE_LEAGUE)
        assert score_with > score_without
