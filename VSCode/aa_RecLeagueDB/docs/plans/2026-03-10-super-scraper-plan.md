# Super Scraper + Merge Tools — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a two-pass "super scraper" triggered by the League Checker for low-quality records,
plus rename the Merge Tool into two scoped tools (URL Merge, League Merge).

**Architecture:** Quality thresholds live in a single config file. The super scraper reuses
existing `crawl()` and `PlaywrightNavigator` with aggressive settings, adds a reconciliation
layer that auto-archives thin contradictions and queues borderline ones, and finishes with
within-URL auto-consolidation. Merge tools share the existing `_merge()` / `archive_league()`
backend.

**Tech Stack:** Python 3.10+, Playwright (sync + async), OpenAI GPT-4o, Claude Haiku,
Supabase/PostgreSQL, Streamlit

---

## Task 1: Quality Thresholds Config

**Files:**
- Create: `src/config/quality_thresholds.py`
- Test: `tests/test_quality_thresholds.py`

**Step 1: Write the failing test**

```python
# tests/test_quality_thresholds.py
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
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_quality_thresholds.py -v
```
Expected: ImportError — module doesn't exist yet.

**Step 3: Implement**

```python
# src/config/quality_thresholds.py
from enum import Enum

AUTO_REPLACE_THRESHOLD = 60   # Below this: super scrape auto-archives if contradicted
DEEP_SCRAPE_THRESHOLD = 75    # Below this: League Checker triggers super scrape

class QualityBand(str, Enum):
    THIN       = "THIN"        # 0–59
    BORDERLINE = "BORDERLINE"  # 60–74
    ACCEPTABLE = "ACCEPTABLE"  # 75–89
    SUBSTANTIAL = "SUBSTANTIAL" # 90+

def get_quality_band(score: int | None) -> QualityBand:
    if score is None or score < AUTO_REPLACE_THRESHOLD:
        return QualityBand.THIN
    if score < DEEP_SCRAPE_THRESHOLD:
        return QualityBand.BORDERLINE
    if score < 90:
        return QualityBand.ACCEPTABLE
    return QualityBand.SUBSTANTIAL
```

**Step 4: Run test to verify it passes**

```
pytest tests/test_quality_thresholds.py -v
```
Expected: 6 tests PASS.

**Step 5: Commit**

```bash
git add src/config/quality_thresholds.py tests/test_quality_thresholds.py
git commit -m "feat: add quality score bands config (Thin/Borderline/Acceptable/Substantial)"
```

---

## Task 2: Update Governance Docs

**Files:**
- Modify: `docs/DATABASE_SCHEMA.md`
- Modify: `CLAUDE.md`

**Step 1: Add Quality Score Bands section to DATABASE_SCHEMA.md**

Add after the `## leagues_metadata` section (after the closing `---`):

```markdown
## Quality Score Bands

`quality_score` (0–100) is calculated by `src/database/validators.calculate_quality_score()`.

| Band | Range | Constant | Scraper Behavior |
|------|-------|----------|-----------------|
| Thin | 0–59 | `AUTO_REPLACE_THRESHOLD = 60` | Super scrape auto-archives old + writes new if contradicted |
| Borderline | 60–74 | `DEEP_SCRAPE_THRESHOLD = 75` | Super scrape triggered; contradictions flagged for manual review |
| Acceptable | 75–89 | — | Standard League Checker: team count verify only |
| Substantial | 90+ | — | Standard League Checker: team count verify only |

Constants: `src/config/quality_thresholds.py`
```

**Step 2: Update CLAUDE.md**

In the `streamlit_app/pages/` tree, replace the `merge_tool.py` line with:

```
│       ├── url_merge.py             # Manage: dedup within a single url_scraped
│       └── league_merge.py          # Manage: cross-URL dedup using 6-field identity model
```

In the Quick Start table, the Scraping row should read:

```
| **Scraping & Extraction** | [CLAUDE_EXTRACT.md](docs/agents/CLAUDE_EXTRACT.md) | Queue Monitor (run scraper), Scraper UI (in progress) |
```

And the Data Cleaning row:

```
| **Data Cleaning & Validation** | [CLAUDE_MANAGE.md](docs/agents/CLAUDE_MANAGE.md) | Leagues Viewer, Data Quality, URL Merge, League Merge, Org View |
```

**Step 3: Commit**

```bash
git add docs/DATABASE_SCHEMA.md CLAUDE.md
git commit -m "docs: add quality score bands to schema; update CLAUDE.md pages list"
```

---

## Task 3: Deep Crawler Wrapper

**Files:**
- Create: `src/scraper/deep_crawler.py`
- Test: `tests/test_deep_crawler.py`

**Step 1: Write the failing test**

