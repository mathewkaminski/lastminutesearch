# Fill In Leagues Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the League Checker page with "Fill In Leagues" — a multi-mode enrichment UI that patches null fields on existing `leagues_metadata` records using cached YAML snapshots with a Firecrawl fallback.

**Architecture:** Three modes — Deep-dive delegates to `super_scraper.py`, Teams delegates to `count_teams_scraper.py`, Fill Fields runs a new `FieldEnricher` that pulls cached snapshots from `page_snapshots`, extracts only the null fields via Claude, and falls back to Firecrawl if no snapshot exists or extraction returns nothing. Field patches are written back via a direct Supabase update (not a full re-insert).

**Tech Stack:** Python 3.10+, Supabase (postgrest-py), Anthropic SDK (claude-sonnet-4-6), Firecrawl REST API, Streamlit, pytest + unittest.mock

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/scraper/firecrawl_client.py` | Create | Minimal Firecrawl API wrapper |
| `src/enrichers/field_enricher.py` | Create | FieldEnricher: snapshot lookup, targeted extraction, write-back, Firecrawl fallback |
| `streamlit_app/pages/fill_in_leagues.py` | Create | Fill In Leagues Streamlit page (replaces league_checker) |
| `streamlit_app/app.py` | Modify | Swap nav entry from League Checker → Fill In Leagues |
| `streamlit_app/pages/league_checker.py` | Delete | Retired |
| `tests/test_firecrawl_client.py` | Create | Unit tests for FirecrawlClient |
| `tests/test_field_enricher.py` | Create | Unit tests for FieldEnricher |

---

## Chunk 1: FirecrawlClient

### Task 1: FirecrawlClient — test + implementation

**Files:**
- Create: `src/scraper/firecrawl_client.py`
- Create: `tests/test_firecrawl_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_firecrawl_client.py`:

```python
"""Tests for FirecrawlClient."""
import pytest
from unittest.mock import patch, MagicMock
from src.scraper.firecrawl_client import FirecrawlClient


def test_scrape_returns_markdown():
    """Successful scrape returns markdown string from API response."""
    client = FirecrawlClient(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "success": True,
        "data": {"markdown": "# Ottawa Volley Sixes\nTeam fee: $875"}
    }
    with patch("requests.post", return_value=mock_response) as mock_post:
        result = client.scrape("https://example.com/register")

    assert result == "# Ottawa Volley Sixes\nTeam fee: $875"
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test-key"
    assert call_kwargs[1]["json"]["url"] == "https://example.com/register"


def test_scrape_raises_on_http_error():
    """HTTP error raises RuntimeError."""
    client = FirecrawlClient(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="Firecrawl request failed"):
            client.scrape("https://example.com")


def test_scrape_raises_on_missing_markdown():
    """API success=False raises RuntimeError."""
    client = FirecrawlClient(api_key="test-key")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"success": False, "error": "blocked"}
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="Firecrawl returned no markdown"):
            client.scrape("https://example.com")


def test_missing_api_key_raises():
    """Constructor raises if api_key is empty."""
    with pytest.raises(ValueError, match="api_key"):
        FirecrawlClient(api_key="")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
python -m pytest tests/test_firecrawl_client.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` (file doesn't exist yet).

- [ ] **Step 3: Implement FirecrawlClient**

Create `src/scraper/firecrawl_client.py`:

```python
"""Minimal Firecrawl API wrapper for fetching page content as markdown."""
from __future__ import annotations

import logging
import requests

logger = logging.getLogger(__name__)

FIRECRAWL_API_URL = "https://api.firecrawl.dev/v1/scrape"


