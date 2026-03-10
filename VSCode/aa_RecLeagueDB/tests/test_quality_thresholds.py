from src.config.quality_thresholds import (
    AUTO_REPLACE_THRESHOLD,
    DEEP_SCRAPE_THRESHOLD,
    get_quality_band,
    QualityBand,
)


def test_constants():
    assert AUTO_REPLACE_THRESHOLD == 60
    assert DEEP_SCRAPE_THRESHOLD == 75


def test_band_thin():
    assert get_quality_band(0) == QualityBand.THIN
    assert get_quality_band(59) == QualityBand.THIN


def test_band_borderline():
    assert get_quality_band(60) == QualityBand.BORDERLINE
    assert get_quality_band(74) == QualityBand.BORDERLINE


def test_band_acceptable():
    assert get_quality_band(75) == QualityBand.ACCEPTABLE
    assert get_quality_band(89) == QualityBand.ACCEPTABLE


def test_band_substantial():
    assert get_quality_band(90) == QualityBand.SUBSTANTIAL
    assert get_quality_band(100) == QualityBand.SUBSTANTIAL


def test_band_none_score():
    assert get_quality_band(None) == QualityBand.THIN
