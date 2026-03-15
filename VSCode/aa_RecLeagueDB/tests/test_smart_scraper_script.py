import sys


def test_min_completeness_pct_removed():
    """MIN_COMPLETENESS_PCT no longer exists in smart_scraper."""
    import inspect
    if "scripts.smart_scraper" in sys.modules:
        del sys.modules["scripts.smart_scraper"]
    import scripts.smart_scraper as ss

    assert not hasattr(ss, "MIN_COMPLETENESS_PCT")
    source = inspect.getsource(ss.run)
    assert "MIN_COMPLETENESS_PCT" not in source


def test_run_sends_low_quality_leagues_to_writer():
    """Leagues with identifying_fields_pct < 50 now reach insert_league."""
    import src.scraper.smart_crawler
    import src.extractors.yaml_extractor
    import src.database.writer
    from unittest.mock import patch

    low_quality = {
        "organization_name": "Test Org",
        "sport_season_code": "201",
        "url_scraped": "https://test.com",
        "identifying_fields_pct": 25,   # below old 50% gate
        "day_of_week": "Monday",
    }

    with (
        patch.object(src.scraper.smart_crawler, "crawl",
                     return_value=([("https://test.com", "yaml", "")], {}, {})),
        patch.object(src.extractors.yaml_extractor, "extract_league_data_from_yaml",
                     return_value=[low_quality]),
        patch.object(src.database.writer, "insert_league",
                     return_value=(None, False)) as mock_insert,
    ):
        if "scripts.smart_scraper" in sys.modules:
            del sys.modules["scripts.smart_scraper"]
        from scripts.smart_scraper import run
        result = run("https://test.com", dry_run=False)

    mock_insert.assert_called_once()       # reached insert_league (not pre-filtered)
    assert result["leagues_written"] == 0  # writer returned None → not counted as written
