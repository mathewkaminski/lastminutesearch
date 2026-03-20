"""Tests for FieldEnricher."""
import json
import pytest
from unittest.mock import MagicMock, patch
from src.enrichers.field_enricher import FieldEnricher, FieldEnrichResult, ENRICHABLE_FIELDS


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def enricher():
    return FieldEnricher(supabase_client=MagicMock(), anthropic_api_key="test-key")


def _make_league(**overrides) -> dict:
    """Return a minimal league dict. All enrichable fields null by default."""
    base = {
        "league_id": "uuid-1",
        "organization_name": "Ottawa Volley Sixes",
        "url_scraped": "https://ottawavolleysixes.com/register",
        "sport_season_code": "411",
    }
    # All enrichable fields null
    for f in ENRICHABLE_FIELDS:
        base[f] = None
    base.update(overrides)
    return base


# ── _get_null_fields ──────────────────────────────────────────────────────────

def test_get_null_fields_all_null(enricher):
    """Returns all ENRICHABLE_FIELDS when all are null."""
    league = _make_league()
    result = enricher._get_null_fields(league)
    assert set(result) == set(ENRICHABLE_FIELDS)


def test_get_null_fields_excludes_populated(enricher):
    """Excludes fields that already have values."""
    league = _make_league(venue_name="Nepean Sportsplex", team_fee=875.0)
    result = enricher._get_null_fields(league)
    assert "venue_name" not in result
    assert "team_fee" not in result
    # Others still returned
    assert "day_of_week" in result


def test_get_null_fields_excludes_num_teams(enricher):
    """num_teams is never in the enrichable list."""
    league = _make_league(num_teams=None)
    result = enricher._get_null_fields(league)
    assert "num_teams" not in result


def test_get_null_fields_all_populated(enricher):
    """Returns empty list when all enrichable fields have values."""
    league = _make_league(**{f: "x" for f in ENRICHABLE_FIELDS})
    assert enricher._get_null_fields(league) == []


# ── _build_prompt ─────────────────────────────────────────────────────────────

def test_build_prompt_contains_null_fields(enricher):
    """Prompt includes all requested null fields."""
    leagues = [_make_league()]
    null_fields = ["venue_name", "team_fee", "day_of_week"]
    prompt = enricher._build_prompt("some page content", null_fields, leagues)
    for f in null_fields:
        assert f in prompt


def test_build_prompt_excludes_populated_fields(enricher):
    """Prompt schema does not mention fields not in null_fields."""
    leagues = [_make_league(venue_name="Nepean Sportsplex")]
    null_fields = ["team_fee", "day_of_week"]  # venue_name NOT in null_fields
    prompt = enricher._build_prompt("some content", null_fields, leagues)
    assert "team_fee" in prompt
    assert "day_of_week" in prompt
    # venue_name should not appear in the schema section
    # (split on OUTPUT SCHEMA to check only schema part)
    schema_part = prompt.split("OUTPUT SCHEMA")[1] if "OUTPUT SCHEMA" in prompt else prompt
    assert "venue_name" not in schema_part


def test_build_prompt_includes_league_context(enricher):
    """Prompt includes org name in the context section."""
    leagues = [_make_league(organization_name="Ottawa Volley Sixes", day_of_week="Monday")]
    null_fields = ["venue_name", "team_fee"]
    prompt = enricher._build_prompt("content", null_fields, leagues)
    assert "Ottawa Volley Sixes" in prompt


def test_build_prompt_includes_content(enricher):
    """Prompt includes the page content."""
    leagues = [_make_league()]
    prompt = enricher._build_prompt("UNIQUE_MARKER_XYZ", ["venue_name"], leagues)
    assert "UNIQUE_MARKER_XYZ" in prompt


def test_build_prompt_includes_full_text(enricher):
    """Prompt includes full_text when provided."""
    leagues = [_make_league()]
    prompt = enricher._build_prompt("yaml content", ["venue_name"], leagues, full_text="FULL_TEXT_MARKER")
    assert "FULL_TEXT_MARKER" in prompt


def test_build_prompt_null_instruction_is_strict(enricher):
    """Prompt contains the CRITICAL null instruction."""
    leagues = [_make_league()]
    prompt = enricher._build_prompt("content", ["venue_name"], leagues)
    assert "CRITICAL" in prompt
    assert "null" in prompt.lower()


# ── _extract ──────────────────────────────────────────────────────────────────

def test_extract_returns_field_patches(enricher):
    """_extract calls Claude and parses JSON array response."""
    leagues = [_make_league()]
    null_fields = ["venue_name", "team_fee"]
    api_response = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex", "team_fee": 875.0}]

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(api_response))]
    enricher._anthropic.messages.create = MagicMock(return_value=mock_message)

    result = enricher._extract("page content", null_fields, leagues)
    assert len(result) == 1
    assert result[0]["venue_name"] == "Nepean Sportsplex"
    assert result[0]["team_fee"] == 875.0


