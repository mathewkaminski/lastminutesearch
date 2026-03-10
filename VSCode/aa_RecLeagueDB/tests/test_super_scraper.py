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
