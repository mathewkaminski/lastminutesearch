# Smart Crawler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the MCP agent as the primary scraping pipeline with a deterministic Playwright BFS crawler that uses Claude Haiku to classify pages, then GPT-4o to extract league data from confirmed pages.

**Architecture:** Three phases — (1) headless Playwright fetches pages as YAML accessibility trees using the existing `playwright_yaml_fetcher.py`, (2) Claude Haiku classifies each page as YES/NO for league data, (3) GPT-4o extracts structured league records from confirmed pages using the existing `yaml_extractor.py`. Navigation follows all primary keyword links first, then secondary, then goes up to 4 layers deep.

**Tech Stack:** Python 3.10+, Playwright (sync), Anthropic SDK (Claude Haiku), OpenAI SDK (GPT-4o), pytest + unittest.mock

---

## Context You Need

- Design doc: `docs/plans/2026-02-27-smart-crawler-design.md`
- Link scoring lives in: `src/scraper/yaml_link_parser.py` — `score_links()` gives score=100 for primary keywords (register, schedule, standings), score=50 for secondary (divisions, rules, teams)
- Page fetching: `src/scraper/playwright_yaml_fetcher.py` — `fetch_page_as_yaml(url) -> (yaml_str, metadata)`
- Extraction: `src/extractors/yaml_extractor.py` — `extract_league_data_from_yaml(yaml_str, url) -> list[dict]`
- Each extracted league dict has `identifying_fields_pct` (0–100) and `completeness_status` (COMPLETE/ACCEPTABLE/PARTIAL/FAILED)
- DB write: `src/database/writer.py` — `insert_league(data) -> (league_id, is_new)`
- **Write threshold: only write leagues where `identifying_fields_pct >= 50`**

---

## Task 1: League Classifier

**Files:**
- Create: `src/scraper/league_classifier.py`
- Create: `tests/test_league_classifier.py`

### Step 1: Write the failing tests

```python
# tests/test_league_classifier.py
import pytest
from unittest.mock import MagicMock, patch


def test_has_league_data_returns_true_when_api_says_yes():
    """Classifier returns True when Haiku responds YES."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="YES")]

    with patch("src.scraper.league_classifier.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.scraper.league_classifier import has_league_data
        result = has_league_data("- role: grid\n  name: Register Now")

    assert result is True


def test_has_league_data_returns_false_when_api_says_no():
    """Classifier returns False when Haiku responds NO."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="NO")]

    with patch("src.scraper.league_classifier.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.scraper.league_classifier import has_league_data
        result = has_league_data("- role: text\n  name: Contact Us")

    assert result is False


def test_has_league_data_returns_false_on_api_error():
    """Classifier fails safe — returns False if API call raises."""
    with patch("src.scraper.league_classifier.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("network error")
        mock_client_cls.return_value = mock_client

        from src.scraper.league_classifier import has_league_data
        result = has_league_data("some yaml content")

    assert result is False


def test_has_league_data_truncates_large_input():
    """Classifier truncates YAML to MAX_CLASSIFIER_CHARS before sending."""
    from src.scraper.league_classifier import MAX_CLASSIFIER_CHARS

    captured = {}

    def fake_create(**kwargs):
        captured["content"] = kwargs["messages"][0]["content"]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="NO")]
        return mock_response

    with patch("src.scraper.league_classifier.anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = fake_create
        mock_client_cls.return_value = mock_client

        from src.scraper.league_classifier import has_league_data
        big_yaml = "x" * (MAX_CLASSIFIER_CHARS + 5000)
        has_league_data(big_yaml)

    assert len(captured["content"]) <= MAX_CLASSIFIER_CHARS + 500  # prompt overhead
```

### Step 2: Run tests to verify they fail

```bash
cd C:\Users\mathe\VSCode\aa_RecLeagueDB
pytest tests/test_league_classifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.scraper.league_classifier'`

### Step 3: Implement `league_classifier.py`