```python
# tests/test_deep_crawler.py
from unittest.mock import patch, call
from src.scraper.deep_crawler import deep_crawl

def test_deep_crawl_calls_crawl_with_aggressive_settings():
    with patch("src.scraper.deep_crawler.crawl") as mock_crawl, \
         patch("src.scraper.deep_crawler.fetch_page_as_yaml") as mock_fetch:
        mock_crawl.return_value = [("https://example.com/leagues", "yaml: content")]
        result = deep_crawl("https://example.com")
        mock_crawl.assert_called_once_with(
            "https://example.com",
            max_index_depth=4,
            primary_link_min_score=60,
            force_refresh=True,
        )
        assert result == [("https://example.com/leagues", "yaml: content")]

def test_deep_crawl_returns_empty_list_on_failure():
    with patch("src.scraper.deep_crawler.crawl", side_effect=Exception("network error")):
        result = deep_crawl("https://example.com")
        assert result == []
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_deep_crawler.py -v
```
Expected: ImportError.

**Step 3: Implement**

First, `smart_crawler.crawl()` needs to accept `primary_link_min_score` and `force_refresh`
parameters. Open `src/scraper/smart_crawler.py` and update the `crawl()` signature:

```python
def crawl(
    start_url: str,
    max_index_depth: int = 2,
    primary_link_min_score: int = 100,
    force_refresh: bool = False,
) -> list:
```

Wherever `fetch_page_as_yaml(link.url)` is called inside `crawl()`, pass through
`force_refresh=force_refresh`. Wherever `link.score >= 100` is checked in Step A,
replace with `link.score >= primary_link_min_score`.

Then create the wrapper:

```python
# src/scraper/deep_crawler.py
"""Deep crawler — aggressive settings for super scraper Pass 1."""
from __future__ import annotations
import logging
from src.scraper.smart_crawler import crawl

logger = logging.getLogger(__name__)

def deep_crawl(start_url: str) -> list[tuple[str, str]]:
    """Crawl with depth=4, lowered link threshold, and cache bypass.

    Returns list of (url, yaml_content) same as crawl().
    Returns empty list on any failure (caller decides how to handle).
    """
    try:
        return crawl(
            start_url,
            max_index_depth=4,
            primary_link_min_score=60,
            force_refresh=True,
        )
    except Exception as e:
        logger.error(f"deep_crawl failed for {start_url}: {e}")
        return []
```

**Step 4: Run test to verify it passes**

```
pytest tests/test_deep_crawler.py -v
```
Expected: 2 tests PASS.

**Step 5: Commit**

```bash
git add src/scraper/smart_crawler.py src/scraper/deep_crawler.py tests/test_deep_crawler.py
git commit -m "feat: add deep_crawl() wrapper with aggressive settings for super scraper"
```

---

## Task 4: Reconciler

**Files:**
- Create: `src/scraper/reconciler.py`
- Test: `tests/test_reconciler.py`

**Step 1: Write the failing tests**

```python
# tests/test_reconciler.py
from src.scraper.reconciler import reconcile, ReconcileAction

def _league(quality=80, num_teams=8, day="Monday", venue="Arena"):
    return {
        "league_id": "abc-123",
        "quality_score": quality,
        "num_teams": num_teams,
        "day_of_week": day,
        "venue_name": venue,
    }

def test_no_contradiction_returns_merge():
    extracted = {"num_teams": 8, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=80, num_teams=8))
    assert action == ReconcileAction.MERGE

def test_contradiction_thin_returns_replace():
    extracted = {"num_teams": 12, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=50, num_teams=8))
    assert action == ReconcileAction.REPLACE

def test_contradiction_borderline_returns_review():
    extracted = {"num_teams": 12, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=65, num_teams=8))
    assert action == ReconcileAction.REVIEW

def test_contradiction_acceptable_returns_merge():
    """High-quality existing record: never auto-replace on contradiction."""
    extracted = {"num_teams": 12, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=80, num_teams=8))
    assert action == ReconcileAction.MERGE

def test_team_count_tolerance():
    """Difference of exactly 1 is not a contradiction."""
    extracted = {"num_teams": 9, "day_of_week": "Monday", "venue_name": "Arena"}
    action, _ = reconcile(extracted, _league(quality=50, num_teams=8))
    assert action == ReconcileAction.MERGE

def test_contradicting_field_in_reason():
    extracted = {"num_teams": 15, "day_of_week": "Tuesday", "venue_name": "Arena"}
    action, reason = reconcile(extracted, _league(quality=50, num_teams=8))
    assert action == ReconcileAction.REPLACE
    assert "num_teams" in reason or "day_of_week" in reason
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_reconciler.py -v
```
Expected: ImportError.

**Step 3: Implement**

