# Organization View Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `base_domain` + `listing_type` columns to `leagues_metadata`, auto-classify records as `league` or `drop_in` using heuristics, and build a new "Org View" Streamlit page that groups URLs by domain with manual override support.

**Architecture:** Two new columns on `leagues_metadata` (Approach B). A pure utility module classifies listing type using keyword/price/duration rules. Integration in `writer._prepare_for_insert` ensures all new records are classified on write. A backfill script handles existing records. The Org View page groups by `base_domain` with inline edit controls.

**Tech Stack:** Python 3.10+, Supabase/PostgreSQL, Streamlit, `urllib.parse` (stdlib only — no new deps)

---

## Task 1: Database Migration

**Files:**
- Create: `migrations/004_add_domain_and_listing_type.sql`

**Step 1: Write the migration file**

```sql
-- migrations/004_add_domain_and_listing_type.sql
-- Date: 2026-03-02

ALTER TABLE public.leagues_metadata
  ADD COLUMN IF NOT EXISTS base_domain  TEXT,
  ADD COLUMN IF NOT EXISTS listing_type TEXT DEFAULT 'unknown'
    CONSTRAINT listing_type_values CHECK (listing_type IN ('league', 'drop_in', 'unknown'));

CREATE INDEX IF NOT EXISTS idx_leagues_base_domain  ON public.leagues_metadata(base_domain);
CREATE INDEX IF NOT EXISTS idx_leagues_listing_type ON public.leagues_metadata(listing_type);
```

**Step 2: Apply migration in Supabase**

Open Supabase SQL editor → paste and run the migration.
Verify: `SELECT column_name FROM information_schema.columns WHERE table_name = 'leagues_metadata' AND column_name IN ('base_domain', 'listing_type');`
Expected: 2 rows returned.

**Step 3: Commit**

```bash
git add migrations/004_add_domain_and_listing_type.sql
git commit -m "feat: add base_domain and listing_type columns to leagues_metadata"
```

---

## Task 2: Domain Extractor Utility

**Files:**
- Create: `src/utils/domain_extractor.py`
- Create: `tests/test_domain_extractor.py`

**Step 1: Write the failing tests**

```python
# tests/test_domain_extractor.py
import pytest
from src.utils.domain_extractor import extract_base_domain


def test_strips_www():
    assert extract_base_domain("https://www.javelin.com/calgary/vball") == "javelin.com"


def test_strips_scheme():
    assert extract_base_domain("http://torontossc.com/leagues") == "torontossc.com"


def test_subdomain_stripped():
    assert extract_base_domain("https://register.zogculture.com/page") == "zogculture.com"


def test_path_only_domain():
    assert extract_base_domain("https://javelin.com") == "javelin.com"


def test_none_returns_empty():
    assert extract_base_domain(None) == ""


def test_empty_string_returns_empty():
    assert extract_base_domain("") == ""


def test_invalid_url_returns_netloc_best_effort():
    # non-URL string — return as-is (best effort)
    result = extract_base_domain("not-a-url")
    assert isinstance(result, str)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_domain_extractor.py -v
```
Expected: `ModuleNotFoundError` or `ImportError`.

**Step 3: Write minimal implementation**

```python
# src/utils/domain_extractor.py
"""Utility for extracting the base domain from a URL."""
from urllib.parse import urlparse


def extract_base_domain(url: str | None) -> str:
    """Return the base domain from a URL, stripping www. and subdomains.

    Examples:
        "https://www.javelin.com/calgary/vball" -> "javelin.com"
        "https://register.zogculture.com/page"  -> "zogculture.com"

    Args:
        url: A URL string, or None.

    Returns:
        Base domain string, e.g. "javelin.com". Empty string if url is None/empty/invalid.
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        netloc = parsed.netloc or parsed.path  # fallback for schemeless strings
        # Strip port if present
        netloc = netloc.split(":")[0]
        # Strip www. prefix
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Keep only last two parts of subdomain (e.g. register.zogculture.com -> zogculture.com)
        parts = netloc.split(".")
        if len(parts) > 2:
            netloc = ".".join(parts[-2:])
        return netloc.lower()
    except Exception:
        return ""
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_domain_extractor.py -v
```
Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
git add src/utils/domain_extractor.py tests/test_domain_extractor.py
git commit -m "feat: add domain_extractor utility"
```

---

## Task 3: Listing Type Classifier

**Files:**
- Create: `src/utils/listing_classifier.py`
- Create: `tests/test_listing_classifier.py`

**Step 1: Write the failing tests**

```python
# tests/test_listing_classifier.py
import pytest
from src.utils.listing_classifier import classify_listing_type