```python
# src/scraper/league_classifier.py
"""Lightweight Claude Haiku classifier: does this page have league data?"""

import logging
import anthropic

logger = logging.getLogger(__name__)

# Truncate YAML to this many chars before sending (keeps Haiku cost near-zero)
MAX_CLASSIFIER_CHARS = 8000

_PROMPT = """\
You are reviewing a page's accessibility tree from a sports league website.
Does this page contain sports league listings with registration info, fees, schedules, or standings?

Answer with ONLY "YES" or "NO". No explanation.

Page content:
{yaml_snippet}"""


def has_league_data(yaml_content: str) -> bool:
    """Return True if the page likely contains league listing data.

    Uses Claude Haiku for cheap, fast YES/NO classification.
    Fails safe — returns False on any API error.

    Args:
        yaml_content: YAML accessibility tree string

    Returns:
        True if page appears to contain league listings
    """
    snippet = yaml_content[:MAX_CLASSIFIER_CHARS]
    prompt = _PROMPT.format(yaml_snippet=snippet)

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text.strip().upper()
        result = answer.startswith("YES")
        logger.debug(f"Classifier → {answer!r} ({result})")
        return result
    except Exception as e:
        logger.warning(f"Classifier failed, defaulting False: {e}")
        return False
```

### Step 4: Run tests to verify they pass

```bash
pytest tests/test_league_classifier.py -v
```

Expected: `4 passed`

### Step 5: Commit

```bash
git add src/scraper/league_classifier.py tests/test_league_classifier.py
git commit -m "feat: add Haiku league page classifier"
```

---

## Task 2: Smart Crawler

**Files:**
- Create: `src/scraper/smart_crawler.py`
- Create: `tests/test_smart_crawler.py`

### Step 1: Write the failing tests

```python
# tests/test_smart_crawler.py
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_yaml(links: list[tuple[str, str]]) -> str:
    """Build a minimal YAML snippet that yaml_link_parser can extract links from."""
    lines = ["- role: nav", "  children:"]
    for url, text in links:
        lines += [
            f"  - role: a",
            f"    name: {text}",
            f"    url: {url}",
        ]
    return "\n".join(lines)


NO_LEAGUE_YAML = _make_yaml([])
PRIMARY_LEAGUE_YAML = "- role: grid\n  name: Upcoming Leagues\n- role: row\n  name: Monday Volleyball"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_crawl_returns_home_page_when_home_has_leagues():
    """If home page itself has leagues, it should be returned."""
    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml") as mock_fetch,
        patch("src.scraper.smart_crawler.has_league_data") as mock_classify,
    ):
        mock_fetch.return_value = (PRIMARY_LEAGUE_YAML, {})
        mock_classify.return_value = True

        from src.scraper.smart_crawler import crawl
        result = crawl("https://example.com")

    assert len(result) == 1
    assert result[0][0] == "https://example.com"


def test_crawl_visits_all_primary_links_regardless_of_early_yes():
    """Step A must visit ALL primary links even after the first YES."""
    home_yaml = _make_yaml([
        ("/register", "Register"),
        ("/schedule", "Schedule"),
        ("/standings", "Standings"),
    ])

    visited = []

    def fake_fetch(url, **kwargs):
        visited.append(url)
        return (NO_LEAGUE_YAML, {})

    def fake_classify(yaml):
        # Return True for /register page (first primary), False for rest
        return "/register" in visited and visited[-1] == "https://example.com/register"

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.has_league_data", side_effect=fake_classify),
    ):
        from src.scraper import smart_crawler
        import importlib; importlib.reload(smart_crawler)
        result = smart_crawler.crawl("https://example.com")

    # All three primary pages must have been visited
    assert "https://example.com/register" in visited
    assert "https://example.com/schedule" in visited
    assert "https://example.com/standings" in visited


def test_crawl_falls_through_to_secondary_when_primary_finds_nothing():
    """If Step A finds no leagues, Step B should visit secondary links."""
    home_yaml = _make_yaml([
        ("/register", "Register"),     # primary
        ("/divisions", "Divisions"),   # secondary
    ])

    visited = []

    def fake_fetch(url, **kwargs):
        visited.append(url)
        # /divisions page has leagues
        if url == "https://example.com/divisions":
            return (PRIMARY_LEAGUE_YAML, {})
        return (NO_LEAGUE_YAML, {})

    def fake_classify(yaml):
        return yaml == PRIMARY_LEAGUE_YAML

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.has_league_data", side_effect=fake_classify),
    ):
        from src.scraper import smart_crawler
        import importlib; importlib.reload(smart_crawler)
        result = smart_crawler.crawl("https://example.com")

    assert any(url == "https://example.com/divisions" for url, _ in result)


def test_crawl_does_not_visit_same_url_twice():
    """Deduplication: same URL appearing in multiple link lists is only fetched once."""
    home_yaml = _make_yaml([
        ("/register", "Register"),
        ("/register", "Register Now"),  # duplicate
    ])

    visited = []

    def fake_fetch(url, **kwargs):
        visited.append(url)
        return (NO_LEAGUE_YAML, {})

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.has_league_data", return_value=False),
    ):
        from src.scraper import smart_crawler
        import importlib; importlib.reload(smart_crawler)
        smart_crawler.crawl("https://example.com")

    assert visited.count("https://example.com/register") == 1


def test_crawl_returns_empty_when_nothing_found_within_max_depth():
    """Returns [] when max_depth is exhausted with no leagues found."""
    # Home page has one primary link; that page has one more link, etc. — all NO.
    home_yaml = _make_yaml([("/register", "Register")])
    deep_yaml = _make_yaml([("/page2", "Teams")])

    def fake_fetch(url, **kwargs):
        if url == "https://example.com":
            return (home_yaml, {})
        return (deep_yaml, {})

    with (
        patch("src.scraper.smart_crawler.fetch_page_as_yaml", side_effect=fake_fetch),
        patch("src.scraper.smart_crawler.has_league_data", return_value=False),
    ):
        from src.scraper import smart_crawler
        import importlib; importlib.reload(smart_crawler)
        result = smart_crawler.crawl("https://example.com", max_depth=2)

    assert result == []
```

