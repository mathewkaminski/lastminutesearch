from unittest.mock import patch, MagicMock
from scripts.super_scraper import run


def test_run_returns_result_dict():
    with patch("scripts.super_scraper.deep_crawl", return_value=[]), \
         patch("scripts.super_scraper._run_pass2", return_value=[]), \
         patch("scripts.super_scraper._get_existing_leagues", return_value=[]):
        result = run("https://example.com", dry_run=True)
        assert "url" in result
        assert "leagues_written" in result
        assert "archived" in result
        assert "review_queued" in result
        assert "errors" in result


def test_run_dry_run_does_not_write():
    fake_page = ("https://example.com/leagues", "yaml: content")
    fake_league = {
        "organization_name": "Test Org",
        "sport_season_code": "V01",
        "day_of_week": "Monday",
        "venue_name": "Park",
        "num_teams": 8,
        "quality_score": 55,
        "url_scraped": "https://example.com",
    }
    with patch("scripts.super_scraper.deep_crawl", return_value=[fake_page]), \
         patch("scripts.super_scraper.extract_league_data_from_yaml", return_value=[fake_league]), \
         patch("scripts.super_scraper._run_pass2", return_value=[]), \
         patch("scripts.super_scraper._get_existing_leagues", return_value=[]), \
         patch("scripts.super_scraper.insert_league") as mock_insert:
        result = run("https://example.com", dry_run=True)
        mock_insert.assert_not_called()


def test_match_pass2_single_fallback():
    """If Pass 2 has no division name but there's exactly one extracted league, match it."""
    from scripts.super_scraper import _match_pass2_to_extracted
    extracted = [{"day_of_week": "Monday", "gender_eligibility": "CoEd", "source_comp_level": "Rec"}]
    p2 = {"division_name": None, "num_teams": 8}
    assert _match_pass2_to_extracted(p2, extracted) is extracted[0]


def test_match_pass2_no_division_multi_league_returns_none():
    """If Pass 2 has no division name and there are multiple leagues, can't safely match."""
    from scripts.super_scraper import _match_pass2_to_extracted
    extracted = [
        {"day_of_week": "Monday", "gender_eligibility": "CoEd", "source_comp_level": "Rec"},
        {"day_of_week": "Wednesday", "gender_eligibility": "Mens", "source_comp_level": "Comp"},
    ]
    p2 = {"division_name": None, "num_teams": 8}
    assert _match_pass2_to_extracted(p2, extracted) is None


def test_match_pass2_by_division_name():
    """Division name matched against day + gender + comp_level fields."""
    from scripts.super_scraper import _match_pass2_to_extracted
    monday = {"day_of_week": "Monday", "gender_eligibility": "CoEd", "source_comp_level": "Recreational"}
    wednesday = {"day_of_week": "Wednesday", "gender_eligibility": "Mens", "source_comp_level": "Competitive"}
    p2 = {"division_name": "Monday CoEd Recreational", "num_teams": 10}
    matched = _match_pass2_to_extracted(p2, [monday, wednesday])
    assert matched is monday


def test_match_pass2_no_good_match_returns_none():
    """If nothing scores above threshold, return None (don't guess)."""
    from scripts.super_scraper import _match_pass2_to_extracted
    extracted = [{"day_of_week": "Friday", "gender_eligibility": "Womens", "source_comp_level": "Beginner"}]
    p2 = {"division_name": "Completely Different Text", "num_teams": 5}
    result = _match_pass2_to_extracted(p2, extracted)
    assert result is None


def test_run_multi_division_assigns_correct_counts():
    """Full run: two Pass 2 divisions assign to the right extracted league each."""
    monday = {
        "organization_name": "Test Org", "sport_season_code": "V01",
        "day_of_week": "Monday", "gender_eligibility": "CoEd",
        "source_comp_level": "Recreational", "url_scraped": "https://example.com",
        "quality_score": 60,
    }
    wednesday = {
        "organization_name": "Test Org", "sport_season_code": "V01",
        "day_of_week": "Wednesday", "gender_eligibility": "Mens",
        "source_comp_level": "Competitive", "url_scraped": "https://example.com",
        "quality_score": 60,
    }
    pass2_monday = {"division_name": "Monday CoEd Recreational", "num_teams": 8, "team_names": ["A"]*8, "nav_path": []}
    pass2_wednesday = {"division_name": "Wednesday Mens Competitive", "num_teams": 12, "team_names": ["B"]*12, "nav_path": []}

    fake_page = ("https://example.com/leagues", "yaml: content")
    with patch("scripts.super_scraper.deep_crawl", return_value=[fake_page]), \
         patch("scripts.super_scraper.extract_league_data_from_yaml", return_value=[monday, wednesday]), \
         patch("scripts.super_scraper._run_pass2", return_value=[pass2_monday, pass2_wednesday]), \
         patch("scripts.super_scraper._get_existing_leagues", return_value=[]):
        result = run("https://example.com", dry_run=True)

    assert monday.get("num_teams") == 8
    assert wednesday.get("num_teams") == 12
