# Leagues-Only Management Views — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the three stubbed Data Management pages (Leagues Viewer, Data Quality, Merge Tool) filtered exclusively to `listing_type = 'league'` records.

**Architecture:** A shared `src/database/leagues_reader.py` module handles all Supabase queries (filtered to leagues only). Three Streamlit pages consume it. No new DB columns needed — `listing_type` and `is_archived` are sufficient.

**Tech Stack:** Python 3.10+, Supabase/PostgreSQL, Streamlit, stdlib only (no new deps)

**Design doc:** `docs/plans/2026-03-02-leagues-only-views-design.md`

---

## Task 1: leagues_reader.py — Shared DB Layer

**Files:**
- Create: `src/database/leagues_reader.py`
- Create: `tests/test_leagues_reader.py`

### Step 1: Write failing tests first

Create `tests/test_leagues_reader.py`:

```python
"""Tests for leagues_reader — the shared DB layer for all league management pages."""
from unittest.mock import patch, MagicMock
import pytest


def _make_mock_client(rows: list[dict]) -> MagicMock:
    """Build a mock Supabase client whose .execute() returns rows."""
    mock_result = MagicMock()
    mock_result.data = rows

    mock_q = MagicMock()
    mock_q.execute.return_value = mock_result
    # All query builder methods return self so chains work
    for method in ("select", "eq", "in_", "ilike", "gte", "lte", "lt", "order", "limit"):
        getattr(mock_q, method).return_value = mock_q

    mock_client = MagicMock()
    mock_client.table.return_value = mock_q
    return mock_client


# ---------------------------------------------------------------------------
# get_leagues
# ---------------------------------------------------------------------------

def test_get_leagues_returns_rows():
    rows = [{"league_id": "abc", "organization_name": "TSSC", "quality_score": 80}]
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client(rows)):
        from src.database.leagues_reader import get_leagues
        result = get_leagues()
    assert result == rows


def test_get_leagues_empty_db():
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client([])):
        from src.database.leagues_reader import get_leagues
        result = get_leagues()
    assert result == []


def test_get_leagues_with_org_search_calls_ilike():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import get_leagues
        get_leagues({"org_search": "tssc"})
    mock_client.table.return_value.ilike.assert_called_once_with("organization_name", "%tssc%")


def test_get_leagues_with_sport_codes_calls_in():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import get_leagues
        get_leagues({"sport_season_codes": ["V10", "S10"]})
    mock_client.table.return_value.in_.assert_called_once_with("sport_season_code", ["V10", "S10"])


def test_get_leagues_empty_filter_dict_no_extra_calls():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import get_leagues
        get_leagues({})
    mock_client.table.return_value.ilike.assert_not_called()
    mock_client.table.return_value.in_.assert_not_called()


# ---------------------------------------------------------------------------
# get_quality_summary
# ---------------------------------------------------------------------------

def test_get_quality_summary_basic():
    rows = [{"quality_score": 80}, {"quality_score": 60}, {"quality_score": 40}]
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client(rows)):
        from src.database.leagues_reader import get_quality_summary
        result = get_quality_summary()
    assert result["total"] == 3
    assert result["avg_score"] == round((80 + 60 + 40) / 3, 1)
    assert result["pct_good"] == round(1 / 3 * 100, 1)   # only 80 >= 70
    assert result["pct_poor"] == round(1 / 3 * 100, 1)   # only 40 < 50


def test_get_quality_summary_empty():
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client([])):
        from src.database.leagues_reader import get_quality_summary
        result = get_quality_summary()
    assert result == {"total": 0, "avg_score": 0.0, "pct_good": 0.0, "pct_poor": 0.0}


# ---------------------------------------------------------------------------
# get_field_coverage
# ---------------------------------------------------------------------------

def test_get_field_coverage_full():
    """All fields populated → 100% for every field."""
    row = {
        "day_of_week": "Monday", "start_time": "19:00", "venue_name": "Lamport",
        "team_fee": 800.0, "individual_fee": None, "season_start_date": "2026-01-01",
        "season_end_date": "2026-03-01", "competition_level": "Rec",
        "gender_eligibility": "CoEd", "num_weeks": 10, "quality_score": 80,
    }
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client([row])):
        from src.database.leagues_reader import get_field_coverage
        result = get_field_coverage()
    assert result["day_of_week"] == 100.0
    assert result["individual_fee"] == 0.0   # None → not covered


def test_get_field_coverage_empty():
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client([])):
        from src.database.leagues_reader import get_field_coverage
        result = get_field_coverage()
    assert all(v == 0.0 for v in result.values())


# ---------------------------------------------------------------------------
# get_duplicate_groups
# ---------------------------------------------------------------------------

def test_get_duplicate_groups_finds_duplicates():
    rows = [
        {"league_id": "1", "organization_name": "TSSC", "sport_season_code": "V10",
         "season_year": 2026, "venue_name": "Lamport", "day_of_week": "Monday",
         "competition_level": "Rec", "quality_score": 80, "url_scraped": "https://a.com"},
        {"league_id": "2", "organization_name": "TSSC", "sport_season_code": "V10",
         "season_year": 2026, "venue_name": "Lamport", "day_of_week": "Monday",
         "competition_level": "Rec", "quality_score": 60, "url_scraped": "https://b.com"},
    ]
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client(rows)):
        from src.database.leagues_reader import get_duplicate_groups
        result = get_duplicate_groups()
    assert len(result) == 1
    assert len(result[0]["records"]) == 2


def test_get_duplicate_groups_no_duplicates():
    rows = [
        {"league_id": "1", "organization_name": "TSSC", "sport_season_code": "V10",
         "season_year": 2026, "venue_name": "Lamport", "day_of_week": "Monday",
         "competition_level": "Rec", "quality_score": 80, "url_scraped": "https://a.com"},
        {"league_id": "2", "organization_name": "ZogSports", "sport_season_code": "S10",
         "season_year": 2026, "venue_name": "Other", "day_of_week": "Tuesday",
         "competition_level": "Int", "quality_score": 70, "url_scraped": "https://b.com"},
    ]
    with patch("src.database.leagues_reader.get_client", return_value=_make_mock_client(rows)):
        from src.database.leagues_reader import get_duplicate_groups
        result = get_duplicate_groups()
    assert result == []


# ---------------------------------------------------------------------------
# archive_league / add_to_rescrape_queue
# ---------------------------------------------------------------------------

def test_archive_league_calls_update():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import archive_league
        archive_league("abc-123")
    mock_client.table.return_value.update.assert_called_once_with({"is_archived": True})


def test_add_to_rescrape_queue_inserts_urls():
    mock_client = _make_mock_client([])
    with patch("src.database.leagues_reader.get_client", return_value=mock_client):
        from src.database.leagues_reader import add_to_rescrape_queue
        add_to_rescrape_queue(["https://example.com", "https://other.com"])
    assert mock_client.table.return_value.upsert.call_count == 1
```