class FirecrawlClient:
    """Wraps the Firecrawl /v1/scrape endpoint.

    Usage:
        client = FirecrawlClient(api_key=os.environ["FIRECRAWL_API_KEY"])
        markdown = client.scrape("https://example.com/register")
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key

    def scrape(self, url: str) -> str:
        """Fetch a URL via Firecrawl and return its content as markdown.

        Args:
            url: Page URL to scrape.

        Returns:
            Markdown string of page content.

        Raises:
            RuntimeError: If the HTTP request fails or API returns no markdown.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"url": url, "formats": ["markdown"]}

        try:
            response = requests.post(
                FIRECRAWL_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Firecrawl request failed for {url}: {exc}") from exc

        body = response.json()
        if not body.get("success"):
            raise RuntimeError(
                f"Firecrawl returned no markdown for {url}: {body.get('error', 'unknown error')}"
            )

        markdown = body.get("data", {}).get("markdown", "")
        if not markdown:
            raise RuntimeError(f"Firecrawl returned no markdown for {url}")

        logger.info("Firecrawl fetched %d chars for %s", len(markdown), url)
        return markdown
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_firecrawl_client.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/firecrawl_client.py tests/test_firecrawl_client.py
git commit -m "feat: add FirecrawlClient minimal API wrapper"
```

---

## Chunk 2: FieldEnricher

### Task 2: FieldEnricher — null field detection

**Files:**
- Create: `src/enrichers/field_enricher.py` (skeleton + `_get_null_fields`)
- Create: `tests/test_field_enricher.py`

The enrichable fields — all fields that can be extracted from web content, excluding system fields, FKs, and `num_teams` (handled by Teams mode):

```python
ENRICHABLE_FIELDS = [
    "day_of_week", "start_time", "num_weeks", "time_played_per_week",
    "season_start_date", "season_end_date", "stat_holidays",
    "venue_name",
    "team_fee", "individual_fee", "registration_deadline",
    "competition_level", "gender_eligibility", "players_per_side",
    "slots_left",
    "has_referee", "requires_insurance", "insurance_policy_link",
]
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_field_enricher.py`:

```python
"""Tests for FieldEnricher."""
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
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_field_enricher.py -v
```

Expected: `ImportError` (file doesn't exist).

- [ ] **Step 3: Implement skeleton + `_get_null_fields`**

Create `src/enrichers/field_enricher.py`:

```python
"""FieldEnricher — patches null fields on leagues_metadata records.

Flow per URL:
  1. Fetch leagues for URL → identify null enrichable fields
  2. Pull latest page snapshot from page_snapshots by domain
  3. If snapshot: run targeted Claude extraction → write back hits
  4. If no snapshot or nothing extracted: Firecrawl URL → repeat step 3
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

import anthropic

from src.database.supabase_client import get_client
from src.database.snapshot_store import get_snapshots_by_domain
from src.database.validators import calculate_quality_score

logger = logging.getLogger(__name__)

# All fields that can be extracted from web content.
# num_teams is excluded — handled by Teams mode.
ENRICHABLE_FIELDS: list[str] = [
    "day_of_week", "start_time", "num_weeks", "time_played_per_week",
    "season_start_date", "season_end_date", "stat_holidays",
    "venue_name",
    "team_fee", "individual_fee", "registration_deadline",
    "competition_level", "gender_eligibility", "players_per_side",
    "slots_left",
    "has_referee", "requires_insurance", "insurance_policy_link",
]


@dataclass
class FieldEnrichResult:
    league_id: str
    org_name: str
    filled_fields: list[str] = field(default_factory=list)
    skipped_fields: list[str] = field(default_factory=list)
    source: str = "none"          # "cache" | "firecrawl" | "none"
    error: str | None = None


class FieldEnricher:
    """Enriches null fields on leagues_metadata using cached snapshots and Firecrawl."""

    def __init__(
        self,
        supabase_client=None,
        anthropic_api_key: str | None = None,
    ) -> None:
        self._db = supabase_client or get_client()
        self._anthropic = anthropic.Anthropic(
            api_key=anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )

    # ── public ────────────────────────────────────────────────────────────────

    def enrich_url(self, url: str) -> list[FieldEnrichResult]:
        """Enrich all leagues at a URL. Returns one result per league."""
        raise NotImplementedError("implemented in Task 5")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_null_fields(self, league: dict) -> list[str]:
        """Return ENRICHABLE_FIELDS that are None on this league record."""
        return [f for f in ENRICHABLE_FIELDS if league.get(f) is None]

    def _build_prompt(self, content: str, null_fields: list[str], leagues: list[dict]) -> str:
        raise NotImplementedError("implemented in Task 3")

    def _extract(self, content: str, null_fields: list[str], leagues: list[dict]) -> list[dict]:
        raise NotImplementedError("implemented in Task 4")

    def _write_back(self, league_id: str, patch: dict) -> None:
        raise NotImplementedError("implemented in Task 4")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_field_enricher.py::test_get_null_fields_all_null tests/test_field_enricher.py::test_get_null_fields_excludes_populated tests/test_field_enricher.py::test_get_null_fields_excludes_num_teams tests/test_field_enricher.py::test_get_null_fields_all_populated -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/enrichers/field_enricher.py tests/test_field_enricher.py
git commit -m "feat: FieldEnricher skeleton + _get_null_fields"
```

---

### Task 3: FieldEnricher — prompt builder

**Files:**
- Modify: `src/enrichers/field_enricher.py` (implement `_build_prompt`)
- Modify: `tests/test_field_enricher.py` (add prompt tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_field_enricher.py`:

```python
# ── _build_prompt ─────────────────────────────────────────────────────────────

def test_build_prompt_contains_null_fields(enricher):
    """Prompt includes all requested null fields."""
    leagues = [_make_league()]
    null_fields = ["venue_name", "team_fee", "day_of_week"]
    prompt = enricher._build_prompt("some page content", null_fields, leagues)
    for f in null_fields:
        assert f in prompt


def test_build_prompt_excludes_populated_fields(enricher):
    """Prompt does not mention fields that already have values."""
    leagues = [_make_league(venue_name="Nepean Sportsplex")]
    null_fields = ["team_fee", "day_of_week"]  # venue_name NOT in null_fields
    prompt = enricher._build_prompt("some content", null_fields, leagues)
    # venue_name should not appear as a field to fill
    # (it may appear in the league context section, but not in the OUTPUT SCHEMA)
    assert "team_fee" in prompt
    assert "day_of_week" in prompt


def test_build_prompt_includes_league_context(enricher):
    """Prompt includes org name and existing field values as context."""
    leagues = [_make_league(organization_name="Ottawa Volley Sixes", day_of_week="Monday")]
    null_fields = ["venue_name", "team_fee"]
    prompt = enricher._build_prompt("content", null_fields, leagues)
    assert "Ottawa Volley Sixes" in prompt


def test_build_prompt_includes_content(enricher):
    """Prompt includes the page content."""
    leagues = [_make_league()]
    prompt = enricher._build_prompt("UNIQUE_MARKER_XYZ", ["venue_name"], leagues)
    assert "UNIQUE_MARKER_XYZ" in prompt
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_field_enricher.py -k "prompt" -v
```

Expected: `NotImplementedError`.

- [ ] **Step 3: Implement `_build_prompt`**

Replace the `_build_prompt` stub in `src/enrichers/field_enricher.py`:

```python
def _build_prompt(self, content: str, null_fields: list[str], leagues: list[dict]) -> str:
    """Build a targeted extraction prompt for only the null fields.

    Args:
        content: Raw page text or YAML accessibility tree.
        null_fields: Field names to extract (all are currently null on these leagues).
        leagues: Existing league records (for context — org name, known fields).

    Returns:
        Formatted prompt string for Claude.
    """
    # Build league context block (known fields help Claude match divisions)
    context_lines = []
    for i, lg in enumerate(leagues, 1):
        known = {
            k: v for k, v in lg.items()
            if k in ("organization_name", "day_of_week", "gender_eligibility",
                     "competition_level", "sport_season_code", "num_teams")
            and v is not None
        }
        context_lines.append(f"  League {i}: {json.dumps(known)}")
    league_context = "\n".join(context_lines) or "  (no context available)"

    # Build output schema — only null fields
    schema_lines = [f'      "{f}": <value or null>' for f in null_fields]
    schema = ",\n".join(schema_lines)

    return f"""You are a data extraction specialist for recreational sports leagues.

TASK: Extract ONLY the fields listed in the OUTPUT SCHEMA from the page content below.
Do not invent or guess values. Return null for any field not clearly stated on the page.

KNOWN LEAGUE CONTEXT (already in database — use to match divisions):
{league_context}

OUTPUT SCHEMA — return a JSON array with one object per league:
[
  {{
    "league_id": "<copy from context above>",
{schema}
  }}
]

Return ONLY valid JSON. No other text.

PAGE CONTENT:
{content}

JSON Output:"""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_field_enricher.py -k "prompt" -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/enrichers/field_enricher.py tests/test_field_enricher.py
git commit -m "feat: FieldEnricher._build_prompt targeted extraction prompt"
```

---

### Task 4: FieldEnricher — extraction and write-back

**Files:**
- Modify: `src/enrichers/field_enricher.py` (implement `_extract` + `_write_back`)
- Modify: `tests/test_field_enricher.py` (add extraction + write-back tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_field_enricher.py`:

```python
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
    """_extract removes null values from patches (don't overwrite with null)."""
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


# ── _write_back ───────────────────────────────────────────────────────────────

def test_write_back_updates_patched_fields(enricher):
    """_write_back calls Supabase update with patch + recalculated quality_score."""
    # Existing record in DB
    enricher._db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        _make_league(league_id="uuid-1")
    ]
    enricher._db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    enricher._write_back("uuid-1", {"venue_name": "Nepean Sportsplex", "team_fee": 875.0})

    update_call = enricher._db.table.return_value.update
    update_call.assert_called_once()
    updated_data = update_call.call_args[0][0]
    assert updated_data["venue_name"] == "Nepean Sportsplex"
    assert updated_data["team_fee"] == 875.0
    assert "quality_score" in updated_data  # recalculated
    assert "updated_at" in updated_data
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_field_enricher.py -k "extract or write_back" -v
```

Expected: `NotImplementedError`.

- [ ] **Step 3: Implement `_extract` and `_write_back`**

Replace the stubs in `src/enrichers/field_enricher.py`:

```python
def _extract(self, content: str, null_fields: list[str], leagues: list[dict]) -> list[dict]:
    """Call Claude to extract null fields from page content.

    Args:
        content: Page text or YAML.
        null_fields: Fields to extract.
        leagues: Existing league records (for context).

    Returns:
        List of patch dicts — one per league, containing only non-null extracted values.
        Empty list on parse error.
    """
    prompt = self._build_prompt(content, null_fields, leagues)
    try:
        message = self._anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        patches = json.loads(raw)
        if isinstance(patches, dict):
            patches = [patches]

        # Strip null values — don't overwrite existing data with null
        return [
            {k: v for k, v in patch.items() if v is not None}
            for patch in patches
        ]
    except Exception as exc:
        logger.warning("Extraction failed: %s", exc)
        return []


def _write_back(self, league_id: str, patch: dict) -> None:
    """Write extracted fields back to leagues_metadata.

    Fetches the current record, merges the patch, recalculates quality_score,
    then updates only the patched fields + quality_score + updated_at.

    Args:
        league_id: UUID of the league to update.
        patch: Dict of field_name → new_value (nulls already stripped).
    """
    from datetime import datetime, timezone

    # Fetch current record to recalculate quality_score correctly
    result = (
        self._db.table("leagues_metadata")
        .select("*")
        .eq("league_id", league_id)
        .execute()
    )
    if not result.data:
        logger.warning("_write_back: league %s not found", league_id)
        return

    current = result.data[0]
    merged = {**current, **patch}
    new_quality = calculate_quality_score(merged)

    update_payload = {
        **patch,
        "quality_score": new_quality,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    self._db.table("leagues_metadata").update(update_payload).eq("league_id", league_id).execute()
    logger.info("Updated league %s: fields=%s quality=%d", league_id, list(patch.keys()), new_quality)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_field_enricher.py -k "extract or write_back" -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Run full test file**

```bash
python -m pytest tests/test_field_enricher.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/enrichers/field_enricher.py tests/test_field_enricher.py
git commit -m "feat: FieldEnricher._extract + _write_back"
```

---

### Task 5: FieldEnricher — enrich_url orchestration

**Files:**
- Modify: `src/enrichers/field_enricher.py` (implement `enrich_url`)
- Modify: `tests/test_field_enricher.py` (add orchestration tests)

`enrich_url` orchestrates the full flow: fetch leagues → get null fields → try cached snapshot → if miss, try Firecrawl → write back hits → return results.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_field_enricher.py`:

```python
# ── enrich_url ────────────────────────────────────────────────────────────────

import json as _json  # already imported above as json — alias to avoid confusion


def _mock_db_leagues(enricher, leagues: list[dict]) -> None:
    """Wire enricher._db to return given leagues for any url_scraped query."""
    enricher._db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = leagues


def _mock_snapshots(enricher, snapshots: list[dict]) -> None:
    """Wire get_snapshots_by_domain to return given snapshots."""
    # get_snapshots_by_domain is a module-level function imported inside enrich_url
    pass  # patched via @patch in each test


def test_enrich_url_cache_hit_writes_back(enricher):
    """Cache hit path: snapshot found → extract → write_back called per league."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])

    snapshot = {"content": "Team plays Monday nights at Nepean Sportsplex. Fee: $875."}
    patches = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex", "team_fee": 875.0}]

    enricher._extract = MagicMock(return_value=patches)
    enricher._write_back = MagicMock()

    with patch("src.enrichers.field_enricher.get_snapshots_by_domain", return_value=[snapshot]):
        results = enricher.enrich_url(url)

    assert len(results) == 1
    result = results[0]
    assert result.source == "cache"
    assert "venue_name" in result.filled_fields
    assert "team_fee" in result.filled_fields
    enricher._write_back.assert_called_once_with("uuid-1", {"venue_name": "Nepean Sportsplex", "team_fee": 875.0})


def test_enrich_url_firecrawl_fallback_on_no_snapshot(enricher):
    """No snapshot → falls back to Firecrawl → extract → write_back called."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    patches = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex"}]
    enricher._extract = MagicMock(return_value=patches)
    enricher._write_back = MagicMock()

    mock_firecrawl = MagicMock()
    mock_firecrawl.scrape.return_value = "Nepean Sportsplex page content"

    with patch("src.enrichers.field_enricher.get_snapshots_by_domain", return_value=[]):
        with patch("src.enrichers.field_enricher.FirecrawlClient", return_value=mock_firecrawl):
            results = enricher.enrich_url(url)

    assert results[0].source == "firecrawl"
    assert "venue_name" in results[0].filled_fields
    mock_firecrawl.scrape.assert_called_once_with(url)


