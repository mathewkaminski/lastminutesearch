# Code Cleanup & Streamlit Reorganization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the dead HTML extraction path, fix all broken imports, reorganize Streamlit navigation into Core Workflow / Diagnostics sections, and upgrade Leagues Viewer with inline edits and group-by-URL.

**Architecture:** Delete 12 dead files, inline `_clean_html` into `vector_store.py`, remove `fetch_html_multi_page` from `html_fetcher.py`, then rewrite `app.py` navigation structure and upgrade `leagues_viewer.py` with `st.data_editor()` for writes and `st.expander()` for group-by-URL.

**Tech Stack:** Python 3.10+, Streamlit, Supabase Python client, pytest, BeautifulSoup4

---

## File Structure

**Delete (12 files):**
- `src/extractors/league_extractor.py` — GPT-4o HTML extraction, replaced by yaml_extractor
- `src/extractors/html_preprocessor.py` — only consumed by league_extractor
- `src/scraper/html_aggregator.py` — HTML aggregation, replaced by YAML path
- `src/scraper/page_classifier.py` — old classifier, replaced by page_type_classifier
- `src/scraper/link_discoverer.py` — old link extraction, replaced by yaml_link_parser
- `src/scraper/multi_page_navigator.py` — orchestrates deleted files above; dead code
- `streamlit_app/pages/url_merge.py` — no longer needed
- `scripts/extract_pipeline.py` — old HTML pipeline entry point
- `tests/test_extraction.py` — tests deleted code
- `tests/test_link_discoverer.py` — tests deleted code
- `tests/test_html_preprocessor.py` — imports html_preprocessor (deleted)
- `tests/test_preprocessing.py` — imports html_preprocessor (deleted)

**Modify (4 files):**
- `src/database/vector_store.py` — replace `from src.extractors.league_extractor import _clean_html` with inline function
- `src/scraper/html_fetcher.py` — remove `fetch_html_multi_page()` function and its lazy `multi_page_navigator` import
- `streamlit_app/app.py` — remove url_merge, reorganize nav into Core Workflow / Diagnostics
- `streamlit_app/pages/leagues_viewer.py` — inline edits via `st.data_editor()`, group-by-URL via `st.expander()`

**Test file (new):**
- `tests/test_vector_store_clean_html.py` — smoke test for inlined `_clean_html`
- `tests/test_leagues_viewer_diff.py` — unit test for edit-diff helper

---

## Chunk 1: Code Cleanup

### Task 1: Inline `_clean_html` into `vector_store.py`

`_clean_html` is currently defined in `league_extractor.py` (line 142) and imported at `vector_store.py:14`. Once `league_extractor.py` is deleted that import breaks. The fix: copy the function directly into `vector_store.py` and drop the import.

**Files:**
- Modify: `src/database/vector_store.py`
- Create: `tests/test_vector_store_clean_html.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vector_store_clean_html.py
from src.database.vector_store import _clean_html


def test_clean_html_strips_tags():
    html = "<p>Hello <b>world</b></p><script>alert(1)</script>"
    result = _clean_html(html)
    assert "Hello world" in result
    assert "<" not in result
    assert "alert" not in result


def test_clean_html_collapses_whitespace():
    html = "<p>  too   many   spaces  </p>"
    result = _clean_html(html)
    assert "  " not in result


def test_clean_html_handles_empty():
    assert _clean_html("") == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd VSCode/aa_RecLeagueDB && python -m pytest tests/test_vector_store_clean_html.py -v
```

Expected: `ImportError` — `_clean_html` not yet defined in `vector_store.py`

- [ ] **Step 3: Edit `vector_store.py`**

Replace line 14:
```python
from src.extractors.league_extractor import _clean_html
```

With the inline import and function. Add `from bs4 import BeautifulSoup` to the imports block (it is already available in requirements — BeautifulSoup4 is a project dependency), then paste the function body after the `logger` line:

```python
# --- no import from league_extractor ---

# (add to imports at top of file)
from bs4 import BeautifulSoup


def _clean_html(html: str) -> str:
    """Clean HTML to plain text for embedding.

    Removes script/style/noscript tags, extracts visible text,
    collapses whitespace.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        cleaned = "\n".join(lines)
        return " ".join(cleaned.split())
    except Exception as e:
        logger.warning(f"Error cleaning HTML: {e}, returning raw text")
        return html
```

Place `_clean_html` directly after the `logger = logging.getLogger(__name__)` line (before `EMBEDDING_MODEL`).

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_vector_store_clean_html.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/database/vector_store.py tests/test_vector_store_clean_html.py
git commit -m "refactor: inline _clean_html into vector_store, remove league_extractor dependency"
```

---

### Task 2: Delete legacy extraction files

Delete all dead files now that the import they provided (`_clean_html`) is no longer needed.

**Files:**
- Delete: `src/extractors/league_extractor.py`
- Delete: `src/extractors/html_preprocessor.py`
- Delete: `src/scraper/html_aggregator.py`
- Delete: `src/scraper/page_classifier.py`
- Delete: `src/scraper/link_discoverer.py`
- Delete: `src/scraper/multi_page_navigator.py`
- Delete: `streamlit_app/pages/url_merge.py`
- Delete: `scripts/extract_pipeline.py`
- Delete: `tests/test_extraction.py`
- Delete: `tests/test_link_discoverer.py`
- Delete: `tests/test_html_preprocessor.py`
- Delete: `tests/test_preprocessing.py`
- Delete: `tests/test_phase3.py` — imports `fetch_html` from html_fetcher (old HTML path test)
- Delete: `tests/test_phase3_quick.py` — imports `fetch_html_multi_page` (deleted in Task 3)

- [ ] **Step 1: Delete the files**

```bash
cd VSCode/aa_RecLeagueDB
rm src/extractors/league_extractor.py
rm src/extractors/html_preprocessor.py
rm src/scraper/html_aggregator.py
rm src/scraper/page_classifier.py
rm src/scraper/link_discoverer.py
rm src/scraper/multi_page_navigator.py
rm streamlit_app/pages/url_merge.py
rm scripts/extract_pipeline.py
rm tests/test_extraction.py
rm tests/test_link_discoverer.py
rm tests/test_html_preprocessor.py
rm tests/test_preprocessing.py
rm tests/test_phase3.py
rm tests/test_phase3_quick.py
```

- [ ] **Step 2: Verify no remaining imports of deleted modules**

```bash
grep -rn "league_extractor\|html_preprocessor\|html_aggregator\|page_classifier\|link_discoverer\|multi_page_navigator\|url_merge\|extract_pipeline" \
    src/ streamlit_app/ scripts/ tests/ \
    --include="*.py"
```

Expected: zero results (or only references that aren't `import` statements).

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: delete legacy HTML extraction path (league_extractor, html_preprocessor, html_aggregator, page_classifier, link_discoverer, multi_page_navigator, url_merge, extract_pipeline)"
```

---

### Task 3: Remove `fetch_html_multi_page` from `html_fetcher.py`

`html_fetcher.py` contains `fetch_html_multi_page()` (line 26) which lazily imports `MultiPageNavigator` (line 60). `MultiPageNavigator` is now deleted. Nothing active calls `fetch_html_multi_page()` — its only caller was `extract_pipeline.py` (deleted in Task 2). Remove the dead function.

**Files:**
- Modify: `src/scraper/html_fetcher.py`

- [ ] **Step 1: Read `html_fetcher.py` to locate the function boundary**

Read `src/scraper/html_fetcher.py`. Confirm:
- `fetch_html_multi_page` starts at approximately line 26
- Function body ends before the next top-level `def` or class
- The lazy `from src.scraper.multi_page_navigator import MultiPageNavigator` is inside this function only

- [ ] **Step 2: Delete `fetch_html_multi_page` from `html_fetcher.py`**

Remove the entire `fetch_html_multi_page()` function definition (from its `def` line through the closing logic, including any helper functions it uses exclusively — `_cache_page` at line 126). Read the file carefully first to identify the exact line range.

After editing, run a quick import check:

```bash
python -c "from src.scraper.html_fetcher import fetch_html; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Verify no remaining reference to `multi_page_navigator` anywhere**

```bash
grep -rn "multi_page_navigator\|MultiPageNavigator" src/ scripts/ tests/ streamlit_app/ --include="*.py"
```

Expected: zero results

- [ ] **Step 4: Run existing tests to confirm nothing broke**

```bash
python -m pytest tests/ -v -x
```

Expected: all passing tests still pass. `test_phase3.py` and `test_phase3_quick.py` were deleted in Task 2 so they will not appear.

- [ ] **Step 5: Commit**

```bash
git add src/scraper/html_fetcher.py
git commit -m "chore: remove dead fetch_html_multi_page from html_fetcher"
```

---

## Chunk 2: Streamlit Reorganization + Leagues Viewer Upgrade

### Task 4: Reorganize Streamlit navigation

**File:** `streamlit_app/app.py`

Current navigation has two sections: "Search Pipeline" and "Data Management". The new structure separates into "Core Workflow" (campaign → queue → scraper → enrich → view → merge → venues) and "Diagnostics" (data quality, org view). Remove URL Merge entirely.

**Files:**
- Modify: `streamlit_app/app.py`

- [ ] **Step 1: Edit `app.py` — rewrite `PAGES` dict and sidebar navigation**

Replace the `PAGES` dict (lines 39–52) with:

```python
PAGES = {
    # Core Workflow
    "Campaign Manager":  ("search", "campaign_manager"),
    "Queue Monitor":     ("search", "queue_monitor"),
    "Scraper UI":        ("search", "scraper_ui"),
    "Fill In Leagues":   ("search", "fill_in_leagues"),
    "Leagues Viewer":    ("manage", "leagues_viewer"),
    "League Merge":      ("manage", "league_merge"),
    "Venues Enricher":   ("manage", "venues_enricher"),
    # Diagnostics
    "Data Quality":      ("manage", "data_quality"),
    "Org View":          ("manage", "org_view"),
}
```

Replace the `with st.sidebar:` block (lines 54–63) with:

```python
with st.sidebar:
    st.title("Navigation")
    st.markdown("**— Core Workflow —**")
    for label in [
        "Campaign Manager", "Queue Monitor", "Scraper UI",
        "Fill In Leagues", "Leagues Viewer", "League Merge", "Venues Enricher",
    ]:
        if st.button(label, key=f"nav_{label}", use_container_width=True):
            st.session_state.current_page = label
    st.divider()
    st.markdown("**— Diagnostics —**")
    for label in ["Data Quality", "Org View"]:
        if st.button(label, key=f"nav_{label}", use_container_width=True):
            st.session_state.current_page = label
```

Update `st.session_state.current_page` default (line 66) to `"Campaign Manager"`.

Remove the `elif module_name == "url_merge":` block (lines 111–113).

No other changes to the `elif` dispatch chain are needed — it already operates on `module_name` (the second element of the `PAGES` tuple), not on the label key. Removing emojis from `PAGES` keys does not affect dispatch logic.

- [ ] **Step 2: Verify app starts cleanly (import-only check)**

```bash
cd VSCode/aa_RecLeagueDB
python -c "
import sys
sys.path.insert(0, 'streamlit_app')
# Verify app.py imports and pages dict parse without error
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location('app', 'streamlit_app/app.py')
# just parse, don't execute st calls
"
```

A cleaner check — verify none of the active page modules have broken imports:

```bash
python -c "from streamlit_app.pages import campaign_manager; print('campaign_manager OK')" 2>&1 | head -5
python -c "from streamlit_app.pages import queue_monitor; print('queue_monitor OK')" 2>&1 | head -5
python -c "from streamlit_app.pages import leagues_viewer; print('leagues_viewer OK')" 2>&1 | head -5
python -c "from streamlit_app.pages import league_merge; print('league_merge OK')" 2>&1 | head -5
```

Expected: each prints `OK`

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat: reorganize Streamlit nav into Core Workflow / Diagnostics, remove URL Merge"
```

---

### Task 5: Leagues Viewer — inline edits via `st.data_editor()`