```python
# src/scraper/reconciler.py
"""Reconciliation logic: compare new extraction vs existing DB record."""
from __future__ import annotations
from enum import Enum
from src.config.quality_thresholds import AUTO_REPLACE_THRESHOLD, DEEP_SCRAPE_THRESHOLD


class ReconcileAction(str, Enum):
    MERGE   = "MERGE"    # No contradiction, or existing is high quality — merge normally
    REPLACE = "REPLACE"  # Contradiction + existing is THIN — auto-archive and write new
    REVIEW  = "REVIEW"   # Contradiction + existing is BORDERLINE — queue for manual review


def _contradictions(extracted: dict, existing: dict) -> list[str]:
    """Return list of field names that contradict between extracted and existing."""
    issues = []

    # num_teams: contradiction if difference > 1
    new_t = extracted.get("num_teams")
    old_t = existing.get("num_teams")
    if new_t is not None and old_t is not None and abs(new_t - old_t) > 1:
        issues.append("num_teams")

    # day_of_week: contradiction if both non-null and differ
    for field in ("day_of_week", "venue_name"):
        new_v = extracted.get(field)
        old_v = existing.get(field)
        if new_v and old_v and new_v.lower() != old_v.lower():
            issues.append(field)

    return issues


def reconcile(
    extracted: dict,
    existing: dict,
) -> tuple[ReconcileAction, str]:
    """Decide what to do with a new extraction vs an existing DB record.

    Returns:
        (ReconcileAction, reason_string)
    """
    contradictions = _contradictions(extracted, existing)

    if not contradictions:
        return ReconcileAction.MERGE, "no contradiction"

    reason = f"contradictions: {', '.join(contradictions)}"
    existing_score = existing.get("quality_score") or 0

    if existing_score < AUTO_REPLACE_THRESHOLD:
        return ReconcileAction.REPLACE, reason
    if existing_score < DEEP_SCRAPE_THRESHOLD:
        return ReconcileAction.REVIEW, reason

    # Acceptable or Substantial — never auto-replace
    return ReconcileAction.MERGE, f"existing quality sufficient ({existing_score}) — {reason}"
```

**Step 4: Run test to verify it passes**

```
pytest tests/test_reconciler.py -v
```
Expected: 6 tests PASS.

**Step 5: Commit**

```bash
git add src/scraper/reconciler.py tests/test_reconciler.py
git commit -m "feat: add reconciler with MERGE/REPLACE/REVIEW actions based on quality bands"
```

---

## Task 5: Within-URL Auto-Consolidator

**Files:**
- Create: `src/database/consolidator.py`
- Test: `tests/test_consolidator.py`

**Step 1: Write the failing tests**

```python
# tests/test_consolidator.py
from src.database.consolidator import find_within_url_duplicates, ConsolidationGroup

def _row(league_id, org="Org A", sss="V01", year=2026, venue="Park",
         day="Monday", level="Rec", quality=70):
    return {
        "league_id": league_id,
        "organization_name": org,
        "sport_season_code": sss,
        "season_year": year,
        "venue_name": venue,
        "day_of_week": day,
        "competition_level": level,
        "quality_score": quality,
    }

def test_identical_six_fields_flagged():
    rows = [_row("A", quality=80), _row("B", quality=60)]
    groups = find_within_url_duplicates(rows)
    assert len(groups) == 1
    g = groups[0]
    assert g.keep_id == "A"   # higher quality
    assert g.archive_id == "B"
    assert g.confidence == "AUTO"

def test_five_of_six_with_one_null_flagged():
    r1 = _row("A", quality=80)
    r2 = _row("B", quality=60)
    r2["competition_level"] = None  # one null — still AUTO
    groups = find_within_url_duplicates([r1, r2])
    assert len(groups) == 1
    assert groups[0].confidence == "AUTO"

def test_four_of_six_flagged_as_review():
    r1 = _row("A", quality=80)
    r2 = _row("B", quality=60, day="Wednesday", level="Intermediate")
    groups = find_within_url_duplicates([r1, r2])
    assert len(groups) == 1
    assert groups[0].confidence == "REVIEW"

def test_clearly_distinct_not_flagged():
    r1 = _row("A", day="Monday")
    r2 = _row("B", day="Friday", level="Intermediate")
    groups = find_within_url_duplicates([r1, r2])
    assert len(groups) == 0

def test_three_records_two_dupes():
    rows = [_row("A", quality=90), _row("B", quality=60), _row("C", day="Wednesday")]
    groups = find_within_url_duplicates(rows)
    # A and B are dupes; C is distinct
    assert len(groups) == 1
    assert groups[0].keep_id == "A"
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_consolidator.py -v
```
Expected: ImportError.

**Step 3: Implement**