# --- Drop-in via keywords ---

def test_dropin_keyword_drop_in():
    assert classify_listing_type({"league_name": "Friday Drop-In Volleyball"}) == "drop_in"

def test_dropin_keyword_pickup():
    assert classify_listing_type({"division_name": "Pick-Up Basketball"}) == "drop_in"

def test_dropin_keyword_one_time():
    assert classify_listing_type({"league_name": "One-Time Social Night"}) == "drop_in"

def test_dropin_keyword_case_insensitive():
    assert classify_listing_type({"league_name": "OPEN PLAY TENNIS"}) == "drop_in"

def test_dropin_keyword_casual():
    assert classify_listing_type({"division_name": "Casual Badminton"}) == "drop_in"


# --- Drop-in via duration + price ---

def test_dropin_short_duration_low_price():
    assert classify_listing_type({"num_weeks": 1, "individual_fee": 15.0}) == "drop_in"

def test_dropin_null_weeks_low_price():
    assert classify_listing_type({"num_weeks": None, "individual_fee": 10.0}) == "drop_in"

def test_not_dropin_short_duration_high_price():
    # num_weeks=1 but price is $50 — not a drop-in
    result = classify_listing_type({"num_weeks": 1, "individual_fee": 50.0})
    assert result != "drop_in"

def test_not_dropin_no_price_info():
    # num_weeks=None, no price — not enough signal for drop_in
    result = classify_listing_type({"num_weeks": None})
    assert result == "unknown"


# --- League ---

def test_league_multi_week():
    assert classify_listing_type({"num_weeks": 10}) == "league"

def test_league_has_team_fee():
    assert classify_listing_type({"team_fee": 800.0}) == "league"

def test_league_four_weeks():
    assert classify_listing_type({"num_weeks": 4}) == "league"


# --- Unknown ---

def test_unknown_empty_record():
    assert classify_listing_type({}) == "unknown"

def test_unknown_no_relevant_fields():
    assert classify_listing_type({"organization_name": "TSSC", "venue_name": "Lamport"}) == "unknown"


# --- Keyword takes priority over other rules ---

def test_keyword_beats_league_signal():
    # Has team_fee but also drop-in keyword → drop_in wins
    assert classify_listing_type({"league_name": "Drop-In Night", "team_fee": 200.0}) == "drop_in"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_listing_classifier.py -v
```
Expected: `ModuleNotFoundError`.

**Step 3: Write minimal implementation**

```python
# src/utils/listing_classifier.py
"""Rule-based listing type classifier for leagues_metadata records."""
import re

_DROPIN_KEYWORDS = re.compile(
    r"drop.?in|pick.?up|one.?time|casual|social night|open play",
    re.IGNORECASE,
)

_DROPIN_PRICE_THRESHOLD = 20.0  # USD/CAD
_LEAGUE_MIN_WEEKS = 4


def classify_listing_type(record: dict) -> str:
    """Classify a league record as 'league', 'drop_in', or 'unknown'.

    Rules (first match wins):
      1. Keyword match in league_name or division_name → drop_in
      2. num_weeks is 1 or None AND individual_fee < $20 → drop_in
      3. num_weeks >= 4 OR team_fee > 0 → league
      4. No match → unknown

    Args:
        record: Dict with any subset of leagues_metadata fields.

    Returns:
        One of: 'league', 'drop_in', 'unknown'
    """
    name_fields = " ".join(
        str(record.get(f) or "") for f in ("league_name", "division_name")
    )

    # Rule 1: keyword match
    if _DROPIN_KEYWORDS.search(name_fields):
        return "drop_in"

    num_weeks = record.get("num_weeks")
    individual_fee = record.get("individual_fee")
    team_fee = record.get("team_fee")

    # Rule 2: short/no duration + cheap price
    short_duration = num_weeks is None or num_weeks <= 1
    cheap = individual_fee is not None and individual_fee < _DROPIN_PRICE_THRESHOLD
    if short_duration and cheap:
        return "drop_in"

    # Rule 3: multi-week or team pricing → league
    if (num_weeks is not None and num_weeks >= _LEAGUE_MIN_WEEKS) or (team_fee is not None and team_fee > 0):
        return "league"

    return "unknown"
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_listing_classifier.py -v
```
Expected: All 15 tests PASS.

**Step 5: Commit**

```bash
git add src/utils/listing_classifier.py tests/test_listing_classifier.py
git commit -m "feat: add listing_type classifier utility"
```

---

## Task 4: Integrate into writer.py

**Files:**
- Modify: `src/database/writer.py`

**Step 1: Write an integration test**

Add this test to `tests/test_writer.py` (or create if it doesn't exist):

```python
# In tests/test_writer.py (add this test)
from unittest.mock import patch, MagicMock
from src.database.writer import _prepare_for_insert


