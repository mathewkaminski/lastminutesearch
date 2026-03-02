# League Checker Design

**Date:** 2026-03-01
**Status:** Approved — ready for implementation planning

---

## Goal

Build a **League Checker** tool that revisits already-scraped URLs, uses Playwright to navigate to team rosters/standings/schedules, and verifies whether the `num_teams` value in `leagues_metadata` is still accurate. Results are shown in Streamlit with before/after comparison and screenshot evidence.

---

## Core Requirements

1. **Primary signal:** `num_teams` — count unique team names found on the re-scraped page(s)
2. **Identity anchors:** `day_of_week`, `start_time`, `venue_name`, `season_start_date` — used to confirm the right league was matched
3. **Input:** User manually selects URLs to check from a Streamlit list
4. **Multiple leagues per URL:** A single `url_scraped` may correspond to several `leagues_metadata` records (different days/divisions). The checker should find all of them
5. **Screenshots:** Saved locally to `scrapes/screenshots/{league_id}/{check_run_id}/step_N.png`
6. **History tab:** Deferred to Parking Lot

---

## Architecture

```
Streamlit UI (league_checker.py)
    │
    ├── Loads leagues_metadata grouped by url_scraped
    ├── User selects URLs to check
    └── On "Check Selected":
            │
            ▼
    LeagueChecker (src/checkers/league_checker.py)
            │
            ├── For each selected URL:
            │     ├── Fetches all leagues_metadata records for that URL
            │     ├── Calls PlaywrightNavigator
            │     │       └── Navigates to team count pages (up to 3 hops)
            │     ├── Calls TeamCountExtractor (LLM)
            │     │       └── Extracts team names + count from page HTML
            │     ├── Matches found leagues to DB records
            │     └── Calls CheckStore to persist results
            │
            └── Returns check_run_id for display

    CheckStore (src/database/check_store.py)
            └── CRUD for league_checks table

    league_checks table (Supabase)
```

---

## Data Model

### New table: `league_checks`

```sql
CREATE TABLE public.league_checks (
    check_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    check_run_id    UUID NOT NULL,              -- groups all checks from one button press
    league_id       UUID REFERENCES public.leagues_metadata(league_id),
    checked_at      TIMESTAMPTZ DEFAULT NOW(),
    old_num_teams   INT,                        -- value from DB at check time
    new_num_teams   INT,                        -- freshly scraped
    division_name   TEXT,                       -- if multiple divisions found
    nav_path        TEXT[],                     -- navigation trail, e.g. ["Standings", "Fall 2025"]
    screenshot_paths TEXT[],                    -- local paths to step screenshots
    status          TEXT,                       -- MATCH | CHANGED | NOT_FOUND | ERROR
    raw_teams       TEXT[],                     -- list of team names found
    url_checked     TEXT,                       -- final URL at time of extraction
    notes           TEXT                        -- error messages or manual notes
);

CREATE INDEX idx_league_checks_league_id   ON public.league_checks(league_id);
CREATE INDEX idx_league_checks_run_id      ON public.league_checks(check_run_id);
CREATE INDEX idx_league_checks_checked_at  ON public.league_checks(checked_at);
```

---

## Component: PlaywrightNavigator

**File:** `src/checkers/playwright_navigator.py`

### Navigation Strategy

The navigator is keyword-driven and generic — it does not assume any particular page structure (dropdowns, tabs, accordions). It treats all interactive/link elements equally.

```python
NAV_KEYWORDS = [
    "standings", "schedule", "teams", "roster", "divisions",
    "current season", "league", "fall", "winter", "spring", "summer"
]

SCORE_THRESHOLD = 0.4   # minimum fuzzy match score to qualify a link
MAX_HOPS = 3            # maximum navigation depth
```

**Algorithm:**

```
navigate(url, league_ids):
  load page → screenshot step_0
  collected_pages = []

  for hop in range(MAX_HOPS):
      candidates = collect_all_clickable_elements(page)
          # <a href>, <button>, <select option>, nav links, tabs
      scored = fuzzy_score_all(candidates, NAV_KEYWORDS)
      qualified = [c for c in scored if c.score >= SCORE_THRESHOLD]
          # sorted by score descending

      for candidate in qualified (not yet visited):
          navigate to candidate → screenshot step_N
          html = get_page_html()
          if has_team_list(html):
              collected_pages.append(PageResult(html, screenshot, nav_path))
          # continue to try other candidates regardless

      if all target leagues have team counts:
          break   # early exit

  return collected_pages
```

**Key properties:**
- Tries ALL qualified candidates above threshold, not just the first
- Stops early only when team counts are found for all leagues at this URL
- Takes a screenshot at each navigation step
- Tracks visited URLs to avoid loops
- `has_team_list(html)` is a heuristic: checks for ≥3 distinct capitalized names in a table/list context

---

## Component: TeamCountExtractor

**File:** `src/checkers/team_count_extractor.py`

Uses GPT-4o to extract team names from the navigated page HTML.