```python
# src/database/consolidator.py
"""Within-URL duplicate detection and auto-consolidation."""
from __future__ import annotations
from dataclasses import dataclass

_IDENTITY_FIELDS = (
    "organization_name",
    "sport_season_code",
    "season_year",
    "venue_name",
    "day_of_week",
    "competition_level",
)


@dataclass
class ConsolidationGroup:
    keep_id: str
    archive_id: str
    confidence: str   # "AUTO" (auto-archive) or "REVIEW" (surface in UI)
    matched_fields: int


def _count_matching_fields(a: dict, b: dict) -> int:
    """Count how many identity fields match, treating null as wildcard."""
    count = 0
    for f in _IDENTITY_FIELDS:
        av, bv = a.get(f), b.get(f)
        if av is None or bv is None:
            count += 1  # null = compatible
        elif str(av).lower() == str(bv).lower():
            count += 1
    return count


def find_within_url_duplicates(rows: list[dict]) -> list[ConsolidationGroup]:
    """Find duplicate pairs within a list of league records from the same URL.

    Args:
        rows: League records, all from the same url_scraped.

    Returns:
        List of ConsolidationGroup — one per duplicate pair found.
        confidence="AUTO"   → 5 or 6 fields match (safe to auto-archive lower quality)
        confidence="REVIEW" → 4 fields match (surface in URL Merge UI)
    """
    groups: list[ConsolidationGroup] = []
    used: set[str] = set()

    # Sort descending by quality so we always keep the better record
    sorted_rows = sorted(rows, key=lambda r: r.get("quality_score") or 0, reverse=True)

    for i, a in enumerate(sorted_rows):
        if a["league_id"] in used:
            continue
        for b in sorted_rows[i + 1:]:
            if b["league_id"] in used:
                continue
            matched = _count_matching_fields(a, b)
            if matched >= 6:
                confidence = "AUTO"
            elif matched == 5:
                confidence = "AUTO"
            elif matched == 4:
                confidence = "REVIEW"
            else:
                continue

            groups.append(ConsolidationGroup(
                keep_id=a["league_id"],
                archive_id=b["league_id"],
                confidence=confidence,
                matched_fields=matched,
            ))
            used.add(b["league_id"])
            break  # each record can only be in one pair

    return groups
```

**Step 4: Run test to verify it passes**

```
pytest tests/test_consolidator.py -v
```
Expected: 5 tests PASS.

**Step 5: Commit**

```bash
git add src/database/consolidator.py tests/test_consolidator.py
git commit -m "feat: add within-URL duplicate consolidator (AUTO/REVIEW confidence)"
```

---

## Task 6: Super Scraper Pipeline

**Files:**
- Create: `scripts/super_scraper.py`
- Test: `tests/test_super_scraper.py`

**Step 1: Write the failing tests**

```python
# tests/test_super_scraper.py
from unittest.mock import patch, MagicMock
from scripts.super_scraper import run

def test_run_returns_result_dict():
    with patch("scripts.super_scraper.deep_crawl", return_value=[]) as mock_crawl, \
         patch("scripts.super_scraper._run_pass2", return_value=[]):
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
         patch("scripts.super_scraper.insert_league") as mock_insert:
        result = run("https://example.com", dry_run=True)
        mock_insert.assert_not_called()
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_super_scraper.py -v
```
Expected: ImportError.

**Step 3: Implement**