def test_prepare_for_insert_sets_base_domain():
    data = {
        "organization_name": "Javelin",
        "url_scraped": "https://www.javelin.com/calgary/vball",
        "sport_season_code": "V10",
        "identifying_fields_pct": 75,
    }
    result = _prepare_for_insert(data)
    assert result["base_domain"] == "javelin.com"


def test_prepare_for_insert_sets_listing_type_league():
    data = {
        "organization_name": "TSSC",
        "url_scraped": "https://torontossc.com",
        "sport_season_code": "S10",
        "num_weeks": 10,
        "identifying_fields_pct": 75,
    }
    result = _prepare_for_insert(data)
    assert result["listing_type"] == "league"


def test_prepare_for_insert_sets_listing_type_dropin():
    data = {
        "organization_name": "ZogSports",
        "url_scraped": "https://zogsports.com",
        "sport_season_code": "S10",
        "league_name": "Friday Drop-In",
        "identifying_fields_pct": 75,
    }
    result = _prepare_for_insert(data)
    assert result["listing_type"] == "drop_in"


def test_prepare_for_insert_unknown_listing_type():
    data = {
        "organization_name": "Mystery Org",
        "url_scraped": "https://example.com",
        "sport_season_code": "S10",
        "identifying_fields_pct": 75,
    }
    result = _prepare_for_insert(data)
    assert result["listing_type"] == "unknown"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_writer.py::test_prepare_for_insert_sets_base_domain -v
pytest tests/test_writer.py::test_prepare_for_insert_sets_listing_type_league -v
```
Expected: FAIL — `base_domain` and `listing_type` not set.

**Step 3: Edit `src/database/writer.py`**

Add imports at top of file (after existing imports):

```python
from src.utils.domain_extractor import extract_base_domain
from src.utils.listing_classifier import classify_listing_type
```

In `_prepare_for_insert`, add these two lines just before the `# Add timestamps` block:

```python
    # Enrich with domain and listing type
    prepared["base_domain"] = extract_base_domain(prepared.get("url_scraped"))
    if not prepared.get("listing_type"):
        prepared["listing_type"] = classify_listing_type(prepared)
```

Also add `"base_domain"` and `"listing_type"` to the `schema_fields` set (around line 320):

```python
        "base_domain",           # NEW
        "listing_type",          # NEW
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_writer.py -v
```
Expected: All writer tests PASS.

**Step 5: Commit**

```bash
git add src/database/writer.py
git commit -m "feat: set base_domain and listing_type on insert in writer"
```

---

## Task 5: Backfill Script

**Files:**
- Create: `scripts/backfill_listing_type.py`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""One-time backfill: set base_domain and listing_type on existing records.

Usage:
    python scripts/backfill_listing_type.py           # dry-run
    python scripts/backfill_listing_type.py --write   # apply to DB
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.database.supabase_client import get_client
from src.utils.domain_extractor import extract_base_domain
from src.utils.listing_classifier import classify_listing_type

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def backfill(write: bool = False) -> None:
    client = get_client()

    # Fetch all records needing backfill
    result = (
        client.table("leagues_metadata")
        .select("league_id, url_scraped, league_name, division_name, num_weeks, team_fee, individual_fee, base_domain, listing_type")
        .execute()
    )
    rows = result.data or []
    logger.info(f"Fetched {len(rows)} total records")

    to_update = []
    for row in rows:
        new_domain = extract_base_domain(row.get("url_scraped"))
        new_type = classify_listing_type(row) if row.get("listing_type") in (None, "unknown") else row["listing_type"]
        needs_update = (row.get("base_domain") != new_domain) or (row.get("listing_type") != new_type)
        if needs_update:
            to_update.append({
                "league_id": row["league_id"],
                "base_domain": new_domain,
                "listing_type": new_type,
            })

    counts = {"league": 0, "drop_in": 0, "unknown": 0}
    for item in to_update:
        counts[item["listing_type"]] += 1

    logger.info(f"Records to update: {len(to_update)}")
    logger.info(f"  league={counts['league']}  drop_in={counts['drop_in']}  unknown={counts['unknown']}")

    if not write:
        logger.info("DRY RUN — pass --write to apply changes")
        return

    # Batch upsert
    for i in range(0, len(to_update), BATCH_SIZE):
        batch = to_update[i:i + BATCH_SIZE]
        client.table("leagues_metadata").upsert(batch, on_conflict="league_id").execute()
        logger.info(f"  Updated batch {i // BATCH_SIZE + 1} ({len(batch)} records)")

    logger.info("Backfill complete.")


