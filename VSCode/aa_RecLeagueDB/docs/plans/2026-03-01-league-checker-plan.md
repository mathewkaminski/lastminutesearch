# League Checker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Playwright-powered league checker that revisits scraped URLs, counts team names across navigated sub-pages, and shows before/after diffs with screenshot evidence in Streamlit.

**Architecture:** PlaywrightNavigator (keyword-driven multi-hop nav) → TeamCountExtractor (LLM) → LeagueChecker (orchestrator) → CheckStore (Supabase) → Streamlit UI.

**Tech Stack:** Python 3.10+, Playwright, OpenAI GPT-4o, Supabase, Streamlit, pytest/MagicMock

**Design doc:** `docs/plans/2026-03-01-league-checker-design.md` — read it before starting.

---

### Task 1: DB Migration — `league_checks` table

**Files:**
- Create: `migrations/003_add_league_checks_table.sql`

**Step 1: Write the migration**

```sql
-- migrations/003_add_league_checks_table.sql
-- Date: 2026-03-01

CREATE TABLE IF NOT EXISTS public.league_checks (
    check_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    check_run_id     UUID NOT NULL,
    league_id        UUID REFERENCES public.leagues_metadata(league_id),
    checked_at       TIMESTAMPTZ DEFAULT NOW(),
    old_num_teams    INT,
    new_num_teams    INT,
    division_name    TEXT,
    nav_path         TEXT[],
    screenshot_paths TEXT[],
    status           TEXT CHECK (status IN ('MATCH', 'CHANGED', 'NOT_FOUND', 'ERROR')),
    raw_teams        TEXT[],
    url_checked      TEXT,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_league_checks_league_id  ON public.league_checks(league_id);
CREATE INDEX IF NOT EXISTS idx_league_checks_run_id     ON public.league_checks(check_run_id);
CREATE INDEX IF NOT EXISTS idx_league_checks_checked_at ON public.league_checks(checked_at);
```

**Step 2: Run migration in Supabase SQL editor**

Open Supabase → SQL editor → paste migration → run.
Verify: `SELECT * FROM public.league_checks LIMIT 1;` returns empty result (no error).

**Step 3: Commit**

```bash
git add migrations/003_add_league_checks_table.sql
git commit -m "feat: add league_checks table migration"
```

---

### Task 2: `CheckStore` — CRUD for `league_checks`

**Files:**
- Create: `src/database/check_store.py`
- Create: `tests/test_check_store.py`

**Step 1: Write failing tests**

```python
# tests/test_check_store.py
from unittest.mock import MagicMock, patch
from uuid import uuid4
from src.database.check_store import CheckStore

def make_store():
    mock_client = MagicMock()
    store = CheckStore.__new__(CheckStore)
    store.client = mock_client
    return store, mock_client

def test_save_checks_inserts_rows():
    store, mock_client = make_store()
    mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock()
    checks = [{"check_run_id": str(uuid4()), "league_id": str(uuid4()), "status": "MATCH"}]
    store.save_checks(checks)
    mock_client.table.assert_called_with("league_checks")
    mock_client.table.return_value.insert.assert_called_once_with(checks)

def test_get_checks_for_run_returns_list():
    store, mock_client = make_store()
    run_id = uuid4()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"check_id": str(uuid4()), "check_run_id": str(run_id), "status": "MATCH"}
    ]
    result = store.get_checks_for_run(run_id)
    assert len(result) == 1
    assert result[0]["status"] == "MATCH"

def test_get_latest_check_per_league_returns_list():
    store, mock_client = make_store()
    mock_client.rpc.return_value.execute.return_value.data = [
        {"league_id": str(uuid4()), "status": "CHANGED", "new_num_teams": 10}
    ]
    result = store.get_latest_check_per_league()
    assert isinstance(result, list)

def test_get_urls_with_check_age():
    store, mock_client = make_store()
    mock_client.rpc.return_value.execute.return_value.data = [
        {"url_scraped": "https://example.com", "league_count": 3, "last_checked_at": None}
    ]
    result = store.get_urls_with_check_age()
    assert result[0]["league_count"] == 3
```

**Step 2: Run to verify failure**