def test_extract_strips_null_values(enricher):
    """_extract removes null values from patches."""
    leagues = [_make_league()]
    null_fields = ["venue_name", "team_fee"]
    api_response = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex", "team_fee": None}]

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(api_response))]
    enricher._anthropic.messages.create = MagicMock(return_value=mock_message)

    result = enricher._extract("content", null_fields, leagues)
    assert "team_fee" not in result[0]
    assert result[0].get("venue_name") == "Nepean Sportsplex"


def test_extract_handles_invalid_json(enricher):
    """_extract returns empty list on parse error (does not raise)."""
    leagues = [_make_league()]
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="not json at all")]
    enricher._anthropic.messages.create = MagicMock(return_value=mock_message)

    result = enricher._extract("content", ["venue_name"], leagues)
    assert result == []


def test_write_back_updates_patched_fields(enricher):
    """_write_back calls Supabase update with patch + recalculated quality_score."""
    # Mock DB fetch of current record
    current_league = _make_league(league_id="uuid-1")
    enricher._db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [current_league]
    enricher._db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    enricher._write_back("uuid-1", {"venue_name": "Nepean Sportsplex", "team_fee": 875.0})

    update_call = enricher._db.table.return_value.update
    update_call.assert_called_once()
    updated_data = update_call.call_args[0][0]
    assert updated_data["venue_name"] == "Nepean Sportsplex"
    assert updated_data["team_fee"] == 875.0
    assert "quality_score" in updated_data
    assert "updated_at" in updated_data


# ── enrich_url ────────────────────────────────────────────────────────────────

def _mock_db_leagues(enricher, leagues: list[dict]) -> None:
    """Wire enricher._db to return given leagues."""
    mock_chain = MagicMock()
    mock_chain.execute.return_value.data = leagues
    enricher._db.table.return_value.select.return_value.eq.return_value.eq.return_value = mock_chain


def test_enrich_url_cache_hit_writes_back(enricher):
    """Cache hit: URL-specific YAML found → extract → write_back called per league."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    patches = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex", "team_fee": 875.0}]
    enricher._extract = MagicMock(return_value=patches)
    enricher._write_back = MagicMock()

    cached_meta = {"full_text": "Nepean Sportsplex content", "cached": True}
    with patch("src.enrichers.field_enricher.load_yaml_from_cache", return_value=("yaml content", cached_meta)):
        results = enricher.enrich_url(url)

    assert len(results) == 1
    assert results[0].source == "cache"
    assert "venue_name" in results[0].filled_fields
    assert "team_fee" in results[0].filled_fields
    enricher._write_back.assert_called_once_with(
        "uuid-1", {"venue_name": "Nepean Sportsplex", "team_fee": 875.0}
    )


def test_enrich_url_cache_miss_fetches_live_playwright(enricher):
    """Cache miss: live Playwright fetch used; source set to 'playwright'."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    patches = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex"}]
    enricher._extract = MagicMock(return_value=patches)
    enricher._write_back = MagicMock()

    live_meta = {"full_text": "live page text", "cached": False}
    with (
        patch("src.enrichers.field_enricher.load_yaml_from_cache", return_value=(None, None)),
        patch("src.enrichers.field_enricher.fetch_page_as_yaml", return_value=("live yaml", live_meta)),
    ):
        results = enricher.enrich_url(url)

    assert results[0].source == "playwright"
    assert "venue_name" in results[0].filled_fields