**Prompt focus:**
```
Given the following HTML from a recreational sports league page,
extract a list of unique team names participating in this league.

Look for:
- Tables with team names (standings, schedule)
- Lists of teams in a division
- Team names in match pairings

Return:
- team_names: list of unique team name strings
- division_name: name of division/session if identifiable (or null)
- season_identifier: any date or season label on this page (or null)

If no team names are found, return empty list.
```

**Output:**
```python
@dataclass
class TeamExtractionResult:
    team_names: list[str]
    division_name: str | None
    season_identifier: str | None
    url: str
    nav_path: list[str]
    screenshot_path: str
```

---

## Component: LeagueChecker (Orchestrator)

**File:** `src/checkers/league_checker.py`

```python
def check_url(url: str, progress_callback=None) -> CheckRunResult:
    check_run_id = uuid4()
    db_leagues = get_leagues_for_url(url)          # from leagues_metadata
    page_results = navigator.navigate(url, [l.league_id for l in db_leagues])
    extractions = [extractor.extract(p) for p in page_results]

    checks = []
    for extraction in extractions:
        matched_league = match_to_db(extraction, db_leagues)
            # match by: division_name fuzzy, season_identifier, day_of_week
        status = compute_status(matched_league, len(extraction.team_names))
        checks.append(LeagueCheck(
            check_run_id=check_run_id,
            league_id=matched_league.league_id if matched_league else None,
            old_num_teams=matched_league.num_teams if matched_league else None,
            new_num_teams=len(extraction.team_names),
            division_name=extraction.division_name,
            nav_path=extraction.nav_path,
            screenshot_paths=extraction.screenshot_path,
            status=status,
            raw_teams=extraction.team_names,
        ))

    check_store.save_checks(checks)
    return CheckRunResult(check_run_id=check_run_id, checks=checks)
```

**Status logic:**
- `MATCH` — new_num_teams within ±1 of old_num_teams (small variance OK)
- `CHANGED` — new_num_teams differs by >1
- `NOT_FOUND` — no team names found on any navigated page
- `ERROR` — Playwright exception or LLM failure

---

## Component: CheckStore

**File:** `src/database/check_store.py`

```python
def save_checks(checks: list[LeagueCheck]) -> None
def get_checks_for_run(check_run_id: UUID) -> list[LeagueCheck]
def get_latest_check_per_league() -> list[LeagueCheck]
    # used by UI to show "last checked" badge
def get_urls_with_check_age() -> list[dict]
    # {url, org_name, league_count, last_checked_at, has_changes}
```

---

## Streamlit UI: `streamlit_app/pages/league_checker.py`

### Layout

```
Page: League Checker

[Summary stats row]
  Total leagues: 142 | Last run: 2 days ago | Changes detected: 3

[URL list — grouped by org]
  ☑ Ottawa Valley Sixes       3 leagues   Last checked: 3 days ago   [2 CHANGED]
  ☐ Ottawa Adult Soccer        5 leagues   Never checked
  ☐ Kanata Volleyball         2 leagues   Last checked: 1 week ago   [✓ all match]
  ...

[Check Selected URLs] button → progress bar per URL

[Results panel — shown after run]
  Check Run: 2026-03-01 14:32   Ottawa Valley Sixes
  ┌──────────────────────────────────────────────────────────────────┐
  │ League            │ Old Teams │ New Teams │ Status   │           │
  │ Monday Coed 6v6   │ 8         │ 10        │ CHANGED  │ [expand]  │
  │ Sunday Beach 4v4  │ 6         │ 6         │ MATCH    │ [expand]  │
  │ Sunday Indoor     │ –         │ 12        │ NEW DATA │ [expand]  │
  └──────────────────────────────────────────────────────────────────┘

  [expand] shows:
    - Division name (if found)
    - Nav path followed: Homepage → Standings → Fall 2025
    - Screenshots: [step_0.png] [step_1.png] [step_2.png]
    - Raw team names list
```

---

## File Structure

```
src/
└── checkers/
    ├── __init__.py
    ├── league_checker.py         # Orchestrator
    ├── playwright_navigator.py   # Multi-hop Playwright nav
    └── team_count_extractor.py   # LLM team name extraction

src/database/
└── check_store.py                # CRUD for league_checks

streamlit_app/pages/
└── league_checker.py             # Streamlit UI

migrations/
└── 003_add_league_checks_table.sql

tests/
├── test_playwright_navigator.py
├── test_team_count_extractor.py
├── test_league_checker.py
└── test_check_store.py
```

---

## Future Work (Parking Lot)

- **History tab:** Show all past check runs per league, trend over time
- **Auto-scheduling:** Cron/scheduled bulk runs (not just manual trigger)
- **Update on confirm:** Button to accept `new_num_teams` and write back to `leagues_metadata`
- **Bulk check all:** One-button run on all leagues (not just selected)

---

## Environment

No new env vars needed. Uses existing:
- `OPENAI_API_KEY` — for TeamCountExtractor
- `SUPABASE_URL` / `SUPABASE_KEY` — for CheckStore
- Playwright already installed in project

Screenshots saved to: `scrapes/screenshots/` (gitignored, local only)