if __name__ == "__main__":
    write_mode = "--write" in sys.argv
    backfill(write=write_mode)
```

**Step 2: Run dry-run to verify it works**

```bash
python scripts/backfill_listing_type.py
```
Expected: Prints record counts with `DRY RUN` message. No DB changes.

**Step 3: Apply if counts look right**

```bash
python scripts/backfill_listing_type.py --write
```
Expected: Prints batch progress and `Backfill complete.`

**Step 4: Commit**

```bash
git add scripts/backfill_listing_type.py
git commit -m "feat: add backfill_listing_type script for existing records"
```

---

## Task 6: Organization View Streamlit Page

**Files:**
- Create: `streamlit_app/pages/org_view.py`

**Step 1: Write the page**

```python
# streamlit_app/pages/org_view.py
"""Organization View — browse leagues grouped by base domain."""
from __future__ import annotations

import streamlit as st
from src.database.supabase_client import get_client


_LISTING_OPTIONS = ["league", "drop_in", "unknown"]
_LISTING_LABELS = {"league": "✅ League", "drop_in": "🎯 Drop-in", "unknown": "❓ Unknown"}


def _load_data() -> list[dict]:
    client = get_client()
    result = (
        client.table("leagues_metadata")
        .select("league_id, organization_name, url_scraped, base_domain, listing_type, league_name, division_name, sport_season_code")
        .eq("is_archived", False)
        .order("base_domain")
        .execute()
    )
    return result.data or []