```python
# scripts/super_scraper.py
"""Super scraper: two-pass deep crawl + team count verification + reconciliation.

Usage:
    python scripts/super_scraper.py --url https://guelphsoccerleague.ca
    python scripts/super_scraper.py --url https://... --dry-run
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

logger = logging.getLogger(__name__)


def _get_existing_leagues(url: str) -> list[dict]:
    from src.database.supabase_client import get_client
    result = (
        get_client().table("leagues_metadata")
        .select("league_id, organization_name, num_teams, day_of_week, venue_name, "
                "competition_level, gender_eligibility, sport_season_code, quality_score, "
                "season_year, url_scraped")
        .eq("url_scraped", url)
        .eq("is_archived", False)
        .execute()
    )
    return result.data or []


def _run_pass2(url: str, run_id: str) -> list[dict]:
    """Pass 2: Playwright navigator → team count extraction. Returns list of extraction dicts."""
    from playwright.sync_api import sync_playwright
    from src.checkers.playwright_navigator import PlaywrightNavigator
    from src.checkers.team_count_extractor import TeamCountExtractor

    navigator = PlaywrightNavigator()
    extractor = TeamCountExtractor()
    results = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            import asyncio
            navigated_pages = asyncio.run(
                navigator.navigate(page, url, run_id, "super_scraper")
            )
            browser.close()

        for nav_page in navigated_pages:
            extraction = extractor.extract(
                nav_page.html, url=nav_page.url, nav_path=nav_page.nav_path
            )
            results.append({
                "division_name": extraction.division_name,
                "num_teams": len(extraction.team_names),
                "team_names": extraction.team_names,
                "nav_path": extraction.nav_path,
            })
    except Exception as e:
        logger.warning(f"Pass 2 failed for {url}: {e}")

    return results


def _queue_for_review(url: str, extracted: dict, existing: dict, reason: str) -> None:
    """Write a record to super_scrape_review for manual resolution."""
    from src.database.supabase_client import get_client
    try:
        get_client().table("super_scrape_review").insert({
            "url": url,
            "extracted": extracted,
            "existing_league_id": existing.get("league_id"),
            "reason": reason,
        }).execute()
    except Exception as e:
        logger.warning(f"Could not write review queue entry: {e}")


def run(url: str, dry_run: bool = False) -> dict:
    from src.scraper.deep_crawler import deep_crawl
    from src.extractors.yaml_extractor import extract_league_data_from_yaml
    from src.database.writer import insert_league
    from src.database.leagues_reader import archive_league
    from src.scraper.reconciler import reconcile, ReconcileAction
    from src.database.consolidator import find_within_url_duplicates

    result = {
        "url": url,
        "pages_crawled": 0,
        "leagues_extracted": 0,
        "leagues_written": 0,
        "archived": 0,
        "review_queued": 0,
        "auto_consolidated": 0,
        "errors": [],
    }

    run_id = str(uuid4())
    existing_leagues = _get_existing_leagues(url)
    logger.info(f"Super scrape {url} — {len(existing_leagues)} existing records")

    # --- Pass 1: Deep YAML crawl ---
    league_pages = deep_crawl(url)
    result["pages_crawled"] = len(league_pages)

    all_extracted: list[dict] = []
    for page_url, yaml_content in league_pages:
        try:
            leagues = extract_league_data_from_yaml(yaml_content, page_url)
            all_extracted.extend(leagues)
        except Exception as e:
            result["errors"].append(f"Extraction failed {page_url}: {e}")

    result["leagues_extracted"] = len(all_extracted)

    # --- Pass 2: Team count verification ---
    pass2_results = _run_pass2(url, run_id)
    logger.info(f"Pass 2 found {len(pass2_results)} division(s)")

    # Enrich Pass 1 extractions with Pass 2 team counts where division matches
    for extracted in all_extracted:
        for p2 in pass2_results:
            if p2.get("num_teams") and not extracted.get("num_teams"):
                extracted["num_teams"] = p2["num_teams"]
                break

    if dry_run:
        logger.info(f"DRY-RUN: would write {len(all_extracted)} league(s)")
        result["leagues_written"] = len(all_extracted)
        return result

    # --- Reconcile + write ---
    for extracted in all_extracted:
        # Find best matching existing record (same day_of_week + gender or first if only one)
        existing = None
        if len(existing_leagues) == 1:
            existing = existing_leagues[0]
        else:
            for ex in existing_leagues:
                if (ex.get("day_of_week") or "").lower() == (extracted.get("day_of_week") or "").lower():
                    existing = ex
                    break

        if existing is None:
            # No match — just write
            try:
                league_id, _ = insert_league(extracted)
                if league_id:
                    result["leagues_written"] += 1
            except Exception as e:
                result["errors"].append(str(e))
            continue

        action, reason = reconcile(extracted, existing)

        if action == ReconcileAction.REPLACE:
            archive_league(existing["league_id"])
            result["archived"] += 1
            try:
                league_id, _ = insert_league(extracted)
                if league_id:
                    result["leagues_written"] += 1
            except Exception as e:
                result["errors"].append(str(e))

        elif action == ReconcileAction.REVIEW:
            _queue_for_review(url, extracted, existing, reason)
            result["review_queued"] += 1

        else:  # MERGE
            try:
                league_id, _ = insert_league(extracted)
                if league_id:
                    result["leagues_written"] += 1
            except Exception as e:
                result["errors"].append(str(e))

    # --- Auto-consolidation ---
    fresh_leagues = _get_existing_leagues(url)
    dup_groups = find_within_url_duplicates(fresh_leagues)
    for group in dup_groups:
        if group.confidence == "AUTO":
            archive_league(group.archive_id)
            result["auto_consolidated"] += 1
            logger.info(f"Auto-consolidated: archived {group.archive_id[:8]} (kept {group.keep_id[:8]})")

    logger.info(
        f"Super scrape done — written={result['leagues_written']} "
        f"archived={result['archived']} review={result['review_queued']} "
        f"consolidated={result['auto_consolidated']}"
    )
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Super scraper: two-pass deep extraction")
    parser.add_argument("--url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level),
                        format="[%(asctime)s] %(levelname)s - %(message)s")

    result = run(args.url, dry_run=args.dry_run)
    print(f"\nSUPER SCRAPER RESULTS for {result['url']}")
    print(f"  Pages crawled:     {result['pages_crawled']}")
    print(f"  Leagues extracted: {result['leagues_extracted']}")
    print(f"  Leagues written:   {result['leagues_written']}")
    print(f"  Auto-archived:     {result['archived']}")
    print(f"  Review queued:     {result['review_queued']}")
    print(f"  Auto-consolidated: {result['auto_consolidated']}")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ERROR: {e}")
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run tests**

```
pytest tests/test_super_scraper.py -v
```
Expected: 2 tests PASS.

**Step 5: Commit**

```bash
git add scripts/super_scraper.py tests/test_super_scraper.py
git commit -m "feat: add super_scraper pipeline (two-pass: deep YAML + Playwright team count)"
```

---

## Task 7: League Checker — Quality Branch

**Files:**
- Modify: `src/checkers/league_checker.py`
- Test: `tests/test_league_checker_branch.py`

**Step 1: Write the failing test**

```python
# tests/test_league_checker_branch.py
from unittest.mock import patch, MagicMock
from src.checkers.league_checker import LeagueChecker