Currently `leagues_viewer.py` uses `st.dataframe()` (read-only). Replace the table view with `st.data_editor()` that lets users edit any of the 18 editable league data fields. On change, diff edited vs. original and call `writer.update_league()` for each modified row.

**Files:**
- Modify: `streamlit_app/pages/leagues_viewer.py`
- Create: `tests/test_leagues_viewer_diff.py`

The edit-diff logic should be extracted into a pure function (`_diff_rows`) that can be unit-tested independently of Streamlit.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_leagues_viewer_diff.py
import pandas as pd
from streamlit_app.pages.leagues_viewer import _diff_rows


_EDITABLE_COLS = [
    "organization_name", "sport_season_code", "season_year",
    "season_start_date", "season_end_date", "day_of_week", "start_time",
    "num_weeks", "venue_name", "competition_level", "gender_eligibility",
    "team_fee", "individual_fee", "registration_deadline",
    "num_teams", "slots_left", "has_referee", "requires_insurance",
]


def _make_df(rows):
    return pd.DataFrame(rows)


def test_diff_rows_detects_single_change():
    original = _make_df([
        {"league_id": "aaa", "organization_name": "Old Name", "team_fee": 100},
    ])
    edited = _make_df([
        {"league_id": "aaa", "organization_name": "New Name", "team_fee": 100},
    ])
    result = _diff_rows(original, edited, editable_cols=["organization_name", "team_fee"])
    assert result == [("aaa", {"organization_name": "New Name"})]


def test_diff_rows_no_change():
    original = _make_df([{"league_id": "aaa", "organization_name": "Same"}])
    edited = _make_df([{"league_id": "aaa", "organization_name": "Same"}])
    assert _diff_rows(original, edited, editable_cols=["organization_name"]) == []


def test_diff_rows_multiple_fields_changed():
    original = _make_df([{"league_id": "bbb", "team_fee": 100, "num_weeks": 10}])
    edited = _make_df([{"league_id": "bbb", "team_fee": 150, "num_weeks": 12}])
    result = _diff_rows(original, edited, editable_cols=["team_fee", "num_weeks"])
    assert len(result) == 1
    league_id, patches = result[0]
    assert league_id == "bbb"
    assert patches == {"team_fee": 150, "num_weeks": 12}


def test_diff_rows_multiple_rows():
    original = _make_df([
        {"league_id": "aaa", "venue_name": "Old"},
        {"league_id": "bbb", "venue_name": "Same"},
    ])
    edited = _make_df([
        {"league_id": "aaa", "venue_name": "New"},
        {"league_id": "bbb", "venue_name": "Same"},
    ])
    result = _diff_rows(original, edited, editable_cols=["venue_name"])
    assert len(result) == 1
    assert result[0][0] == "aaa"


def test_diff_rows_nan_both_null_is_no_change():
    """Two None/NaN values in same cell should not trigger a change."""
    original = _make_df([{"league_id": "aaa", "team_fee": None}])
    edited = _make_df([{"league_id": "aaa", "team_fee": None}])
    assert _diff_rows(original, edited, editable_cols=["team_fee"]) == []


def test_diff_rows_null_to_value_is_change():
    """Filling in a previously null cell should register as a change."""
    original = _make_df([{"league_id": "aaa", "team_fee": None}])
    edited = _make_df([{"league_id": "aaa", "team_fee": 200.0}])
    result = _diff_rows(original, edited, editable_cols=["team_fee"])
    assert result == [("aaa", {"team_fee": 200.0})]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_leagues_viewer_diff.py -v
```

Expected: `ImportError` — `_diff_rows` does not exist yet

- [ ] **Step 3: Add `_EDITABLE_COLS`, `_READ_ONLY_COLS`, and `_diff_rows` to `leagues_viewer.py`**

Add after the existing `_ALL_FIELDS` list:

```python
_EDITABLE_COLS = [
    "organization_name", "sport_season_code", "season_year",
    "season_start_date", "season_end_date", "day_of_week", "start_time",
    "num_weeks", "venue_name", "competition_level", "gender_eligibility",
    "team_fee", "individual_fee", "registration_deadline",
    "num_teams", "slots_left", "has_referee", "requires_insurance",
]

