from unittest.mock import patch, MagicMock


SAMPLE_YAML = "- role: div\n  name: Monday Soccer Spring 2026\n"


def _mock_haiku(text: str):
    """Return a mock Anthropic response with the given text."""
    mock = MagicMock()
    mock.content[0].text = text
    return mock


def test_classify_returns_league_detail():
    with patch("src.scraper.page_type_classifier.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_haiku("LEAGUE_DETAIL")
        from src.scraper.page_type_classifier import classify_page
        assert classify_page(SAMPLE_YAML) == "LEAGUE_DETAIL"


def test_classify_returns_schedule():
    with patch("src.scraper.page_type_classifier.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_haiku("SCHEDULE")
        from src.scraper.page_type_classifier import classify_page
        assert classify_page(SAMPLE_YAML) == "SCHEDULE"


def test_classify_returns_league_index():
    with patch("src.scraper.page_type_classifier.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_haiku("LEAGUE_INDEX")
        from src.scraper.page_type_classifier import classify_page
        assert classify_page(SAMPLE_YAML) == "LEAGUE_INDEX"


def test_classify_returns_other():
    with patch("src.scraper.page_type_classifier.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_haiku("OTHER")
        from src.scraper.page_type_classifier import classify_page
        assert classify_page(SAMPLE_YAML) == "OTHER"


def test_classify_defaults_to_other_on_api_error():
    with patch("src.scraper.page_type_classifier.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = Exception("API down")
        from src.scraper.page_type_classifier import classify_page
        assert classify_page(SAMPLE_YAML) == "OTHER"


def test_classify_truncates_large_input():
    """YAML is truncated to MAX_CLASSIFIER_CHARS before sending."""
    big_yaml = "x" * 20_000
    captured = {}

    def fake_create(**kwargs):
        captured["prompt"] = kwargs["messages"][0]["content"]
        return _mock_haiku("OTHER")

    with patch("src.scraper.page_type_classifier.anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = fake_create
        from src.scraper.page_type_classifier import classify_page, MAX_CLASSIFIER_CHARS
        classify_page(big_yaml)

    assert len(captured["prompt"]) <= MAX_CLASSIFIER_CHARS + 300  # prompt template overhead (~280 chars)