def _make_db_leagues(quality: int) -> list[dict]:
    return [{
        "league_id": "abc-123",
        "organization_name": "Test",
        "num_teams": 8,
        "day_of_week": "Monday",
        "competition_level": "Rec",
        "gender_eligibility": "Mens",
        "sport_season_code": "S01",
        "quality_score": quality,
    }]

def test_high_quality_uses_standard_check():
    checker = LeagueChecker.__new__(LeagueChecker)
    with patch.object(checker, "_get_leagues_for_url", return_value=_make_db_leagues(80)), \
         patch.object(checker, "_standard_check", return_value=MagicMock()) as mock_std, \
         patch.object(checker, "_super_check") as mock_super:
        checker.check_url("https://example.com")
        mock_std.assert_called_once()
        mock_super.assert_not_called()

def test_low_quality_uses_super_check():
    checker = LeagueChecker.__new__(LeagueChecker)
    with patch.object(checker, "_get_leagues_for_url", return_value=_make_db_leagues(60)), \
         patch.object(checker, "_standard_check") as mock_std, \
         patch.object(checker, "_super_check", return_value=MagicMock()) as mock_super:
        checker.check_url("https://example.com")
        mock_super.assert_called_once()
        mock_std.assert_not_called()
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_league_checker_branch.py -v
```
Expected: FAIL — `LeagueChecker` has no `_standard_check` / `_super_check` methods yet.

**Step 3: Refactor `src/checkers/league_checker.py`**

Rename the existing `_check_url_async` logic into `_standard_check_async`. Add a new
`_super_check` that calls `super_scraper.run()`. Add branching in `check_url()`:

```python
from src.config.quality_thresholds import DEEP_SCRAPE_THRESHOLD

def check_url(self, url: str, progress_callback=None) -> CheckRunResult:
    db_leagues = self._get_leagues_for_url(url)
    min_quality = min((l.get("quality_score") or 0 for l in db_leagues), default=0)

    if min_quality < DEEP_SCRAPE_THRESHOLD and db_leagues:
        if progress_callback:
            progress_callback(f"Quality {min_quality} < {DEEP_SCRAPE_THRESHOLD} — triggering super scrape")
        return self._super_check(url, db_leagues, progress_callback)
    else:
        return asyncio.run(self._standard_check_async(url, db_leagues, progress_callback))

def _super_check(self, url: str, db_leagues: list[dict], progress_callback=None) -> CheckRunResult:
    from scripts.super_scraper import run as super_run
    check_run_id = uuid4()
    if progress_callback:
        progress_callback("Running super scrape (deep crawl + team count pass)...")
    result = super_run(url, dry_run=False)
    checks = [{
        "check_run_id": str(check_run_id),
        "league_id": None,
        "status": "SUPER_SCRAPED",
        "old_num_teams": None,
        "new_num_teams": result.get("leagues_written"),
        "division_name": None,
        "nav_path": [],
        "screenshot_paths": [],
        "url_checked": url,
        "super_scrape_result": result,
    }]
    self.check_store.save_checks(checks)
    return CheckRunResult(check_run_id=check_run_id, checks=checks, url=url)