### Step 2: Run tests to verify they fail

```bash
pytest tests/test_smart_crawler.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.scraper.smart_crawler'`

### Step 3: Implement `smart_crawler.py`

```python
# src/scraper/smart_crawler.py
"""Deterministic BFS crawler: Playwright YAML + Haiku classifier.

Navigation algorithm:
  Step A — Visit ALL primary links (score >= 100) from home. No early exit.
            Collect every page that classifies as having leagues.
  Step B — If A found nothing: visit secondary links (score 50-99), stop at first YES.
  Step C — If A+B found nothing: BFS from primary pages following TOP link only,
            up to max_depth layers. Stop at first YES.
"""

import logging
import yaml as yaml_lib

from src.scraper.playwright_yaml_fetcher import fetch_page_as_yaml
from src.scraper.yaml_link_parser import parse_yaml_links, score_links
from src.scraper.league_classifier import has_league_data

logger = logging.getLogger(__name__)

MAX_DEPTH = 4


def crawl(start_url: str, max_depth: int = MAX_DEPTH) -> list[tuple[str, str]]:
    """Crawl a sports league website, return pages confirmed to have league data.

    Args:
        start_url: Home page URL
        max_depth: Maximum BFS depth from home (default 4)

    Returns:
        List of (url, yaml_content) for pages where classifier returned True
    """
    visited: set[str] = set()

    # --- Layer 0: Home page ---
    logger.info(f"Fetching home: {start_url}")
    home_yaml, _ = fetch_page_as_yaml(start_url)
    visited.add(start_url)

    home_tree = yaml_lib.safe_load(home_yaml)
    all_home_links = parse_yaml_links(home_tree, start_url)
    scored_home = score_links(all_home_links)

    # Deduplicate while preserving score-desc order
    seen: set[str] = {start_url}
    primary_links = []
    secondary_links = []
    for link in scored_home:
        if link.url in seen:
            continue
        seen.add(link.url)
        if link.score >= 100:
            primary_links.append(link)
        elif link.score >= 50:
            secondary_links.append(link)

    logger.info(
        f"Home links: {len(primary_links)} primary, {len(secondary_links)} secondary"
    )

    # --- Step A: Visit ALL primary links ---
    league_pages: list[tuple[str, str]] = []
    primary_page_store: list[tuple[str, str]] = []  # for Step C

    for link in primary_links:
        if link.url in visited:
            continue
        visited.add(link.url)
        try:
            page_yaml, _ = fetch_page_as_yaml(link.url)
            primary_page_store.append((link.url, page_yaml))
            if has_league_data(page_yaml):
                logger.info(f"[Step A] League page: {link.url}")
                league_pages.append((link.url, page_yaml))
        except Exception as e:
            logger.warning(f"[Step A] Fetch failed {link.url}: {e}")

    if league_pages:
        logger.info(f"Step A complete: {len(league_pages)} league page(s)")
        return league_pages

    # --- Step B: Secondary links (only if A found nothing) ---
    logger.info("Step A: no leagues. Trying secondary links...")
    for link in secondary_links:
        if link.url in visited:
            continue
        visited.add(link.url)
        try:
            page_yaml, _ = fetch_page_as_yaml(link.url)
            if has_league_data(page_yaml):
                logger.info(f"[Step B] League page: {link.url}")
                return [(link.url, page_yaml)]
        except Exception as e:
            logger.warning(f"[Step B] Fetch failed {link.url}: {e}")

    # --- Step C: Deeper BFS from primary pages, top link only ---
    logger.info("Step B: no leagues. Going deeper (BFS, top link per page)...")
    # frontier entries: (url, yaml_content, depth)
    frontier: list[tuple[str, str, int]] = [
        (url, yml, 2) for url, yml in primary_page_store
    ]

    while frontier:
        curr_url, curr_yaml, depth = frontier.pop(0)
        if depth > max_depth:
            continue
        try:
            curr_tree = yaml_lib.safe_load(curr_yaml)
        except Exception:
            continue

        curr_links = parse_yaml_links(curr_tree, curr_url)
        curr_scored = score_links(curr_links)
        top_candidates = [
            l for l in curr_scored if l.score >= 50 and l.url not in visited
        ][:1]

        for link in top_candidates:
            visited.add(link.url)
            try:
                page_yaml, _ = fetch_page_as_yaml(link.url)
                if has_league_data(page_yaml):
                    logger.info(f"[Step C, depth={depth}] League page: {link.url}")
                    return [(link.url, page_yaml)]
                frontier.append((link.url, page_yaml, depth + 1))
            except Exception as e:
                logger.warning(f"[Step C] Fetch failed {link.url}: {e}")

    logger.warning(f"No league pages found within depth {max_depth}")
    return []
```