```bash
cd C:\Users\mathe\VSCode\aa_RecLeagueDB
python -m pytest tests/test_check_store.py -v
```
Expected: ImportError (module doesn't exist yet)

**Step 3: Implement `CheckStore`**

```python
# src/database/check_store.py
from uuid import UUID
from src.database.supabase_client import get_client


class CheckStore:
    def __init__(self):
        self.client = get_client()

    def save_checks(self, checks: list[dict]) -> None:
        """Insert one or more league_check rows."""
        self.client.table("league_checks").insert(checks).execute()

    def get_checks_for_run(self, check_run_id: UUID) -> list[dict]:
        result = (
            self.client.table("league_checks")
            .select("*")
            .eq("check_run_id", str(check_run_id))
            .execute()
        )
        return result.data or []

    def get_latest_check_per_league(self) -> list[dict]:
        """Returns the most recent check row per league_id."""
        result = self.client.rpc("get_latest_league_checks").execute()
        return result.data or []

    def get_urls_with_check_age(self) -> list[dict]:
        """Returns each distinct url_scraped with league count and last checked timestamp."""
        result = self.client.rpc("get_urls_with_check_age").execute()
        return result.data or []
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_check_store.py -v
```
Expected: 4 PASSED

**Step 5: Create package init**

```python
# src/checkers/__init__.py
# (empty)
```

**Step 6: Commit**

```bash
git add src/database/check_store.py src/checkers/__init__.py tests/test_check_store.py
git commit -m "feat: add CheckStore for league_checks CRUD"
```

---

### Task 3: `TeamCountExtractor` — LLM team name extraction

**Files:**
- Create: `src/checkers/team_count_extractor.py`
- Create: `tests/test_team_count_extractor.py`

**Step 1: Write failing tests**

```python
# tests/test_team_count_extractor.py
from unittest.mock import patch, MagicMock
from src.checkers.team_count_extractor import TeamCountExtractor, TeamExtractionResult

SAMPLE_HTML = """
<table>
  <tr><td>Red Devils</td><td>3</td><td>1</td></tr>
  <tr><td>Blue Hawks</td><td>2</td><td>2</td></tr>
  <tr><td>Green Force</td><td>1</td><td>3</td></tr>
</table>
"""

EMPTY_HTML = "<div>No leagues found this season.</div>"

def mock_openai_response(team_names, division=None, season=None):
    import json
    mock = MagicMock()
    mock.choices[0].message.content = json.dumps({
        "team_names": team_names,
        "division_name": division,
        "season_identifier": season,
    })
    return mock

def test_extracts_team_names():
    extractor = TeamCountExtractor.__new__(TeamCountExtractor)
    with patch("src.checkers.team_count_extractor.openai.chat.completions.create") as mock_create:
        mock_create.return_value = mock_openai_response(
            ["Red Devils", "Blue Hawks", "Green Force"], "Division A", "Fall 2025"
        )
        result = extractor.extract(SAMPLE_HTML, url="http://example.com", nav_path=["Standings"])
    assert len(result.team_names) == 3
    assert result.division_name == "Division A"
    assert result.season_identifier == "Fall 2025"

def test_returns_empty_on_no_teams():
    extractor = TeamCountExtractor.__new__(TeamCountExtractor)
    with patch("src.checkers.team_count_extractor.openai.chat.completions.create") as mock_create:
        mock_create.return_value = mock_openai_response([])
        result = extractor.extract(EMPTY_HTML, url="http://example.com", nav_path=[])
    assert result.team_names == []
    assert result.division_name is None

def test_result_has_nav_path():
    extractor = TeamCountExtractor.__new__(TeamCountExtractor)
    with patch("src.checkers.team_count_extractor.openai.chat.completions.create") as mock_create:
        mock_create.return_value = mock_openai_response(["Team A"])
        result = extractor.extract("<p>Team A</p>", url="http://x.com", nav_path=["Standings", "Fall 2025"])
    assert result.nav_path == ["Standings", "Fall 2025"]
    assert result.url == "http://x.com"
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_team_count_extractor.py -v
```
Expected: ImportError

**Step 3: Implement `TeamCountExtractor`**

```python
# src/checkers/team_count_extractor.py
import json
import os
from dataclasses import dataclass, field

import openai


SYSTEM_PROMPT = """You extract team names from recreational sports league pages.
Return JSON only: {"team_names": [...], "division_name": "..." or null, "season_identifier": "..." or null}"""

USER_PROMPT = """Extract all unique team names from this HTML.
Look for standings tables, schedule grids, or team lists.
Return team names exactly as shown.

HTML:
{html}"""


@dataclass
class TeamExtractionResult:
    team_names: list[str]
    division_name: str | None
    season_identifier: str | None
    url: str
    nav_path: list[str] = field(default_factory=list)
    screenshot_path: str | None = None


class TeamCountExtractor:
    def __init__(self):
        openai.api_key = os.getenv("OPENAI_API_KEY")

    def extract(
        self,
        html: str,
        url: str,
        nav_path: list[str],
        screenshot_path: str | None = None,
    ) -> TeamExtractionResult:
        # Truncate HTML to avoid token limits
        truncated = html[:12000] if len(html) > 12000 else html

        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT.format(html=truncated)},
            ],
            temperature=0,
        )

        raw = response.choices[0].message.content
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"team_names": [], "division_name": None, "season_identifier": None}

        return TeamExtractionResult(
            team_names=data.get("team_names", []),
            division_name=data.get("division_name"),
            season_identifier=data.get("season_identifier"),
            url=url,
            nav_path=nav_path,
            screenshot_path=screenshot_path,
        )
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_team_count_extractor.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add src/checkers/team_count_extractor.py tests/test_team_count_extractor.py
git commit -m "feat: add TeamCountExtractor with LLM team name extraction"
```

---

### Task 4: `PlaywrightNavigator` — keyword-driven multi-hop navigation

**Files:**
- Create: `src/checkers/playwright_navigator.py`
- Create: `tests/test_playwright_navigator.py`

**Step 1: Write failing tests**

```python
# tests/test_playwright_navigator.py
from unittest.mock import MagicMock, patch, AsyncMock
from src.checkers.playwright_navigator import PlaywrightNavigator, NavigatedPage

def make_navigator():
    nav = PlaywrightNavigator.__new__(PlaywrightNavigator)
    nav.score_threshold = 0.4
    nav.max_hops = 3
    return nav

def test_score_link_high_for_standings():
    nav = make_navigator()
    score = nav._score_text("Standings")
    assert score >= 0.4

def test_score_link_zero_for_irrelevant():
    nav = make_navigator()
    score = nav._score_text("Contact Us")
    assert score < 0.4

def test_score_link_medium_for_schedule():
    nav = make_navigator()
    score = nav._score_text("View Schedule")
    assert score >= 0.4

def test_has_team_list_detects_multiple_names():
    nav = make_navigator()
    html = "<table><tr><td>Red Devils</td></tr><tr><td>Blue Hawks</td></tr><tr><td>Green Force</td></tr></table>"
    assert nav._has_team_list(html) is True

def test_has_team_list_false_for_short_page():
    nav = make_navigator()
    html = "<p>Register now for the upcoming season!</p>"
    assert nav._has_team_list(html) is False
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_playwright_navigator.py -v
```
Expected: ImportError

**Step 3: Implement `PlaywrightNavigator`**

```python
# src/checkers/playwright_navigator.py
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


NAV_KEYWORDS = [
    "standings", "schedule", "teams", "roster", "divisions",
    "current season", "league", "fall", "winter", "spring", "summer",
    "results", "games",
]
SCORE_THRESHOLD = 0.4
MAX_HOPS = 3
SCREENSHOT_DIR = Path("scrapes/screenshots")


@dataclass
class NavigatedPage:
    html: str
    url: str
    nav_path: list[str]
    screenshot_path: str | None = None


class PlaywrightNavigator:
    def __init__(self, score_threshold: float = SCORE_THRESHOLD, max_hops: int = MAX_HOPS):
        self.score_threshold = score_threshold
        self.max_hops = max_hops

    def _score_text(self, text: str) -> float:
        """Score a link/button text against nav keywords. Returns max score 0-1."""
        text_lower = text.lower().strip()
        best = 0.0
        for kw in NAV_KEYWORDS:
            # Exact substring match → high score
            if kw in text_lower:
                best = max(best, 0.8)
                continue
            ratio = SequenceMatcher(None, text_lower, kw).ratio()
            best = max(best, ratio)
        return best

    def _has_team_list(self, html: str) -> bool:
        """Heuristic: True if page appears to contain ≥3 distinct team-like names."""
        # Look for capitalized multi-word phrases in table cells or list items
        names = re.findall(r'<(?:td|li)[^>]*>\s*([A-Z][A-Za-z\s&\'.\-]{3,30})\s*</(?:td|li)>', html)
        unique = set(n.strip() for n in names)
        return len(unique) >= 3

    async def navigate(
        self,
        page,  # Playwright Page object
        start_url: str,
        run_id: str,
        league_id: str,
    ) -> list[NavigatedPage]:
        """
        Navigate from start_url, following keyword-matching links up to max_hops deep.
        Takes screenshots at each step. Returns list of NavigatedPage with HTML snapshots.
        """
        screenshot_base = SCREENSHOT_DIR / league_id / run_id
        screenshot_base.mkdir(parents=True, exist_ok=True)

        visited = set()
        results = []

        await page.goto(start_url)
        visited.add(start_url)

        # Screenshot step 0
        step0_path = str(screenshot_base / "step_0.png")
        await page.screenshot(path=step0_path, full_page=True)

        html0 = await page.content()
        if self._has_team_list(html0):
            results.append(NavigatedPage(
                html=html0, url=start_url, nav_path=[], screenshot_path=step0_path
            ))

        await self._explore(page, visited, results, [], screenshot_base, 0)
        return results

    async def _explore(self, page, visited, results, path, screenshot_base, depth):
        if depth >= self.max_hops:
            return

        # Collect all clickable elements with text
        elements = await page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a[href], button, [role="tab"]'));
            return links.map(el => ({
                text: el.innerText.trim(),
                href: el.href || null,
                tag: el.tagName.toLowerCase(),
            })).filter(e => e.text.length > 0 && e.text.length < 80);
        }""")

        scored = [
            (el, self._score_text(el["text"]))
            for el in elements
            if self._score_text(el["text"]) >= self.score_threshold
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        for el, score in scored:
            target_url = el.get("href") or page.url
            if target_url in visited:
                continue
            visited.add(target_url)
            new_path = path + [el["text"]]

            try:
                if el.get("href"):
                    await page.goto(el["href"])
                else:
                    # Button or tab — click it
                    locator = page.locator(f'text="{el["text"]}"').first
                    await locator.click()
                    await page.wait_for_load_state("networkidle", timeout=5000)

                step_n = len(list(screenshot_base.glob("step_*.png")))
                shot_path = str(screenshot_base / f"step_{step_n}.png")
                await page.screenshot(path=shot_path, full_page=True)

                html = await page.content()
                if self._has_team_list(html):
                    results.append(NavigatedPage(
                        html=html,
                        url=page.url,
                        nav_path=new_path,
                        screenshot_path=shot_path,
                    ))

                await self._explore(page, visited, results, new_path, screenshot_base, depth + 1)

            except Exception:
                pass  # Skip elements that can't be navigated
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_playwright_navigator.py -v
```
Expected: 5 PASSED (unit tests mock the page object, testing scoring + heuristics only)

**Step 5: Commit**

```bash
git add src/checkers/playwright_navigator.py tests/test_playwright_navigator.py
git commit -m "feat: add PlaywrightNavigator with keyword-driven multi-hop navigation"
```

---

### Task 5: `LeagueChecker` — orchestrator

**Files:**
- Create: `src/checkers/league_checker.py`
- Create: `tests/test_league_checker.py`

**Step 1: Write failing tests**

```python
# tests/test_league_checker.py
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4
from src.checkers.league_checker import LeagueChecker, compute_status

def test_compute_status_match():
    assert compute_status(old=8, new=8) == "MATCH"
    assert compute_status(old=8, new=9) == "MATCH"   # ±1 tolerance

def test_compute_status_changed():
    assert compute_status(old=8, new=12) == "CHANGED"
    assert compute_status(old=8, new=5) == "CHANGED"

def test_compute_status_no_old():
    assert compute_status(old=None, new=10) == "CHANGED"  # new data found

def test_compute_status_not_found():
    assert compute_status(old=8, new=0) == "NOT_FOUND"
    assert compute_status(old=None, new=0) == "NOT_FOUND"

def test_match_league_by_division():
    from src.checkers.league_checker import match_to_db
    db_leagues = [
        {"league_id": str(uuid4()), "division_name": "Monday Coed", "num_teams": 8},
        {"league_id": str(uuid4()), "division_name": "Sunday Beach", "num_teams": 6},
    ]
    extraction = MagicMock()
    extraction.division_name = "monday coed 6v6"
    matched = match_to_db(extraction, db_leagues)
    assert matched["division_name"] == "Monday Coed"

def test_match_league_returns_none_on_no_match():
    from src.checkers.league_checker import match_to_db
    db_leagues = [{"league_id": str(uuid4()), "division_name": "Monday Coed", "num_teams": 8}]
    extraction = MagicMock()
    extraction.division_name = "Completely Unrelated Division"
    matched = match_to_db(extraction, db_leagues)
    assert matched is None
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_league_checker.py -v
```
Expected: ImportError

**Step 3: Implement `LeagueChecker`**

```python
# src/checkers/league_checker.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from uuid import UUID, uuid4

from src.checkers.team_count_extractor import TeamCountExtractor, TeamExtractionResult
from src.checkers.playwright_navigator import PlaywrightNavigator, NavigatedPage
from src.database.check_store import CheckStore
from src.database.supabase_client import get_client


def compute_status(old: int | None, new: int) -> str:
    if new == 0:
        return "NOT_FOUND"
    if old is None:
        return "CHANGED"
    return "MATCH" if abs(new - old) <= 1 else "CHANGED"


def match_to_db(extraction: TeamExtractionResult, db_leagues: list[dict]) -> dict | None:
    """Fuzzy-match an extraction result to a leagues_metadata record."""
    if not extraction.division_name:
        return db_leagues[0] if len(db_leagues) == 1 else None

    best_score = 0.0
    best_league = None
    for league in db_leagues:
        candidate = (league.get("division_name") or league.get("league_name") or "").lower()
        score = SequenceMatcher(None, extraction.division_name.lower(), candidate).ratio()
        if score > best_score:
            best_score = score
            best_league = league

    return best_league if best_score >= 0.4 else None


@dataclass
class CheckRunResult:
    check_run_id: UUID
    checks: list[dict]
    url: str


class LeagueChecker:
    def __init__(self):
        self.extractor = TeamCountExtractor()
        self.navigator = PlaywrightNavigator()
        self.check_store = CheckStore()
        self.supabase = get_client()

    def _get_leagues_for_url(self, url: str) -> list[dict]:
        result = (
            self.supabase.table("leagues_metadata")
            .select("league_id, organization_name, num_teams, division_name, day_of_week, sport_season_code")
            .eq("url_scraped", url)
            .execute()
        )
        return result.data or []

    def check_url(self, url: str, progress_callback=None) -> CheckRunResult:
        """Synchronous entry point — wraps async navigate."""
        return asyncio.run(self._check_url_async(url, progress_callback))

    async def _check_url_async(self, url: str, progress_callback=None) -> CheckRunResult:
        from playwright.async_api import async_playwright

        check_run_id = uuid4()
        db_leagues = self._get_leagues_for_url(url)

        if progress_callback:
            progress_callback(f"Found {len(db_leagues)} league(s) at URL")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            navigator = self.navigator
            league_id_for_path = db_leagues[0]["league_id"] if db_leagues else "unknown"
            navigated_pages: list[NavigatedPage] = await navigator.navigate(
                page, url, str(check_run_id), league_id_for_path
            )
            await browser.close()

        if progress_callback:
            progress_callback(f"Navigated to {len(navigated_pages)} page state(s)")

        checks = []
        for nav_page in navigated_pages:
            extraction = self.extractor.extract(
                nav_page.html,
                url=nav_page.url,
                nav_path=nav_page.nav_path,
                screenshot_path=nav_page.screenshot_path,
            )
            matched = match_to_db(extraction, db_leagues)
            old_count = matched["num_teams"] if matched else None
            new_count = len(extraction.team_names)

            checks.append({
                "check_run_id": str(check_run_id),
                "league_id": matched["league_id"] if matched else None,
                "old_num_teams": old_count,
                "new_num_teams": new_count,
                "division_name": extraction.division_name,
                "nav_path": extraction.nav_path,
                "screenshot_paths": [extraction.screenshot_path] if extraction.screenshot_path else [],
                "status": compute_status(old_count, new_count),
                "raw_teams": extraction.team_names,
                "url_checked": nav_page.url,
            })

        self.check_store.save_checks(checks)

        if progress_callback:
            progress_callback(f"Saved {len(checks)} check result(s)")

        return CheckRunResult(check_run_id=check_run_id, checks=checks, url=url)
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_league_checker.py -v
```
Expected: 6 PASSED

**Step 5: Commit**

```bash
git add src/checkers/league_checker.py tests/test_league_checker.py
git commit -m "feat: add LeagueChecker orchestrator"
```

---

### Task 6: Streamlit UI — `league_checker.py`

**Files:**
- Create: `streamlit_app/pages/league_checker.py`
- Modify: `streamlit_app/app.py` — add routing for `league_checker`

**Step 1: Implement the Streamlit page**

```python
# streamlit_app/pages/league_checker.py
"""League Checker — re-scrape URLs to verify team counts."""
from __future__ import annotations

import streamlit as st
from pathlib import Path
from src.checkers.league_checker import LeagueChecker
from src.database.check_store import CheckStore


def render():
    st.title("League Checker")
    st.caption("Re-scrape existing URLs to verify team counts and detect changes.")

    check_store = CheckStore()

    # --- Summary stats ---
    try:
        urls_data = check_store.get_urls_with_check_age()
    except Exception as e:
        st.error(f"Could not load URL list: {e}")
        return

    if not urls_data:
        st.info("No scraped leagues found. Run the scraper first.")
        return

    total_urls = len(urls_data)
    never_checked = sum(1 for r in urls_data if r.get("last_checked_at") is None)
    col1, col2, col3 = st.columns(3)
    col1.metric("URLs", total_urls)
    col2.metric("Never checked", never_checked)
    col3.metric("With changes", sum(1 for r in urls_data if r.get("has_changes")))

    st.divider()

    # --- URL selection ---
    st.subheader("Select URLs to Check")
    selected_urls = []
    for row in urls_data:
        url = row["url_scraped"]
        org = row.get("org_name", url[:60])
        count = row.get("league_count", "?")
        last_checked = row.get("last_checked_at", "Never")
        has_changes = row.get("has_changes", False)

        badge = "🔴 CHANGES" if has_changes else ("⚪ Never" if last_checked == "Never" else "✅ OK")
        label = f"{org}  ({count} leagues)  {badge}"
        if st.checkbox(label, key=f"check_{url}"):
            selected_urls.append(url)

    st.divider()

    # --- Run button ---
    if st.button("Check Selected URLs", disabled=len(selected_urls) == 0, type="primary"):
        checker = LeagueChecker()
        all_results = []

        progress = st.progress(0, text="Starting...")
        status_placeholder = st.empty()

        for i, url in enumerate(selected_urls):
            status_placeholder.info(f"Checking: {url[:80]}")
            msgs = []

            def callback(msg, _msgs=msgs):
                _msgs.append(msg)
                status_placeholder.info(msg)

            try:
                result = checker.check_url(url, progress_callback=callback)
                all_results.append(result)
            except Exception as e:
                st.error(f"Error checking {url}: {e}")

            progress.progress((i + 1) / len(selected_urls), text=f"{i+1}/{len(selected_urls)} URLs")

        status_placeholder.success(f"Done. Checked {len(all_results)} URL(s).")
        st.session_state["last_check_results"] = all_results

    # --- Results display ---
    if "last_check_results" in st.session_state:
        st.divider()
        st.subheader("Results")

        for run_result in st.session_state["last_check_results"]:
            st.markdown(f"**URL:** `{run_result.url}`")
            if not run_result.checks:
                st.warning("No team data found for this URL.")
                continue

            for chk in run_result.checks:
                status = chk.get("status", "?")
                color = {"MATCH": "✅", "CHANGED": "🔴", "NOT_FOUND": "⚠️", "ERROR": "❌"}.get(status, "?")
                label = chk.get("division_name") or "League"
                old_t = chk.get("old_num_teams", "–")
                new_t = chk.get("new_num_teams", "–")

                with st.expander(f"{color} {label}  |  {old_t} → {new_t} teams  [{status}]"):
                    col_a, col_b = st.columns(2)
                    col_a.metric("DB teams", old_t)
                    col_b.metric("Scraped teams", new_t, delta=None if old_t == "–" else (new_t - old_t if isinstance(new_t, int) and isinstance(old_t, int) else None))

                    nav = chk.get("nav_path", [])
                    if nav:
                        st.caption(f"Navigation: {' → '.join(nav)}")

                    teams = chk.get("raw_teams", [])
                    if teams:
                        st.markdown("**Teams found:**")
                        st.write(", ".join(teams))

                    shots = chk.get("screenshot_paths", [])
                    for shot_path in shots:
                        p = Path(shot_path)
                        if p.exists():
                            st.image(str(p), caption=p.name, use_column_width=True)
                        else:
                            st.caption(f"Screenshot: `{shot_path}` (not found locally)")
```

**Step 2: Update `app.py` to route to `league_checker`**

In `streamlit_app/app.py`:

Add `"🔍 League Checker"` to the PAGES dict and sidebar navigation (under Search Pipeline), and add the routing block:

```python
# In PAGES dict:
"🔍 League Checker":  ("search", "league_checker"),

# In sidebar, add to the Search Pipeline loop:
for label in ["🎯 Campaign Manager", "📋 Queue Monitor", "🕷️ Scraper UI", "🔍 League Checker"]:

# Add routing block:
elif module_name == "league_checker":
    try:
        from pages import league_checker
        league_checker.render()
    except ImportError:
        st.info("🔍 League Checker — coming soon.")
```

**Step 3: Manually test**

```bash
cd C:\Users\mathe\VSCode\aa_RecLeagueDB
streamlit run streamlit_app/app.py
```

Navigate to "League Checker" in sidebar. Verify URL list loads. Select one URL and click "Check Selected URLs".

**Step 4: Commit**

```bash
git add streamlit_app/pages/league_checker.py streamlit_app/app.py
git commit -m "feat: add League Checker Streamlit UI"
```

---

### Task 7: Supabase RPC functions

Two RPC functions are needed by `CheckStore`. Run these in Supabase SQL editor.

**Step 1: Create `get_latest_league_checks`**

```sql
-- Run in Supabase SQL editor
CREATE OR REPLACE FUNCTION get_latest_league_checks()
RETURNS TABLE (
    check_id UUID,
    league_id UUID,
    checked_at TIMESTAMPTZ,
    old_num_teams INT,
    new_num_teams INT,
    status TEXT
) AS $$
    SELECT DISTINCT ON (league_id)
        check_id, league_id, checked_at, old_num_teams, new_num_teams, status
    FROM public.league_checks
    WHERE league_id IS NOT NULL
    ORDER BY league_id, checked_at DESC;
$$ LANGUAGE SQL;
```

**Step 2: Create `get_urls_with_check_age`**

```sql
CREATE OR REPLACE FUNCTION get_urls_with_check_age()
RETURNS TABLE (
    url_scraped TEXT,
    org_name TEXT,
    league_count BIGINT,
    last_checked_at TIMESTAMPTZ,
    has_changes BOOLEAN
) AS $$
    SELECT
        lm.url_scraped,
        lm.organization_name AS org_name,
        COUNT(DISTINCT lm.league_id) AS league_count,
        MAX(lc.checked_at) AS last_checked_at,
        BOOL_OR(lc.status = 'CHANGED') AS has_changes
    FROM public.leagues_metadata lm
    LEFT JOIN public.league_checks lc ON lc.league_id = lm.league_id
    WHERE lm.is_archived = FALSE
    GROUP BY lm.url_scraped, lm.organization_name
    ORDER BY last_checked_at ASC NULLS FIRST;
$$ LANGUAGE SQL;
```

**Step 3: Verify in SQL editor**

```sql
SELECT * FROM get_urls_with_check_age() LIMIT 5;
SELECT * FROM get_latest_league_checks() LIMIT 5;
```

Both should return without error (empty result is fine).

**Step 4: Commit migration notes**

```bash
git add migrations/003_add_league_checks_table.sql
git commit -m "docs: note RPC functions needed for CheckStore" --allow-empty
```
(Or just note this step was done manually — no file needed.)

---

## Test Suite Summary

After all tasks, run full test suite:

```bash
cd C:\Users\mathe\VSCode\aa_RecLeagueDB
python -m pytest tests/test_check_store.py tests/test_team_count_extractor.py tests/test_playwright_navigator.py tests/test_league_checker.py -v
```

Expected: ~18 tests PASSED

---

## What's NOT in Scope (Parking Lot)

- History tab (trend over time per league)
- Auto-scheduling / cron runs
- "Accept changes" button that writes new `num_teams` back to `leagues_metadata`
- Bulk check all (one-button, all leagues)
- Handling iframes or login-gated content