### Step 2: Run tests to confirm they fail

```bash
cd C:\Users\mathe\VSCode\aa_RecLeagueDB
python -m pytest tests/test_leagues_reader.py -v
```

Expected: `ModuleNotFoundError` (file doesn't exist yet).

### Step 3: Write the implementation

Create `src/database/leagues_reader.py`:

```python
"""Shared DB query layer for league management pages.

All queries are pre-filtered to listing_type='league' AND is_archived=False.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from src.database.supabase_client import get_client

logger = logging.getLogger(__name__)

# Fields checked in the coverage report
COVERAGE_FIELDS = [
    "day_of_week",
    "start_time",
    "venue_name",
    "team_fee",
    "individual_fee",
    "season_start_date",
    "season_end_date",
    "competition_level",
    "gender_eligibility",
    "num_weeks",
]

# Fields that define a unique league (identity model from DATABASE_SCHEMA.md)
_IDENTITY_FIELDS = (
    "organization_name",
    "sport_season_code",
    "season_year",
    "venue_name",
    "day_of_week",
    "competition_level",
)


def get_leagues(filters: dict | None = None) -> list[dict]:
    """Return all active league records, optionally filtered.

    Args:
        filters: Optional dict with any of:
            - org_search (str): ilike match on organization_name
            - sport_season_codes (list[str]): exact-match multi-select
            - days_of_week (list[str]): exact-match multi-select
            - genders (list[str]): exact-match multi-select
            - quality_min (int): minimum quality_score
            - quality_max (int): maximum quality_score
            - season_year (int): exact season_year match

    Returns:
        List of league record dicts, ordered by quality_score ascending.
    """
    client = get_client()
    q = (
        client.table("leagues_metadata")
        .select("*")
        .eq("listing_type", "league")
        .eq("is_archived", False)
    )

    if filters:
        if org := filters.get("org_search"):
            q = q.ilike("organization_name", f"%{org}%")
        if codes := filters.get("sport_season_codes"):
            q = q.in_("sport_season_code", codes)
        if days := filters.get("days_of_week"):
            q = q.in_("day_of_week", days)
        if genders := filters.get("genders"):
            q = q.in_("gender_eligibility", genders)
        if (qmin := filters.get("quality_min")) is not None:
            q = q.gte("quality_score", qmin)
        if (qmax := filters.get("quality_max")) is not None:
            q = q.lte("quality_score", qmax)
        if year := filters.get("season_year"):
            q = q.eq("season_year", year)

    result = q.order("quality_score").execute()
    return result.data or []


def get_quality_summary() -> dict:
    """Return aggregate quality metrics for all active leagues.

    Returns:
        Dict with keys: total, avg_score, pct_good (>=70), pct_poor (<50).
    """
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("quality_score")
        .eq("listing_type", "league")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return {"total": 0, "avg_score": 0.0, "pct_good": 0.0, "pct_poor": 0.0}

    total = len(rows)
    scores = [r.get("quality_score") or 0 for r in rows]
    return {
        "total": total,
        "avg_score": round(sum(scores) / total, 1),
        "pct_good": round(sum(1 for s in scores if s >= 70) * 100 / total, 1),
        "pct_poor": round(sum(1 for s in scores if s < 50) * 100 / total, 1),
    }


def get_field_coverage() -> dict[str, float]:
    """Return % of leagues where each important field is populated.

    Returns:
        Dict of field_name -> coverage percentage (0.0–100.0).
    """
    client = get_client()
    fields_str = ", ".join(["quality_score"] + COVERAGE_FIELDS)
    result = (
        client.table("leagues_metadata")
        .select(fields_str)
        .eq("listing_type", "league")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return {f: 0.0 for f in COVERAGE_FIELDS}

    total = len(rows)
    return {
        field: round(
            sum(1 for r in rows if r.get(field) is not None) * 100 / total, 1
        )
        for field in COVERAGE_FIELDS
    }


def get_duplicate_groups() -> list[dict]:
    """Find suspected duplicate leagues by identity-field grouping.

    Two records are suspected duplicates if they share the same
    (org_name, sport_code, season_year, venue, day_of_week, competition_level).

    Returns:
        List of dicts, each with keys 'key' (tuple) and 'records' (list of 2+ rows).
    """
    client = get_client()
    fields = "league_id, organization_name, sport_season_code, season_year, " \
             "venue_name, day_of_week, competition_level, quality_score, url_scraped, updated_at"
    result = (
        client.table("leagues_metadata")
        .select(fields)
        .eq("listing_type", "league")
        .eq("is_archived", False)
        .execute()
    )
    rows = result.data or []

    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        key = tuple(
            (row.get(f) or "").lower().strip() if isinstance(row.get(f), str)
            else (row.get(f) or "")
            for f in _IDENTITY_FIELDS
        )
        groups[key].append(row)

    return [
        {"key": key, "records": records}
        for key, records in groups.items()
        if len(records) > 1
    ]


def archive_league(league_id: str) -> None:
    """Set is_archived=True for a single league record.

    Args:
        league_id: UUID of the league to archive.
    """
    client = get_client()
    client.table("leagues_metadata").update({"is_archived": True}).eq("league_id", league_id).execute()
    logger.info("Archived league %s", league_id)


def add_to_rescrape_queue(urls: list[str]) -> None:
    """Insert URLs into scrape_queue with status PENDING.

    Upserts on url to avoid duplicates if already queued.

    Args:
        urls: List of url_scraped values to re-queue.
    """
    if not urls:
        return
    client = get_client()
    rows = [{"url": url, "status": "PENDING", "source": "rescrape_trigger"} for url in urls]
    client.table("scrape_queue").upsert(rows, on_conflict="url").execute()
    logger.info("Added %d URLs to rescrape queue", len(urls))
```

### Step 4: Run tests to confirm they pass

```bash
python -m pytest tests/test_leagues_reader.py -v
```

Expected: All 12 tests PASS.

### Step 5: Commit

```bash
git add src/database/leagues_reader.py tests/test_leagues_reader.py
git commit -m "feat: add leagues_reader DB layer for league management pages"
```

---

## Task 2: Leagues Viewer Page

**Files:**
- Create: `streamlit_app/pages/leagues_viewer.py`

### Step 1: Create the page

Create `streamlit_app/pages/leagues_viewer.py`:

```python
"""Leagues Viewer — browse and filter active league records."""
from __future__ import annotations

import csv
import io

import streamlit as st

from src.database.leagues_reader import get_leagues, archive_league, add_to_rescrape_queue

_DISPLAY_COLS = [
    "organization_name", "sport_season_code", "day_of_week", "start_time",
    "venue_name", "team_fee", "individual_fee", "quality_score", "updated_at",
]

_ALL_FIELDS = [
    "league_id", "organization_name", "url_scraped", "base_domain",
    "sport_season_code", "season_year", "season_start_date", "season_end_date",
    "day_of_week", "start_time", "num_weeks", "venue_name",
    "competition_level", "gender_eligibility",
    "team_fee", "individual_fee", "registration_deadline",
    "num_teams", "slots_left", "has_referee", "requires_insurance",
    "quality_score", "created_at", "updated_at",
]


def _build_filters() -> dict:
    """Render sidebar filter controls and return active filters dict."""
    filters = {}
    with st.sidebar:
        st.header("Filters")

        org = st.text_input("Org name contains", placeholder="e.g. TSSC")
        if org.strip():
            filters["org_search"] = org.strip()

        sport_codes = st.multiselect(
            "Sport/Season code",
            options=["V10", "V11", "S10", "S11", "B10", "B11", "U10", "U11",
                     "F10", "F11", "T10", "T11", "H10", "H11", "K10", "K11"],
        )
        if sport_codes:
            filters["sport_season_codes"] = sport_codes

        days = st.multiselect(
            "Day of week",
            options=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        )
        if days:
            filters["days_of_week"] = days

        genders = st.multiselect(
            "Gender eligibility",
            options=["Mens", "Womens", "CoEd", "Other", "Unsure"],
        )
        if genders:
            filters["genders"] = genders

        qmin, qmax = st.slider("Quality score range", 0, 100, (0, 100))
        if qmin > 0:
            filters["quality_min"] = qmin
        if qmax < 100:
            filters["quality_max"] = qmax

    return filters


def _to_csv(rows: list[dict]) -> str:
    """Serialize rows to CSV string."""
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_ALL_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def render() -> None:
    st.title("Leagues Viewer")
    st.caption("Active league records only. Drop-ins and unknowns are excluded.")

    filters = _build_filters()

    try:
        rows = get_leagues(filters)
    except Exception as e:
        st.error(f"Could not load data: {e}")
        return

    if not rows:
        st.info("No leagues match the current filters.")
        return

    st.metric("Leagues shown", len(rows))

    # --- CSV export ---
    csv_data = _to_csv(rows)
    st.download_button(
        "Download CSV",
        data=csv_data,
        file_name="leagues_export.csv",
        mime="text/csv",
    )

    st.divider()

    # --- Table (key columns only) ---
    display_rows = [{col: r.get(col) for col in _DISPLAY_COLS} for r in rows]
    st.dataframe(display_rows, use_container_width=True)

    st.divider()

    # --- Detail expand ---
    st.subheader("Record Detail")
    league_options = {
        f"{r.get('organization_name')} — {r.get('sport_season_code')} — {r.get('day_of_week')} — {r.get('league_id', '')[:8]}": r
        for r in rows
    }
    selected_label = st.selectbox("Select a league to inspect", options=list(league_options.keys()))
    if selected_label:
        record = league_options[selected_label]
        col1, col2 = st.columns(2)
        items = [(k, record.get(k)) for k in _ALL_FIELDS]
        mid = len(items) // 2
        with col1:
            for k, v in items[:mid]:
                st.markdown(f"**{k}:** {v}")
        with col2:
            for k, v in items[mid:]:
                st.markdown(f"**{k}:** {v}")

        st.divider()
        col_arch, col_rescrape = st.columns(2)
        with col_arch:
            if st.button("🗑️ Archive this league", key=f"arch_{record['league_id']}"):
                archive_league(record["league_id"])
                st.success("Archived. Refresh to see updated list.")
                st.rerun()
        with col_rescrape:
            if st.button("🔄 Add to re-scrape queue", key=f"rescrape_{record['league_id']}"):
                add_to_rescrape_queue([record["url_scraped"]])
                st.success(f"Added {record['url_scraped'][:60]} to queue.")
```

### Step 2: Syntax check

```bash
cd C:\Users\mathe\VSCode\aa_RecLeagueDB
python -c "import ast; ast.parse(open('streamlit_app/pages/leagues_viewer.py', encoding='utf-8').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

### Step 3: Commit

```bash
git add streamlit_app/pages/leagues_viewer.py
git commit -m "feat: add Leagues Viewer page (leagues only)"
```

---

## Task 3: Data Quality Dashboard

**Files:**
- Create: `streamlit_app/pages/data_quality.py`

### Step 1: Create the page

Create `streamlit_app/pages/data_quality.py`:

```python
"""Data Quality Dashboard — quality metrics for league records only."""
from __future__ import annotations

import streamlit as st

from src.database.leagues_reader import (
    get_quality_summary,
    get_field_coverage,
    get_leagues,
    add_to_rescrape_queue,
    COVERAGE_FIELDS,
)


def _get_quality_by_org(rows: list[dict]) -> list[dict]:
    from collections import defaultdict
    orgs: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        orgs[row.get("organization_name") or "Unknown"].append(row.get("quality_score") or 0)
    result = []
    for org, scores in orgs.items():
        total = len(scores)
        avg = sum(scores) / total
        pct_good = sum(1 for s in scores if s >= 70) * 100 / total
        result.append({"Organization": org, "Leagues": total,
                        "Avg Score": round(avg, 1), "% ≥ 70": round(pct_good, 1)})
    return sorted(result, key=lambda x: x["Avg Score"])


def _get_quality_by_sport(rows: list[dict]) -> list[dict]:
    from collections import defaultdict
    sports: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        sports[row.get("sport_season_code") or "Unknown"].append(row.get("quality_score") or 0)
    result = []
    for sport, scores in sports.items():
        total = len(scores)
        avg = sum(scores) / total
        result.append({"Sport Code": sport, "Leagues": total, "Avg Score": round(avg, 1)})
    return sorted(result, key=lambda x: x["Avg Score"])


def render() -> None:
    st.title("Data Quality Dashboard")
    st.caption("League records only. Drop-ins and unknowns are excluded.")

    try:
        summary = get_quality_summary()
        coverage = get_field_coverage()
        all_rows = get_leagues()
    except Exception as e:
        st.error(f"Could not load data: {e}")
        return

    # --- Summary metrics ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Leagues", summary["total"])
    c2.metric("Avg Quality Score", summary["avg_score"])
    c3.metric("% Score ≥ 70", f"{summary['pct_good']}%")
    c4.metric("% Score < 50 (needs attention)", f"{summary['pct_poor']}%")

    st.divider()

    # --- Field coverage ---
    st.subheader("Field Coverage")
    st.caption("% of leagues where each field is populated.")
    for field in COVERAGE_FIELDS:
        pct = coverage.get(field, 0.0)
        col_label, col_bar = st.columns([2, 5])
        col_label.markdown(f"`{field}`")
        col_bar.progress(int(pct), text=f"{pct}%")

    st.divider()

    # --- Breakdown by org ---
    st.subheader("Quality by Organization")
    org_data = _get_quality_by_org(all_rows)
    if org_data:
        st.dataframe(org_data, use_container_width=True)

    # --- Breakdown by sport ---
    st.subheader("Quality by Sport Code")
    sport_data = _get_quality_by_sport(all_rows)
    if sport_data:
        st.dataframe(sport_data, use_container_width=True)

    st.divider()

    # --- Issue queue ---
    st.subheader("Issue Queue (Score < 50)")
    poor = [r for r in all_rows if (r.get("quality_score") or 0) < 50]
    if not poor:
        st.success("No leagues below quality threshold.")
    else:
        st.warning(f"{len(poor)} leagues need attention.")
        issue_display = [
            {
                "org": r.get("organization_name"),
                "sport": r.get("sport_season_code"),
                "score": r.get("quality_score"),
                "url": r.get("url_scraped", "")[:60],
                "league_id": r.get("league_id"),
            }
            for r in poor
        ]
        st.dataframe(issue_display, use_container_width=True)

        if st.button("🔄 Add all to re-scrape queue"):
            urls = [r["url_scraped"] for r in poor if r.get("url_scraped")]
            add_to_rescrape_queue(urls)
            st.success(f"Added {len(urls)} URLs to re-scrape queue.")
```

### Step 2: Syntax check

```bash
python -c "import ast; ast.parse(open('streamlit_app/pages/data_quality.py', encoding='utf-8').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

### Step 3: Commit

```bash
git add streamlit_app/pages/data_quality.py
git commit -m "feat: add Data Quality dashboard page (leagues only)"
```

---

## Task 4: Merge Tool

**Files:**
- Create: `streamlit_app/pages/merge_tool.py`

### Step 1: Create the page

Create `streamlit_app/pages/merge_tool.py`:

```python
"""Merge Tool — surface and resolve suspected duplicate league records."""
from __future__ import annotations

import streamlit as st

from src.database.leagues_reader import get_duplicate_groups, archive_league
from src.database.supabase_client import get_client


def _merge(keep_id: str, archive_id: str) -> None:
    """Keep higher-quality record, copy non-null fields from the other, archive duplicate."""
    client = get_client()
    # Fetch both records
    keep_res = client.table("leagues_metadata").select("*").eq("league_id", keep_id).execute()
    arch_res = client.table("leagues_metadata").select("*").eq("league_id", archive_id).execute()
    keep = (keep_res.data or [{}])[0]
    other = (arch_res.data or [{}])[0]

    # Copy non-null fields from other into keep (only where keep is null)
    updates = {
        k: v for k, v in other.items()
        if v is not None and keep.get(k) is None
        and k not in ("league_id", "created_at", "updated_at", "is_archived")
    }
    if updates:
        client.table("leagues_metadata").update(updates).eq("league_id", keep_id).execute()

    # Archive the duplicate
    archive_league(archive_id)


_COMPARE_FIELDS = [
    "organization_name", "sport_season_code", "season_year",
    "day_of_week", "start_time", "venue_name", "competition_level",
    "gender_eligibility", "team_fee", "individual_fee", "num_weeks",
    "quality_score", "url_scraped", "updated_at",
]


def render() -> None:
    st.title("Merge Tool")
    st.caption("Finds suspected duplicate leagues (same org + sport + year + venue + day + level).")

    if st.button("🔍 Scan for duplicates"):
        try:
            groups = get_duplicate_groups()
            st.session_state["dup_groups"] = groups
        except Exception as e:
            st.error(f"Scan failed: {e}")
            return

    groups = st.session_state.get("dup_groups")
    if groups is None:
        st.info("Click 'Scan for duplicates' to begin.")
        return

    if not groups:
        st.success("No suspected duplicates found.")
        return

    st.warning(f"Found {len(groups)} suspected duplicate group{'s' if len(groups) != 1 else ''}.")

    for i, group in enumerate(groups):
        records = group["records"]
        # Sort so higher quality score is first
        records = sorted(records, key=lambda r: r.get("quality_score") or 0, reverse=True)
        r1, r2 = records[0], records[1]

        with st.expander(
            f"Group {i + 1}: {r1.get('organization_name')} — {r1.get('sport_season_code')} — "
            f"{r1.get('day_of_week')} ({len(records)} records)"
        ):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Record A** (score: {r1.get('quality_score')})")
                for f in _COMPARE_FIELDS:
                    v1, v2 = r1.get(f), r2.get(f)
                    diff = "🔴 " if v1 != v2 else ""
                    st.markdown(f"{diff}`{f}`: {v1}")
            with col2:
                st.markdown(f"**Record B** (score: {r2.get('quality_score')})")
                for f in _COMPARE_FIELDS:
                    v1, v2 = r1.get(f), r2.get(f)
                    diff = "🔴 " if v1 != v2 else ""
                    st.markdown(f"{diff}`{f}`: {v2}")

            st.divider()
            ca, cb, cc = st.columns(3)

            with ca:
                if st.button("✅ Keep Both", key=f"keep_{i}"):
                    # Remove from session state so it doesn't reappear
                    st.session_state["dup_groups"] = [
                        g for j, g in enumerate(groups) if j != i
                    ]
                    st.success("Marked as distinct — removed from list.")
                    st.rerun()

            with cb:
                if st.button("🔀 Merge (keep A, archive B)", key=f"merge_{i}"):
                    _merge(r1["league_id"], r2["league_id"])
                    st.session_state["dup_groups"] = [
                        g for j, g in enumerate(groups) if j != i
                    ]
                    st.success(f"Merged. Kept {r1['league_id'][:8]}, archived {r2['league_id'][:8]}.")
                    st.rerun()

            with cc:
                if st.button("🗑️ Delete B (archive)", key=f"del_{i}"):
                    archive_league(r2["league_id"])
                    st.session_state["dup_groups"] = [
                        g for j, g in enumerate(groups) if j != i
                    ]
                    st.success(f"Archived record B ({r2['league_id'][:8]}).")
                    st.rerun()
```

### Step 2: Syntax check

```bash
python -c "import ast; ast.parse(open('streamlit_app/pages/merge_tool.py', encoding='utf-8').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

### Step 3: Commit

```bash
git add streamlit_app/pages/merge_tool.py
git commit -m "feat: add Merge Tool page for duplicate league resolution"
```

---

## Task 5: Full Test Suite

### Step 1: Run all tests

```bash
cd C:\Users\mathe\VSCode\aa_RecLeagueDB
python -m pytest tests/ -v
```

Expected: All tests pass (including the 12 new leagues_reader tests). No regressions.

### Step 2: Commit any fixes needed

If any tests fail, fix the implementation (not the tests), then:

```bash
git add <fixed files>
git commit -m "fix: resolve test regressions from leagues-views changes"
```

---

## Done

At this point:
- `leagues_reader.py` provides a tested, filtered query layer for all three pages
- **Leagues Viewer** — paginated browse with filters, detail expand, archive + re-scrape actions, CSV export
- **Data Quality** — summary metrics, field coverage bars, org/sport breakdowns, issue queue with bulk re-scrape
- **Merge Tool** — duplicate scan, side-by-side compare, Keep Both / Merge / Delete actions
- All pages filter to `listing_type = 'league'` only — drop-ins never appear

**Parking Lot:** Analytics tab in Leagues Viewer (pricing distribution, sport/day breakdowns) — deferred.