def _group_by_domain(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        domain = row.get("base_domain") or "unknown"
        groups.setdefault(domain, []).append(row)
    return dict(sorted(groups.items()))


def _group_by_url(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        url = row.get("url_scraped") or "unknown"
        groups.setdefault(url, []).append(row)
    return groups


def _update_listing_type_for_url(url: str, new_type: str) -> None:
    client = get_client()
    client.table("leagues_metadata").update({"listing_type": new_type}).eq("url_scraped", url).execute()


def _rename_domain(old_domain: str, new_domain: str) -> None:
    client = get_client()
    client.table("leagues_metadata").update({"base_domain": new_domain}).eq("base_domain", old_domain).execute()


def _merge_domains(source: str, target: str) -> None:
    """Reassign all records from source domain to target domain."""
    client = get_client()
    client.table("leagues_metadata").update({"base_domain": target}).eq("base_domain", source).execute()


def render() -> None:
    st.title("Organization View")
    st.caption("Browse scraped URLs grouped by organization domain.")

    try:
        rows = _load_data()
    except Exception as e:
        st.error(f"Could not load data: {e}")
        return

    if not rows:
        st.info("No records found. Run the scraper first.")
        return

    groups = _group_by_domain(rows)
    all_domains = list(groups.keys())

    # --- Summary metrics ---
    total_leagues = sum(1 for r in rows if r.get("listing_type") == "league")
    total_dropins = sum(1 for r in rows if r.get("listing_type") == "drop_in")
    total_unknown = sum(1 for r in rows if r.get("listing_type") == "unknown")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Organizations", len(groups))
    c2.metric("Leagues", total_leagues)
    c3.metric("Drop-ins", total_dropins)
    c4.metric("Unclassified", total_unknown)

    st.divider()

    # --- Filters ---
    col_search, col_filter = st.columns([3, 1])
    search = col_search.text_input("Search by org name or domain", placeholder="e.g. javelin")
    type_filter = col_filter.selectbox("Filter by type", ["All", "League", "Drop-in", "Unknown"])

    type_map = {"All": None, "League": "league", "Drop-in": "drop_in", "Unknown": "unknown"}
    active_type = type_map[type_filter]

    st.divider()

    # --- Domain merge tool ---
    with st.expander("Merge two domain groups"):
        col_a, col_b = st.columns(2)
        src = col_a.selectbox("Source domain (will be renamed)", all_domains, key="merge_src")
        tgt = col_b.selectbox("Target domain (keep this name)", all_domains, key="merge_tgt")
        if st.button("Merge domains", key="do_merge"):
            if src == tgt:
                st.warning("Source and target are the same.")
            else:
                _merge_domains(src, tgt)
                st.success(f"Merged '{src}' → '{tgt}'. Refresh to see changes.")
                st.rerun()

    st.divider()

    # --- Per-domain groups ---
    for domain, domain_rows in groups.items():
        if search and search.lower() not in domain.lower() and not any(
            search.lower() in (r.get("organization_name") or "").lower() for r in domain_rows
        ):
            continue

        url_groups = _group_by_url(domain_rows)

        # Filter by listing type if active
        if active_type:
            visible_urls = {
                url: urrows for url, urrows in url_groups.items()
                if any(r.get("listing_type") == active_type for r in urrows)
            }
        else:
            visible_urls = url_groups

        if not visible_urls:
            continue

        type_counts = {t: sum(1 for r in domain_rows if r.get("listing_type") == t) for t in _LISTING_OPTIONS}
        league_bar = "█" * type_counts["league"]
        dropin_bar = "█" * type_counts["drop_in"]
        header = (
            f"**{domain}**  ({len(url_groups)} URL{'s' if len(url_groups) != 1 else ''})  "
            f"  League `{league_bar or '–'}` {type_counts['league']}  "
            f"  Drop-in `{dropin_bar or '–'}` {type_counts['drop_in']}"
        )

        with st.expander(header):
            # Rename domain
            with st.form(key=f"rename_{domain}"):
                new_name = st.text_input("Rename this domain group", value=domain, key=f"rename_val_{domain}")
                if st.form_submit_button("Rename"):
                    if new_name and new_name != domain:
                        _rename_domain(domain, new_name)
                        st.success(f"Renamed to '{new_name}'. Refresh to see changes.")
                        st.rerun()

            st.divider()

            for url, url_rows in visible_urls.items():
                current_type = url_rows[0].get("listing_type") or "unknown"
                label = _LISTING_LABELS.get(current_type, current_type)
                col_url, col_type, col_edit = st.columns([5, 2, 2])
                col_url.markdown(f"`{url[:70]}`  ({len(url_rows)} record{'s' if len(url_rows) != 1 else ''})")
                col_type.markdown(label)

                new_type = col_edit.selectbox(
                    "Change type",
                    _LISTING_OPTIONS,
                    index=_LISTING_OPTIONS.index(current_type),
                    key=f"type_{url}",
                    label_visibility="collapsed",
                )
                if new_type != current_type:
                    _update_listing_type_for_url(url, new_type)
                    st.success(f"Updated {url[:50]} → {new_type}")
                    st.rerun()
```

**Step 2: Smoke-test manually**

```bash
cd streamlit_app && streamlit run app.py
```
Navigate to Org View in the sidebar. Verify:
- Domain groups appear
- Counts match
- Rename/merge forms are visible

**Step 3: Commit**

```bash
git add streamlit_app/pages/org_view.py
git commit -m "feat: add Organization View Streamlit page"
```

---

## Task 7: Wire Org View into Navigation

**Files:**
- Modify: `streamlit_app/app.py`

**Step 1: Add Org View to PAGES dict and sidebar**

In `app.py`, find the `PAGES` dict and add:

```python
    "🏢 Org View":               ("manage",  "org_view"),
```

In the sidebar loop for Data Management labels, add `"🏢 Org View"`:

```python
    for label in ["🗂️ Leagues Viewer", "📊 Data Quality", "🔀 Merge Tool", "📍 Venues Enricher", "🏢 Org View"]:
```

At the bottom of the page dispatch block, add:

```python
elif module_name == "org_view":
    try:
        from pages import org_view
        org_view.render()
    except ImportError:
        st.info("🏢 Org View — coming soon.")
```

**Step 2: Verify navigation works**

```bash
cd streamlit_app && streamlit run app.py
```
Click "🏢 Org View" in sidebar. Confirm page renders without error.

**Step 3: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat: add Org View to app navigation"
```

---

## Task 8: Run Full Test Suite

**Step 1: Run all tests**

```bash
pytest tests/ -v
```
Expected: All tests PASS. No regressions.

**Step 2: Commit if any fixes were needed**

```bash
git add -p
git commit -m "fix: resolve any test regressions from org-view changes"
```

---

## Done

At this point:
- `base_domain` and `listing_type` are set on all new records at insert time
- Existing records are backfilled
- Org View groups URLs by domain with listing type badges, rename, merge, and inline type overrides

**Future work (Parking Lot):** League merge tool within Org View — rename + deduplicate records sharing the same URL.