### Step 4: Run tests to verify they pass

```bash
pytest tests/test_smart_crawler.py -v
```

Expected: `5 passed`

### Step 5: Commit

```bash
git add src/scraper/smart_crawler.py tests/test_smart_crawler.py
git commit -m "feat: add smart BFS crawler with primary/secondary/deep navigation"
```

---

## Task 3: CLI Script

**Files:**
- Create: `scripts/smart_scraper.py`

No dedicated unit tests for the CLI — the integration is validated by importing without error and a dry-run smoke test at the end.

### Step 1: Implement `scripts/smart_scraper.py`

```python
#!/usr/bin/env python
"""Smart scraper: deterministic BFS Playwright + Haiku classifier + GPT-4o extraction.

Replaces mcp_agent_scraper.py as the primary pipeline for most sites.

Usage:
    python scripts/smart_scraper.py --url https://www.ottawavolleysixes.com
    python scripts/smart_scraper.py --url https://... --dry-run
    python scripts/smart_scraper.py --url https://... --log-level DEBUG
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

LOG_DIR = Path(__file__).parent.parent / "logs"

# Leagues below this completeness threshold are not written to DB
MIN_COMPLETENESS_PCT = 50.0


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smart crawler: BFS Playwright + Haiku classifier + GPT-4o extraction"
    )
    parser.add_argument("--url", required=True, help="Base URL to crawl")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print results without writing to DB"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def setup_logging(log_level: str) -> None:
    from datetime import datetime
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"smart_scraper_{ts}.log"
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger(__name__).info(f"Logging to {log_file}")


def run(url: str, dry_run: bool) -> dict:
    from src.scraper.smart_crawler import crawl
    from src.extractors.yaml_extractor import extract_league_data_from_yaml
    from src.database.writer import insert_league

    logger = logging.getLogger(__name__)
    result = {
        "url": url,
        "pages_with_leagues": 0,
        "leagues_extracted": 0,
        "leagues_written": 0,
        "skipped_low_quality": 0,
        "errors": [],
    }

    # Phase 1+2: Navigate + classify
    logger.info(f"Starting smart crawl: {url}")
    league_pages = crawl(url)
    result["pages_with_leagues"] = len(league_pages)

    if not league_pages:
        result["errors"].append("No league pages found after full crawl")
        return result

    # Phase 3: Extract + write
    for page_url, yaml_content in league_pages:
        logger.info(f"Extracting leagues from: {page_url}")
        try:
            leagues = extract_league_data_from_yaml(yaml_content, page_url)
            result["leagues_extracted"] += len(leagues)
        except Exception as e:
            msg = f"Extraction failed for {page_url}: {e}"
            logger.warning(msg)
            result["errors"].append(msg)
            continue

        for league in leagues:
            pct = league.get("identifying_fields_pct", 0)
            label = (
                f"{league.get('day_of_week')} | "
                f"{(league.get('venue_name') or '')[:25]} | "
                f"{league.get('gender_eligibility')}"
            )

            if pct < MIN_COMPLETENESS_PCT:
                logger.info(f"  SKIP ({pct:.0f}%): {label}")
                result["skipped_low_quality"] += 1
                continue

            if dry_run:
                logger.info(f"  DRY-RUN ({pct:.0f}%): {label}")
                result["leagues_written"] += 1
                continue

            try:
                league_id, is_new = insert_league(league)
                status = "NEW" if is_new else "UPDATED"
                logger.info(f"  [{status}] {league_id[:8]}... ({pct:.0f}%): {label}")
                result["leagues_written"] += 1
            except Exception as e:
                msg = f"DB write failed for {label}: {e}"
                logger.warning(msg)
                result["errors"].append(msg)

    return result


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)
    logger.info(f"Smart scraper starting")
    logger.info(f"  URL:      {args.url}")
    logger.info(f"  Dry-run:  {args.dry_run}")

    result = run(args.url, args.dry_run)

    print(f"\n{'='*60}")
    print("SMART SCRAPER RESULTS")
    print(f"{'='*60}")
    print(f"Pages with leagues:   {result['pages_with_leagues']}")
    print(f"Leagues extracted:    {result['leagues_extracted']}")
    print(f"Leagues written:      {result['leagues_written']}")
    print(f"Skipped (<50%):       {result['skipped_low_quality']}")
    if result["errors"]:
        print(f"Errors: {len(result['errors'])}")
        for err in result["errors"]:
            print(f"  ERROR: {err}")

    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

### Step 2: Verify the script imports cleanly

```bash
cd C:\Users\mathe\VSCode\aa_RecLeagueDB
python -c "import scripts.smart_scraper; print('OK')"
```

Expected: `OK`

### Step 3: Run a dry-run smoke test against Ottawa Volley Sixes

```bash
python scripts/smart_scraper.py --url https://www.ottawavolleysixes.com --dry-run
```

Expected output (approximate):
```
Pages with leagues:   N   (at least 1)
Leagues extracted:    N
Leagues written:      N   (dry-run, not actually written)
Skipped (<50%):       N
```

No crashes. Any 429 rate limits are fine — the classifier uses Haiku which has a much higher rate limit than Sonnet.

### Step 4: Commit

```bash
git add scripts/smart_scraper.py
git commit -m "feat: add smart_scraper CLI (BFS Playwright + Haiku + GPT-4o)"
```

---

## Task 4: URL Logging in `count_teams_scraper.py` (quick fix)

While we're here, add URL logging to `count_teams_scraper.py` so future runs show which pages the agent visits.

**Files:**
- Modify: `scripts/count_teams_scraper.py:249`

### Step 1: Find the tool logging line

```python
# Current line ~249 in scripts/count_teams_scraper.py:
logger.info(f"  Tool: {tool_name}({list(tool_input.keys())})")
```

### Step 2: Replace with URL-aware logging

```python
# Replace the single logger.info line with:
if tool_name == "browser_navigate":
    logger.info(f"  Tool: browser_navigate → {tool_input.get('url', '?')}")
else:
    logger.info(f"  Tool: {tool_name}({list(tool_input.keys())})")
```

### Step 3: Commit

```bash
git add scripts/count_teams_scraper.py
git commit -m "fix: log actual URLs in count_teams_scraper browser_navigate calls"
```

---

## Final Verification

Run all tests to confirm nothing broke:

```bash
pytest tests/ -v --tb=short
```

Expected: all existing tests pass plus the 9 new ones (4 classifier + 5 crawler).