_READ_ONLY_COLS = [
    "league_id", "url_scraped", "base_domain",
    "quality_score", "created_at", "updated_at",
]


def _diff_rows(
    original_df: "pd.DataFrame",
    edited_df: "pd.DataFrame",
    editable_cols: list[str],
) -> list[tuple[str, dict]]:
    """Return list of (league_id, {field: new_value}) for changed rows."""
    import pandas as pd

    def _is_null(v) -> bool:
        """True for None, float NaN, and pandas NA/NaT."""
        if v is None:
            return True
        try:
            return bool(pd.isna(v))
        except (TypeError, ValueError):
            return False

    changes = []
    for idx in range(len(original_df)):
        league_id = original_df.iloc[idx]["league_id"]
        patches = {}
        for col in editable_cols:
            if col not in original_df.columns or col not in edited_df.columns:
                continue
            orig_val = original_df.iloc[idx][col]
            edit_val = edited_df.iloc[idx][col]
            orig_null = _is_null(orig_val)
            edit_null = _is_null(edit_val)
            if orig_null and edit_null:
                continue  # both null — no change
            if orig_null != edit_null or orig_val != edit_val:
                patches[col] = None if edit_null else edit_val
        if patches:
            changes.append((league_id, patches))
    return changes
```

- [ ] **Step 4: Run test to verify `_diff_rows` tests pass**

```bash
python -m pytest tests/test_leagues_viewer_diff.py -v
```

Expected: 6 PASS

- [ ] **Step 5: Add `import pandas as pd` and update `render()` to use `st.data_editor()`**

At the top of `leagues_viewer.py`, add:
```python
import pandas as pd
from src.database.writer import update_league
```

Replace the existing table section in `render()` (the `st.dataframe(display_rows, ...)` call at line 118) with:

```python
    # --- Editable table ---
    all_cols = _EDITABLE_COLS + _READ_ONLY_COLS
    editor_rows = [{col: r.get(col) for col in all_cols} for r in rows]
    original_df = pd.DataFrame(editor_rows)

    edited_df = st.data_editor(
        original_df,
        disabled=list(_READ_ONLY_COLS),
        use_container_width=True,
        key="league_editor",
        num_rows="fixed",
    )

    if st.button("Save changes"):
        changes = _diff_rows(original_df, edited_df, _EDITABLE_COLS)
        if not changes:
            st.info("No changes detected.")
        else:
            errors = []
            for league_id, patches in changes:
                try:
                    update_league(league_id, patches)
                except Exception as e:
                    errors.append(f"{league_id[:8]}: {e}")
            if errors:
                st.error(f"Save failed for {len(errors)} record(s):\n" + "\n".join(errors))
            else:
                st.success(f"Saved {len(changes)} change(s).")
                st.rerun()
```

- [ ] **Step 6: Run diff tests again to confirm nothing broke**

```bash
python -m pytest tests/test_leagues_viewer_diff.py -v
```

Expected: 6 PASS

- [ ] **Step 7: Commit**

```bash
git add streamlit_app/pages/leagues_viewer.py tests/test_leagues_viewer_diff.py
git commit -m "feat: add inline edit to Leagues Viewer via st.data_editor + _diff_rows helper"
```

---

### Task 6: Leagues Viewer — group-by-URL toggle

Add a "Group by URL" checkbox. When enabled, rows are grouped under collapsible `st.expander()` sections per unique `url_scraped`. The group view is read-only (plain `st.dataframe`); the flat view (Task 5) has the editable table.

**Files:**
- Modify: `streamlit_app/pages/leagues_viewer.py`

No new unit test needed — the grouping is purely presentational; the diff tests in Task 5 cover the underlying logic.

- [ ] **Step 1: Add group-by toggle to `render()`**

Add the toggle just after the `st.metric` line and before the CSV export button:

```python
    group_by_url = st.checkbox("Group by URL", value=False)
```

- [ ] **Step 2: Branch rendering on the toggle**

After the CSV export + divider, replace the current table + detail section with a conditional branch:

```python
    if group_by_url:
        _render_grouped(rows)
    else:
        _render_flat(rows)