```

Rename `_check_url_async` → `_standard_check_async` in the same file.

**Step 4: Run tests**

```
pytest tests/test_league_checker_branch.py tests/test_reconciler.py tests/test_quality_thresholds.py -v
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/checkers/league_checker.py tests/test_league_checker_branch.py
git commit -m "feat: League Checker branches on quality score — super scrape when < 75"
```

---

## Task 8: DB Migration — super_scrape_review Table

**Files:**
- Create: `migrations/002_add_super_scrape_review.sql`

**Step 1: Write the migration**

```sql
-- migrations/002_add_super_scrape_review.sql
-- Review queue for super scraper borderline contradictions

CREATE TABLE IF NOT EXISTS super_scrape_review (
    review_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url               TEXT NOT NULL,
    extracted         JSONB NOT NULL,          -- new extracted league data
    existing_league_id UUID REFERENCES leagues_metadata(league_id),
    reason            TEXT,                    -- which fields contradicted
    status            TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING / ACCEPTED / REJECTED
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ
);

CREATE INDEX idx_ssr_url ON super_scrape_review(url);
CREATE INDEX idx_ssr_status ON super_scrape_review(status);
```

**Step 2: Apply migration in Supabase**

Go to Supabase → SQL Editor, paste and run the migration.
Verify: `SELECT * FROM super_scrape_review LIMIT 1;` returns empty result set (no error).

**Step 3: Commit**

```bash
git add migrations/002_add_super_scrape_review.sql
git commit -m "feat: add super_scrape_review table for borderline contradiction review queue"
```

---

## Task 9: URL Merge Tool (rename + scope)

**Files:**
- Rename: `streamlit_app/pages/merge_tool.py` → `streamlit_app/pages/url_merge.py`
- Modify: `src/database/leagues_reader.py` — add `get_duplicate_groups_for_url()`
- Modify: `streamlit_app/app.py` — update nav entry

**Step 1: Add `get_duplicate_groups_for_url()` to leagues_reader**

Open `src/database/leagues_reader.py`. Find the existing `get_duplicate_groups()` function.
Add a new function below it:

```python
def get_duplicate_groups_for_url(url_scraped: str) -> list[dict]:
    """Return duplicate groups scoped to a single url_scraped.

    Same logic as get_duplicate_groups() but pre-filtered to one URL.
    """
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("*")
        .eq("url_scraped", url_scraped)
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []

    from src.database.consolidator import find_within_url_duplicates, ConsolidationGroup
    dup_groups = find_within_url_duplicates(rows)

    # Convert ConsolidationGroup → same dict format as get_duplicate_groups()
    groups = []
    id_to_row = {r["league_id"]: r for r in rows}
    for g in dup_groups:
        keep = id_to_row.get(g.keep_id)
        arch = id_to_row.get(g.archive_id)
        if keep and arch:
            groups.append({"records": [keep, arch], "confidence": g.confidence})
    return groups
```

**Step 2: Create url_merge.py**

Copy `merge_tool.py` to `url_merge.py`. Apply these changes:

- Title: `"🔗 URL Merge"` and caption `"Find and resolve duplicate leagues within a single source URL."`
- Add a URL selector at the top:

```python
# Get distinct scraped URLs
client = get_client()
url_res = (
    client.table("leagues_metadata")
    .select("url_scraped")
    .eq("is_archived", False)
    .execute()
)
urls = sorted(set(r["url_scraped"] for r in (url_res.data or []) if r.get("url_scraped")))

selected_url = st.selectbox("Source URL", [""] + urls)
if not selected_url:
    st.info("Select a URL to scan for duplicates within it.")
    return
```

- Replace the `get_duplicate_groups()` call with `get_duplicate_groups_for_url(selected_url)`
- Import `get_duplicate_groups_for_url` instead of `get_duplicate_groups`

**Step 3: Update app.py nav**

In `streamlit_app/app.py`:

Replace:
```python
"🔀 Merge Tool":             ("manage",  "merge_tool"),
```
With:
```python
"🔗 URL Merge":              ("manage",  "url_merge"),
"🔀 League Merge":           ("manage",  "league_merge"),
```

Update the sidebar loop and the module dispatch block accordingly (add `url_merge` and
`league_merge` cases, remove `merge_tool`).

**Step 4: Verify in browser**

Run `streamlit run streamlit_app/app.py`. Navigate to "URL Merge". Select a URL. Confirm
the duplicate scan works.

**Step 5: Commit**

```bash
git add streamlit_app/pages/url_merge.py src/database/leagues_reader.py streamlit_app/app.py
git rm streamlit_app/pages/merge_tool.py
git commit -m "feat: replace Merge Tool with URL Merge (scoped to single url_scraped)"
```

---

## Task 10: League Merge Tool (new cross-URL page)

**Files:**
- Create: `streamlit_app/pages/league_merge.py`

**Step 1: Create league_merge.py**

This is essentially the old `merge_tool.py` behaviour (cross-URL, uses `get_duplicate_groups()`),
with updated title and caption:

```python
"""League Merge — surface and resolve cross-URL duplicate league records."""
from __future__ import annotations