def test_enrich_url_playwright_fetch_failure_returns_error(enricher):
    """Live Playwright fetch raises → result with error set, no exception raised."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    enricher._write_back = MagicMock()

    with (
        patch("src.enrichers.field_enricher.load_yaml_from_cache", return_value=(None, None)),
        patch("src.enrichers.field_enricher.fetch_page_as_yaml", side_effect=RuntimeError("Playwright failed")),
    ):
        results = enricher.enrich_url(url)

    assert results[0].error is not None
    assert "Playwright" in results[0].error
    assert results[0].source == "none"
    enricher._write_back.assert_not_called()


def test_enrich_url_explicit_firecrawl_mode(enricher):
    """use_firecrawl=True: Firecrawl called after extraction with source 'firecrawl'."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    call_count = {"n": 0}

    def extract_side_effect(content, null_fields, leagues, full_text=""):
        call_count["n"] += 1
        # First call (Playwright cache) returns nothing; second (Firecrawl) fills
        if call_count["n"] == 1:
            return []
        return [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex"}]

    enricher._extract = MagicMock(side_effect=extract_side_effect)
    enricher._write_back = MagicMock()

    mock_fc_instance = MagicMock()
    mock_fc_instance.scrape.return_value = "Firecrawl page content"

    cached_meta = {"full_text": "standings only", "cached": True}
    with (
        patch("src.enrichers.field_enricher.load_yaml_from_cache", return_value=("yaml content", cached_meta)),
        patch("src.enrichers.field_enricher.FirecrawlClient", return_value=mock_fc_instance),
    ):
        results = enricher.enrich_url(url, use_firecrawl=True)

    assert results[0].source == "firecrawl"
    mock_fc_instance.scrape.assert_called_once_with(url)


def test_enrich_url_firecrawl_not_called_by_default(enricher):
    """Firecrawl is NOT called automatically when cache extraction is empty."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    enricher._extract = MagicMock(return_value=[])
    enricher._write_back = MagicMock()
    enricher._mini_crawl_for_fields = MagicMock(return_value={})

    mock_fc_instance = MagicMock()

    cached_meta = {"full_text": "standings only", "cached": True}
    with (
        patch("src.enrichers.field_enricher.load_yaml_from_cache", return_value=("yaml content", cached_meta)),
        patch("src.enrichers.field_enricher.FirecrawlClient", return_value=mock_fc_instance),
    ):
        results = enricher.enrich_url(url)

    mock_fc_instance.scrape.assert_not_called()
    assert results[0].source == "none"


def test_enrich_url_no_null_fields_skips_extraction(enricher):
    """League with all fields populated → extraction skipped, source=none."""
    league = _make_league(**{f: "x" for f in ENRICHABLE_FIELDS})
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    enricher._extract = MagicMock()

    results = enricher.enrich_url(url)

    enricher._extract.assert_not_called()
    assert results[0].source == "none"
    assert results[0].filled_fields == []


def test_enrich_url_firecrawl_error_returns_error_result(enricher):
    """Firecrawl failure with use_firecrawl=True → result with error set, no exception raised."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    enricher._extract = MagicMock(return_value=[])
    enricher._write_back = MagicMock()
    enricher._mini_crawl_for_fields = MagicMock(return_value={})

    mock_fc_instance = MagicMock()
    mock_fc_instance.scrape.side_effect = RuntimeError("Firecrawl blocked")

    cached_meta = {"full_text": "", "cached": True}
    with (
        patch("src.enrichers.field_enricher.load_yaml_from_cache", return_value=("yaml content", cached_meta)),
        patch("src.enrichers.field_enricher.FirecrawlClient", return_value=mock_fc_instance),
    ):
        results = enricher.enrich_url(url, use_firecrawl=True)

    assert results[0].error is not None
    assert "blocked" in results[0].error
    assert results[0].source == "none"


# ── TestMiniCrawlTier ─────────────────────────────────────────────────────────

class TestMiniCrawlTier:
    def test_enrich_url_calls_mini_crawl_when_cache_yields_nothing(self):
        """When cache extraction returns empty patches, mini-crawl is attempted."""
        fake_leagues = [{"league_id": "abc", "organization_name": "Test", "url_scraped": "https://example.com", "is_archived": False, "team_fee": None, "venue_name": None}]

        with (
            patch("src.enrichers.field_enricher.load_yaml_from_cache") as mock_cache,
            patch("src.enrichers.field_enricher.FieldEnricher._extract") as mock_extract,
            patch("src.enrichers.field_enricher.FieldEnricher._mini_crawl_for_fields") as mock_mini,
            patch("src.enrichers.field_enricher.FieldEnricher._write_back"),
        ):
            # DB returns fake league
            mock_db = MagicMock()
            mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = fake_leagues

            mock_cache.return_value = ("yaml content", {"full_text": "snapshot content", "cached": True})
            mock_extract.return_value = []  # cache extraction finds nothing
            mock_mini.return_value = {"team_fee": 150.0}  # mini-crawl finds team_fee

            from src.enrichers.field_enricher import FieldEnricher
            enricher = FieldEnricher(supabase_client=mock_db)
            enricher.enrich_url("https://example.com")

        mock_mini.assert_called_once()

    def test_mini_crawl_skipped_when_cache_fills_all_fields(self):
        """Mini-crawl not attempted if cache extraction fills all null fields."""
        # All ENRICHABLE_FIELDS populated except team_fee; cache patch fills team_fee
        base_league = {"league_id": "abc", "organization_name": "Test", "url_scraped": "https://example.com", "is_archived": False}
        for f in ENRICHABLE_FIELDS:
            base_league[f] = "x"
        base_league["team_fee"] = None
        fake_leagues = [base_league]
        fake_patch = [{"league_id": "abc", "team_fee": 150.0}]

        with (
            patch("src.enrichers.field_enricher.load_yaml_from_cache") as mock_cache,
            patch("src.enrichers.field_enricher.FieldEnricher._extract") as mock_extract,
            patch("src.enrichers.field_enricher.FieldEnricher._mini_crawl_for_fields") as mock_mini,
            patch("src.enrichers.field_enricher.FieldEnricher._write_back"),
        ):
            mock_db = MagicMock()
            mock_db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = fake_leagues

            mock_cache.return_value = ("yaml content", {"full_text": "snapshot content", "cached": True})
            mock_extract.return_value = fake_patch  # cache filled everything

            from src.enrichers.field_enricher import FieldEnricher
            enricher = FieldEnricher(supabase_client=mock_db)
            enricher.enrich_url("https://example.com")

        mock_mini.assert_not_called()