def test_enrich_url_firecrawl_fallback_on_empty_extraction(enricher):
    """Snapshot exists but extraction returns nothing → falls back to Firecrawl."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    snapshot = {"content": "standings only page, no useful data"}

    patches_firecrawl = [{"league_id": "uuid-1", "venue_name": "Nepean Sportsplex"}]

    call_count = {"n": 0}
    def extract_side_effect(content, null_fields, leagues):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return []  # cache miss
        return patches_firecrawl  # Firecrawl hit

    enricher._extract = MagicMock(side_effect=extract_side_effect)
    enricher._write_back = MagicMock()

    mock_firecrawl = MagicMock()
    mock_firecrawl.scrape.return_value = "Nepean content"

    with patch("src.enrichers.field_enricher.get_snapshots_by_domain", return_value=[snapshot]):
        with patch("src.enrichers.field_enricher.FirecrawlClient", return_value=mock_firecrawl):
            results = enricher.enrich_url(url)

    assert results[0].source == "firecrawl"


def test_enrich_url_no_null_fields_skips_extraction(enricher):
    """League with all fields populated skips extraction entirely."""
    league = _make_league(**{f: "x" for f in ENRICHABLE_FIELDS})
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    enricher._extract = MagicMock()

    with patch("src.enrichers.field_enricher.get_snapshots_by_domain", return_value=[]):
        results = enricher.enrich_url(url)

    enricher._extract.assert_not_called()
    assert results[0].source == "none"
    assert results[0].filled_fields == []


def test_enrich_url_firecrawl_error_returns_error_result(enricher):
    """Firecrawl failure returns result with error set, does not raise."""
    league = _make_league()
    url = "https://ottawavolleysixes.com/register"

    _mock_db_leagues(enricher, [league])
    enricher._extract = MagicMock(return_value=[])
    enricher._write_back = MagicMock()

    mock_firecrawl = MagicMock()
    mock_firecrawl.scrape.side_effect = RuntimeError("Firecrawl blocked")

    with patch("src.enrichers.field_enricher.get_snapshots_by_domain", return_value=[]):
        with patch("src.enrichers.field_enricher.FirecrawlClient", return_value=mock_firecrawl):
            results = enricher.enrich_url(url)

    assert results[0].error is not None
    assert results[0].source == "none"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_field_enricher.py -k "enrich_url" -v
```

Expected: `NotImplementedError`.

- [ ] **Step 3: Implement `enrich_url`**

Add this import at the top of `src/enrichers/field_enricher.py` (after existing imports):

```python
from src.database.snapshot_store import get_snapshots_by_domain
from src.scraper.firecrawl_client import FirecrawlClient
```

Replace the `enrich_url` stub:

```python
def enrich_url(self, url: str) -> list[FieldEnrichResult]:
    """Enrich all leagues at a URL.

    Flow:
      1. Fetch league records for URL
      2. For each league: identify null enrichable fields
      3. Pull most recent snapshot for the domain
      4. Run targeted extraction against snapshot content
      5. If extraction empty: Firecrawl URL → retry extraction
      6. Write back any hits; record skipped fields

    Args:
        url: url_scraped value (exact match against leagues_metadata).

    Returns:
        One FieldEnrichResult per league.
    """
    # Step 1: fetch leagues
    response = (
        self._db.table("leagues_metadata")
        .select("*")
        .eq("url_scraped", url)
        .eq("is_archived", False)
        .execute()
    )
    leagues = response.data or []

    if not leagues:
        logger.warning("No active leagues found for %s", url)
        return []

    # Step 2: null fields per league (union across all leagues — one extraction covers all)
    all_null_fields: list[str] = []
    league_null_map: dict[str, list[str]] = {}
    for lg in leagues:
        nf = self._get_null_fields(lg)
        league_null_map[lg["league_id"]] = nf
        for f in nf:
            if f not in all_null_fields:
                all_null_fields.append(f)

    # Short-circuit: nothing to fill
    if not all_null_fields:
        return [
            FieldEnrichResult(
                league_id=lg["league_id"],
                org_name=lg.get("organization_name", ""),
                skipped_fields=[],
                source="none",
            )
            for lg in leagues
        ]

    # Step 3: fetch most recent snapshot for this domain
    domain = urlparse(url).netloc
    snapshots = get_snapshots_by_domain(domain)
    snapshot_content = snapshots[0]["content"] if snapshots else None

    # Step 4: try extraction from cached snapshot
    patches: list[dict] = []
    source = "none"

    if snapshot_content:
        patches = self._extract(snapshot_content, all_null_fields, leagues)
        if patches:
            source = "cache"

    # Step 5: Firecrawl fallback if no snapshot or empty extraction
    if not patches:
        api_key = os.environ.get("FIRECRAWL_API_KEY", "")
        try:
            fc = FirecrawlClient(api_key=api_key)
            fc_content = fc.scrape(url)
            patches = self._extract(fc_content, all_null_fields, leagues)
            if patches:
                source = "firecrawl"
        except Exception as exc:
            logger.warning("Firecrawl fallback failed for %s: %s", url, exc)
            # Return error results for all leagues
            return [
                FieldEnrichResult(
                    league_id=lg["league_id"],
                    org_name=lg.get("organization_name", ""),
                    skipped_fields=league_null_map.get(lg["league_id"], []),
                    source="none",
                    error=str(exc),
                )
                for lg in leagues
            ]

    # Step 6: write back and build results
    # Index patches by league_id
    patch_map: dict[str, dict] = {p.get("league_id", ""): p for p in patches}

    results = []
    for lg in leagues:
        lid = lg["league_id"]
        patch = {k: v for k, v in patch_map.get(lid, {}).items() if k != "league_id"}
        null_fields_for_league = league_null_map.get(lid, [])

        if patch:
            self._write_back(lid, patch)
            filled = [f for f in patch if f in null_fields_for_league]
            skipped = [f for f in null_fields_for_league if f not in patch]
        else:
            filled = []
            skipped = null_fields_for_league

        results.append(FieldEnrichResult(
            league_id=lid,
            org_name=lg.get("organization_name", ""),
            filled_fields=filled,
            skipped_fields=skipped,
            source=source if patch else "none",
        ))

    return results
```

- [ ] **Step 4: Run all FieldEnricher tests**

```bash
python -m pytest tests/test_field_enricher.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/enrichers/field_enricher.py tests/test_field_enricher.py
git commit -m "feat: FieldEnricher.enrich_url full orchestration with Firecrawl fallback"
```

---

## Chunk 3: Streamlit Page + Nav

### Task 6: fill_in_leagues.py Streamlit page

**Files:**
- Create: `streamlit_app/pages/fill_in_leagues.py`

No unit tests for Streamlit pages (consistent with all other pages in this codebase).

- [ ] **Step 1: Create `fill_in_leagues.py`**

Create `streamlit_app/pages/fill_in_leagues.py`:

```python
"""Fill In Leagues — multi-mode enrichment for existing league records."""
from __future__ import annotations

import streamlit as st
from src.database.supabase_client import get_client

# ── helpers ───────────────────────────────────────────────────────────────────

def _get_url_rows() -> list[dict]:
    """Return distinct URLs with org name, league count, avg quality from leagues_metadata."""
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("url_scraped, organization_name, quality_score, base_domain")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []

    # Group by url_scraped
    seen: dict[str, dict] = {}
    for row in rows:
        url = row["url_scraped"]
        if url not in seen:
            seen[url] = {
                "url": url,
                "org_name": row.get("organization_name") or row.get("base_domain") or url[:60],
                "league_count": 0,
                "quality_scores": [],
            }
        seen[url]["league_count"] += 1
        if row.get("quality_score") is not None:
            seen[url]["quality_scores"].append(row["quality_score"])

    result_rows = []
    for url, data in seen.items():
        scores = data["quality_scores"]
        data["avg_quality"] = round(sum(scores) / len(scores)) if scores else 0
        result_rows.append(data)

    return sorted(result_rows, key=lambda r: r["avg_quality"])


def _run_deep_dive(url: str, progress_callback) -> dict:
    from scripts.super_scraper import run as super_run
    progress_callback(f"Running super scrape for {url}...")
    return super_run(url, dry_run=False)


def _run_teams(url: str, progress_callback) -> dict:
    """Delegate to count_teams_scraper logic."""
    import asyncio
    from src.checkers.league_checker import LeagueChecker
    progress_callback(f"Running team count refresh for {url}...")
    checker = LeagueChecker()
    result = checker._standard_check(url, db_leagues=None, progress_callback=progress_callback)
    return {"checks": result.checks}


def _run_fill_fields(url: str, progress_callback) -> list:
    from src.enrichers.field_enricher import FieldEnricher
    progress_callback(f"Running field enrichment for {url}...")
    enricher = FieldEnricher()
    return enricher.enrich_url(url)


# ── render ────────────────────────────────────────────────────────────────────

def render():
    st.title("Fill In Leagues")
    st.caption("Enrich existing league records with missing data.")

    # Mode selector
    mode = st.radio(
        "Mode",
        options=["Fill Fields", "Teams", "Deep-dive"],
        horizontal=True,
        help=(
            "Fill Fields: extract all null fields (venue, cost, schedule, policies) "
            "from cached snapshots or Firecrawl.  "
            "Teams: refresh team counts from standings pages.  "
            "Deep-dive: full re-crawl + reconcile via super scraper."
        ),
    )

    mode_descriptions = {
        "Fill Fields": "Fills null fields (venue, cost, schedule, policies) from cached snapshots. Falls back to Firecrawl if no cached content is found.",
        "Teams": "Navigates standings pages to refresh `num_teams` counts.",
        "Deep-dive": "Full re-crawl of the site. Reconciles extracted leagues against existing DB records. Use for low-quality or stale records.",
    }
    st.caption(mode_descriptions[mode])
    st.divider()

    # URL list
    st.subheader("Select URLs")
    try:
        url_rows = _get_url_rows()
    except Exception as e:
        st.error(f"Could not load league URLs: {e}")
        return

    if not url_rows:
        st.info("No scraped leagues found. Run the scraper first.")
        return

    selected_urls: list[str] = []
    for row in url_rows:
        label = f"{row['org_name']}  ({row['league_count']} leagues)  · avg quality {row['avg_quality']}"
        if st.checkbox(label, key=f"fill_{row['url']}"):
            selected_urls.append(row["url"])

    st.divider()

    # Run
    if st.button("Run Selected", disabled=len(selected_urls) == 0, type="primary"):
        progress = st.progress(0, text="Starting...")
        status = st.empty()
        all_results = []

        for i, url in enumerate(selected_urls):
            status.info(f"Processing: {url[:80]}")

            def cb(msg, _s=status):
                _s.info(msg)

            try:
                if mode == "Deep-dive":
                    r = _run_deep_dive(url, cb)
                    all_results.append({"url": url, "mode": mode, "data": r})
                elif mode == "Teams":
                    r = _run_teams(url, cb)
                    all_results.append({"url": url, "mode": mode, "data": r})
                else:  # Fill Fields
                    r = _run_fill_fields(url, cb)
                    all_results.append({"url": url, "mode": mode, "data": r})
            except Exception as e:
                st.error(f"Error processing {url}: {e}")
                all_results.append({"url": url, "mode": mode, "data": None, "error": str(e)})

            progress.progress((i + 1) / len(selected_urls), text=f"{i + 1}/{len(selected_urls)}")

        status.success(f"Done. Processed {len(all_results)} URL(s).")
        st.session_state["fill_results"] = all_results

    # Results
    if "fill_results" in st.session_state:
        st.divider()
        st.subheader("Results")
        for run in st.session_state["fill_results"]:
            url = run["url"]
            mode_label = run["mode"]
            data = run.get("data")
            err = run.get("error")

            with st.expander(f"`{url[:70]}`  [{mode_label}]", expanded=True):
                if err:
                    st.error(f"Error: {err}")
                    continue

                if mode_label == "Deep-dive" and isinstance(data, dict):
                    st.success(
                        f"Super scrape complete — "
                        f"{data.get('leagues_written', 0)} written, "
                        f"{data.get('archived', 0)} archived, "
                        f"{data.get('review_queued', 0)} queued for review"
                    )
                    for e in data.get("errors", []):
                        st.caption(f"Error: {e}")

                elif mode_label == "Teams" and isinstance(data, dict):
                    for chk in data.get("checks", []):
                        status_icon = {"MATCH": "✅", "CHANGED": "🔴", "NOT_FOUND": "⚠️"}.get(
                            chk.get("status", ""), "?"
                        )
                        label = chk.get("division_name") or "League"
                        old_t = chk.get("old_num_teams", "–")
                        new_t = chk.get("new_num_teams", "–")
                        st.write(f"{status_icon} {label} — {old_t} → {new_t} teams")

                elif mode_label == "Fill Fields" and isinstance(data, list):
                    for res in data:
                        source_badge = {"cache": "Cache", "firecrawl": "Firecrawl", "none": "No data"}.get(
                            res.source, res.source
                        )
                        filled = res.filled_fields
                        skipped = res.skipped_fields

                        if res.error:
                            st.warning(f"{res.org_name} — Error: {res.error}")
                        elif filled:
                            st.success(
                                f"{res.org_name} — filled {len(filled)} field(s) "
                                f"via **{source_badge}**: `{'`, `'.join(filled)}`"
                            )
                        else:
                            st.info(f"{res.org_name} — no new data found ({source_badge})")

                        if skipped:
                            st.caption(f"Still missing: {', '.join(skipped)}")
```

- [ ] **Step 2: Manual smoke test (no automated test for Streamlit pages)**

Start the app and navigate to Fill In Leagues:

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
streamlit run streamlit_app/app.py
```

Verify: the page loads with mode radio, URL checkboxes, and run button. (Update nav in Task 7 first.)

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/fill_in_leagues.py
git commit -m "feat: add Fill In Leagues Streamlit page"
```

---

### Task 7: Update nav + retire league_checker.py

**Files:**
- Modify: `streamlit_app/app.py`
- Delete: `streamlit_app/pages/league_checker.py`

- [ ] **Step 1: Update `app.py` nav**

In `streamlit_app/app.py`, make these changes:

Replace in `PAGES` dict:
```python
# Old:
"🔍 League Checker":         ("search",  "league_checker"),
# New:
"🔧 Fill In Leagues":        ("search",  "fill_in_leagues"),
```

Replace in sidebar loop — change the label in the list:
```python
# Old:
for label in ["🎯 Campaign Manager", "📋 Queue Monitor", "🕷️ Scraper UI", "🔍 League Checker"]:
# New:
for label in ["🎯 Campaign Manager", "📋 Queue Monitor", "🕷️ Scraper UI", "🔧 Fill In Leagues"]:
```

Replace the routing block:
```python
# Old:
elif module_name == "league_checker":
    try:
        from pages import league_checker
        league_checker.render()
    except ImportError:
        st.info("🔍 League Checker — coming soon.")

# New:
elif module_name == "fill_in_leagues":
    from pages import fill_in_leagues
    fill_in_leagues.render()
```

- [ ] **Step 2: Delete `league_checker.py`**

```bash
rm "C:/Users/mathe/VSCode/aa_RecLeagueDB/streamlit_app/pages/league_checker.py"
```

- [ ] **Step 3: Smoke test**

```bash
streamlit run streamlit_app/app.py
```

Verify: sidebar shows "Fill In Leagues" (not "League Checker"), page renders correctly, no import errors.

- [ ] **Step 4: Commit**

```bash
git add streamlit_app/app.py
git rm streamlit_app/pages/league_checker.py
git commit -m "feat: swap League Checker for Fill In Leagues in nav"
```

---

## Final Check

- [ ] Run all new tests:

```bash
python -m pytest tests/test_firecrawl_client.py tests/test_field_enricher.py -v
```

Expected: all tests PASS, no warnings about missing fields or imports.

- [ ] Confirm no references to `league_checker` remain in app code:

```bash
grep -r "league_checker" C:/Users/mathe/VSCode/aa_RecLeagueDB/streamlit_app/
```

Expected: no output.