```

- [ ] **Step 3: Extract `_render_flat` (current behavior)**

Move the existing editable table block (from Task 5) into:

```python
def _render_flat(rows: list[dict]) -> None:
    """Render flat editable table view."""
    all_cols = _EDITABLE_COLS + _READ_ONLY_COLS
    editor_rows = [{col: r.get(col) for col in all_cols} for r in rows]
    original_df = pd.DataFrame(editor_rows)

    edited_df = st.data_editor(
        original_df,
        disabled=list(_READ_ONLY_COLS),
        use_container_width=True,
        key="league_editor",
        num_rows="fixed",
    )

    if st.button("Save changes"):
        changes = _diff_rows(original_df, edited_df, _EDITABLE_COLS)
        if not changes:
            st.info("No changes detected.")
        else:
            errors = []
            for league_id, patches in changes:
                try:
                    update_league(league_id, patches)
                except Exception as e:
                    errors.append(f"{league_id[:8]}: {e}")
            if errors:
                st.error(f"Save failed for {len(errors)} record(s):\n" + "\n".join(errors))
            else:
                st.success(f"Saved {len(changes)} change(s).")
                st.rerun()

    # --- Detail expand ---
    st.divider()
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
            if st.button("Archive this league", key=f"arch_{record['league_id']}"):
                archive_league(record["league_id"])
                st.success("Archived. Refresh to see updated list.")
                st.rerun()
        with col_rescrape:
            if st.button("Add to re-scrape queue", key=f"rescrape_{record['league_id']}"):
                add_to_rescrape_queue([record["url_scraped"]])
                st.success(f"Added {record['url_scraped'][:60]} to queue.")
```

- [ ] **Step 4: Add `_render_grouped`**

```python
def _render_grouped(rows: list[dict]) -> None:
    """Render rows grouped by url_scraped, one expander per URL."""
    from collections import defaultdict

    by_url: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_url[r.get("url_scraped", "unknown")].append(r)

    for url, url_rows in sorted(by_url.items()):
        label = f"{url}  ({len(url_rows)} league{'s' if len(url_rows) != 1 else ''})"
        with st.expander(label, expanded=False):
            display_cols = _DISPLAY_COLS
            display_data = [{col: r.get(col) for col in display_cols} for r in url_rows]
            st.dataframe(display_data, use_container_width=True)
```

- [ ] **Step 5: Verify import-level check**

```bash
python -c "from streamlit_app.pages import leagues_viewer; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add streamlit_app/pages/leagues_viewer.py
git commit -m "feat: add group-by-URL toggle to Leagues Viewer"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run all remaining tests**

```bash
cd VSCode/aa_RecLeagueDB
python -m pytest tests/ -v -x
```

Expected: all pass. No `ImportError` from deleted modules.

- [ ] **Step 2: Verify no broken imports from deleted modules**

```bash
grep -rn "league_extractor\|html_preprocessor\|html_aggregator\|page_classifier\|link_discoverer\|multi_page_navigator\|url_merge" \
  src/ streamlit_app/ scripts/ tests/ --include="*.py"
```

Expected: zero results

- [ ] **Step 3: Spot-check active page imports**

```bash
python -c "from streamlit_app.pages import campaign_manager; print('campaign_manager OK')"
python -c "from streamlit_app.pages import queue_monitor; print('queue_monitor OK')"
python -c "from streamlit_app.pages import fill_in_leagues; print('fill_in_leagues OK')"
python -c "from streamlit_app.pages import leagues_viewer; print('leagues_viewer OK')"
python -c "from streamlit_app.pages import league_merge; print('league_merge OK')"
python -c "from streamlit_app.pages import venues_enricher; print('venues_enricher OK')"
python -c "from streamlit_app.pages import data_quality; print('data_quality OK')"
python -c "from streamlit_app.pages import org_view; print('org_view OK')"
```

Expected: each line prints `OK`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: Plan B complete — legacy cleanup, nav reorg, Leagues Viewer upgrades"
```