import streamlit as st
from src.database.leagues_reader import get_duplicate_groups, archive_league
from src.database.supabase_client import get_client

# --- Copy _merge() and _COMPARE_FIELDS from old merge_tool.py exactly ---
# --- Copy render() from old merge_tool.py, updating title/caption only ---

def render() -> None:
    st.title("🔀 League Merge")
    st.caption(
        "Finds suspected duplicate leagues across all URLs "
        "(same org + sport + year + venue + day + level)."
    )
    # ... rest of render() unchanged from merge_tool.py
```

**Step 2: Wire into app.py**

The `league_merge` case should already be in the dispatch block from Task 9.
Add the import:
```python
elif module_name == "league_merge":
    from pages import league_merge
    league_merge.render()
```

**Step 3: Verify in browser**

Navigate to "League Merge". Click "Scan for duplicates". Confirm it shows cross-URL groups.

**Step 4: Commit**

```bash
git add streamlit_app/pages/league_merge.py streamlit_app/app.py
git commit -m "feat: add League Merge page for cross-URL deduplication"
```

---

## Task 11: League Checker UI — Show Super Scrape Results

**Files:**
- Modify: `streamlit_app/pages/league_checker.py`

**Step 1: Update results display**

In `league_checker.py`, in the results display loop, add handling for `status == "SUPER_SCRAPED"`:

```python
for chk in run_result.checks:
    status = chk.get("status", "?")

    if status == "SUPER_SCRAPED":
        sr = chk.get("super_scrape_result", {})
        st.success(
            f"Super scrape complete — "
            f"{sr.get('leagues_written', 0)} written, "
            f"{sr.get('archived', 0)} archived, "
            f"{sr.get('review_queued', 0)} queued for review, "
            f"{sr.get('auto_consolidated', 0)} auto-consolidated"
        )
        if sr.get("errors"):
            for err in sr["errors"]:
                st.caption(f"  Error: {err}")
        continue

    # ... existing display logic unchanged
```

**Step 2: Verify in browser**

Run League Checker on a URL with quality_score < 75. Confirm the super scrape summary
banner appears instead of the old per-division expanders.

**Step 3: Commit**

```bash
git add streamlit_app/pages/league_checker.py
git commit -m "feat: League Checker UI shows super scrape summary for low-quality URLs"
```

---

## Task 12: Update CLAUDE_EXTRACT.md + CLAUDE_MANAGE.md

**Files:**
- Modify: `docs/agents/CLAUDE_EXTRACT.md`
- Modify: `docs/agents/CLAUDE_MANAGE.md`

**Step 1: Update CLAUDE_EXTRACT.md**

Add a **Scraper Cascade** section (or update the existing one) to describe:

```
L0  mcp_agent_scraper.py     Manual/complex sites — run when L1 fails
L1  smart_scraper.py         Standard: BFS YAML crawl, Haiku classify, Sonnet extract
L1.5 super_scraper.py        Auto-triggered by League Checker when quality_score < 75
                             Two passes: deep YAML crawl + Playwright team count verification
                             Reconciles against existing records; auto-archives THIN contradictions
L2  Firecrawl API            Paid fallback only — run when L1/L1.5 both fail
```

Also document that `DEEP_SCRAPE_THRESHOLD = 75` and `AUTO_REPLACE_THRESHOLD = 60` are
the trigger constants, defined in `src/config/quality_thresholds.py`.

**Step 2: Update CLAUDE_MANAGE.md**

Replace references to "Merge Tool" with:
- **URL Merge** — within-URL dedup, scoped to one `url_scraped`
- **League Merge** — cross-URL dedup using 6-field identity model

**Step 3: Commit**

```bash
git add docs/agents/CLAUDE_EXTRACT.md docs/agents/CLAUDE_MANAGE.md
git commit -m "docs: update CLAUDE_EXTRACT + CLAUDE_MANAGE for super scraper cascade and merge tool split"
```

---

## Execution Checklist (run in order)

- [ ] Task 1 — Quality thresholds config
- [ ] Task 2 — Governance docs
- [ ] Task 3 — Deep crawler wrapper + smart_crawler params
- [ ] Task 4 — Reconciler
- [ ] Task 5 — Within-URL consolidator
- [ ] Task 6 — Super scraper pipeline
- [ ] Task 7 — League Checker branch
- [ ] Task 8 — DB migration (run in Supabase SQL editor)
- [ ] Task 9 — URL Merge tool
- [ ] Task 10 — League Merge tool
- [ ] Task 11 — League Checker UI update
- [ ] Task 12 — CLAUDE_EXTRACT + CLAUDE_MANAGE docs
