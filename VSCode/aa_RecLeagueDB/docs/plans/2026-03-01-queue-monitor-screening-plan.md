# Queue Monitor Screening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove Search Results Review from the nav, tighten the Queue Monitor default filter to PENDING-only with a first-timer caption, and add a "Screen Selected" action that deletes slip-through URLs from the queue and flags them in search_results.

**Architecture:** Three tasks — nav/filter cleanup (no tests needed), a new `screen_urls()` DB function (TDD), then the Screen Selected UI wired to it. All DB logic stays in `queue_viewer.py`; no raw Supabase calls added to the UI page.

**Tech Stack:** Python 3.11, Streamlit, supabase-py, pytest + unittest.mock

---

## Context You Need

- **`scrape_queue` fields:** `scrape_id` (UUID PK), `url`, `status`, `organization_name`, `sport_season_code`, `priority`, `scrape_attempts`
- **`search_results` fields:** `result_id` (UUID PK), `url_canonical`, `validation_status` (PASSED/FAILED), `validation_reason` (text)
- **`queue_viewer.py`** is the typed DB layer — all Supabase calls go here. The UI imports only from this module.
- **`_make_builder(data, count)`** test helper is in `tests/test_queue_viewer.py` — copy the pattern for new tests in the same file.
- **`execute_search_campaign()`** in `src/search/__init__.py` already auto-adds PASSED results to `scrape_queue` — Campaign Manager auto-add is already done.
- **All commands run from:** `C:/Users/mathe/VSCode/aa_RecLeagueDB`

---

## Task 1: Nav Cleanup + QM Default Filter + Caption

**Files:**
- Modify: `streamlit_app/app.py`
- Modify: `streamlit_app/pages/queue_monitor.py`

No unit tests — UI-only changes verified visually.

### Step 1: Remove Search Results Review from `app.py`

In `streamlit_app/app.py`, find the `PAGES` dict:

```python
PAGES = {
    # Search Pipeline
    "🎯 Campaign Manager":       ("search",  "campaign_manager"),
    "📋 Search Results Review":  ("search",  "search_results_review"),
    "📋 Queue Monitor":          ("search",  "queue_monitor"),
    "🕷️ Scraper UI":             ("search",  "scraper_ui"),
    ...
}
```

Remove the `"📋 Search Results Review"` entry:

```python
PAGES = {
    # Search Pipeline
    "🎯 Campaign Manager":       ("search",  "campaign_manager"),
    "📋 Queue Monitor":          ("search",  "queue_monitor"),
    "🕷️ Scraper UI":             ("search",  "scraper_ui"),
    ...
}
```

Then find the sidebar nav loop:

```python
    for label in ["🎯 Campaign Manager", "📋 Search Results Review", "📋 Queue Monitor", "🕷️ Scraper UI"]:
```

Remove `"📋 Search Results Review"` from the list:

```python
    for label in ["🎯 Campaign Manager", "📋 Queue Monitor", "🕷️ Scraper UI"]:
```

Also remove the `elif module_name == "search_results_review":` block (lines ~77-79):

```python
elif module_name == "search_results_review":
    from pages import search_results_review
    search_results_review.render()
```

### Step 2: Change QM default filter to PENDING-only

In `streamlit_app/pages/queue_monitor.py`, find the status filter (line ~43):

```python
        status_filter = st.multiselect(
            "Status", VALID_STATUSES, default=['PENDING', 'FAILED']
        )
```

Change default to `['PENDING']`:

```python
        status_filter = st.multiselect(
            "Status", VALID_STATUSES, default=['PENDING']
        )
```

### Step 3: Add first-timer caption

In `queue_monitor.py`, find the row count caption (line ~70):

```python
    st.caption(
        f"{total} rows total | Page {st.session_state.queue_page + 1} of {total_pages}"
    )
```

Replace with:

```python
    st.caption(
        f"{total} rows total | Page {st.session_state.queue_page + 1} of {total_pages}"
    )
    if status_filter == ['PENDING']:
        st.info(
            "Showing PENDING URLs by default. Use the **Status** filter above to see "
            "completed, failed, or skipped runs. To remove a URL that shouldn't be "
            "scraped, select it and use **Screen Selected** below.",
            icon="ℹ️",
        )
```

### Step 4: Commit

```bash
git add streamlit_app/app.py streamlit_app/pages/queue_monitor.py
git commit -m "feat: remove SRR from nav, default QM filter to PENDING, add first-timer caption"
```

---

## Task 2: Add `screen_urls()` to `queue_viewer.py`

**Files:**
- Modify: `src/database/queue_viewer.py`
- Modify: `tests/test_queue_viewer.py`

### Step 1: Write the failing tests

Append these tests at the end of `tests/test_queue_viewer.py`:

```python
# ── screen_urls ──────────────────────────────────────────────────────────────

def test_screen_urls_empty_list_returns_zero_without_db_call():
    """Empty ID list skips DB entirely."""
    mock_client, _, _ = _make_builder(data=[])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import screen_urls
        result = screen_urls([], [], 'sub_page')
    assert result == 0
    mock_client.table.assert_not_called()


def test_screen_urls_deletes_from_scrape_queue():
    """Calls .delete() on scrape_queue with matching scrape_ids."""
    ids = ['id-1', 'id-2']
    urls = ['https://a.com', 'https://b.com']
    mock_builder = MagicMock()
    for method in ['select', 'eq', 'in_', 'or_', 'order', 'range',
                   'ilike', 'update', 'delete', 'neq']:
        getattr(mock_builder, method).return_value = mock_builder
    mock_result = MagicMock()
    mock_result.data = [{'scrape_id': 'id-1'}, {'scrape_id': 'id-2'}]
    mock_result.count = 2
    mock_builder.execute.return_value = mock_result
    mock_client = MagicMock()
    mock_client.table.return_value = mock_builder

    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import screen_urls
        n = screen_urls(ids, urls, 'sub_page')

    mock_builder.delete.assert_called_once()
    mock_builder.in_.assert_any_call('scrape_id', ids)
    assert n == 2


def test_screen_urls_updates_search_results_with_reason():
    """Updates search_results validation_status and validation_reason."""
    ids = ['id-1']
    urls = ['https://a.com']
    mock_builder = MagicMock()
    for method in ['select', 'eq', 'in_', 'or_', 'order', 'range',
                   'ilike', 'update', 'delete', 'neq']:
        getattr(mock_builder, method).return_value = mock_builder
    delete_result = MagicMock()
    delete_result.data = [{'scrape_id': 'id-1'}]
    update_result = MagicMock()
    update_result.data = [{'result_id': 'r-1'}]
    mock_builder.execute.side_effect = [delete_result, update_result]
    mock_client = MagicMock()
    mock_client.table.return_value = mock_builder

    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import screen_urls
        screen_urls(ids, urls, 'social_media')

    # Second call should be update on search_results
    update_calls = mock_builder.update.call_args_list
    assert len(update_calls) == 1
    payload = update_calls[0][0][0]
    assert payload['validation_status'] == 'FAILED'
    assert payload['validation_reason'] == 'social_media'
```

### Step 2: Run — verify FAIL

```bash
python -m pytest tests/test_queue_viewer.py::test_screen_urls_empty_list_returns_zero_without_db_call tests/test_queue_viewer.py::test_screen_urls_deletes_from_scrape_queue tests/test_queue_viewer.py::test_screen_urls_updates_search_results_with_reason -v
```

Expected: `ImportError: cannot import name 'screen_urls'`

### Step 3: Implement `screen_urls`

Add this function at the end of `src/database/queue_viewer.py`:

```python
def screen_urls(scrape_ids: list, urls: list, reason: str) -> int:
    """Delete screened URLs from scrape_queue and flag them in search_results.

    Two DB calls: DELETE from scrape_queue, then UPDATE search_results so
    the URLs won't resurface in future campaign dedup checks.

    Args:
        scrape_ids: List of scrape_id UUIDs to delete from scrape_queue
        urls: Corresponding canonical URL strings (for updating search_results)
        reason: Screening reason — one of: sub_page, social_media,
                professional_sports, manually_screened

    Returns:
        Number of rows deleted from scrape_queue
    """
    if not scrape_ids:
        return 0

    client = get_client()

    # Step 1: Delete from scrape_queue
    delete_result = (
        client.table('scrape_queue')
        .delete()
        .in_('scrape_id', scrape_ids)
        .execute()
    )
    deleted = len(delete_result.data or [])

    # Step 2: Flag in search_results so dedup checks prevent re-adding
    if urls:
        client.table('search_results').update({
            'validation_status': 'FAILED',
            'validation_reason': reason,
        }).in_('url_canonical', urls).execute()

    return deleted
```

### Step 4: Run — verify PASS

```bash
python -m pytest tests/test_queue_viewer.py -v
```

Expected: all 16 tests PASS (13 original + 3 new).

### Step 5: Commit

```bash
git add src/database/queue_viewer.py tests/test_queue_viewer.py
git commit -m "feat: add screen_urls to queue_viewer (delete from queue, flag in search_results)"
```

---

## Task 3: Add Screen Selected UI to Queue Monitor

**Files:**
- Modify: `streamlit_app/pages/queue_monitor.py`

No unit tests — UI-only. Verified by smoke test.

### Step 1: Add `screen_urls` to the import block

Find:

```python
from src.database.queue_viewer import (
    VALID_STATUSES,
    bulk_update_by_filter,
    bulk_update_status,
    get_queue_row_count,
    get_queue_rows,
    get_queue_stats,
    update_scrape_result,
)
```

Replace with:

```python
from src.database.queue_viewer import (
    VALID_STATUSES,
    bulk_update_by_filter,
    bulk_update_status,
    get_queue_row_count,
    get_queue_rows,
    get_queue_stats,
    screen_urls,
    update_scrape_result,
)
```

### Step 2: Add the Screen Selected section

Find the divider before the Serper expander:

```python
    st.divider()

    # ── Add via Serper ────────────────────────────────────────────────────────
```

Insert the screen section immediately before that `st.divider()`:

```python
    # ── Screen selected URLs ──────────────────────────────────────────────────
    if rows and 'scrape_id' in df.columns and 'url' in df.columns:
        st.markdown("**🚫 Screen selected URLs**")
        sc1, sc2 = st.columns([2, 1])
        with sc1:
            SCREEN_REASONS = {
                'Sub-Page': 'sub_page',
                'Social Media': 'social_media',
                'Pro Team': 'professional_sports',
                'Other': 'manually_screened',
            }
            screen_reason_label = st.selectbox(
                "Reason",
                list(SCREEN_REASONS.keys()),
                key="screen_reason",
            )
        with sc2:
            st.write("")  # vertical alignment spacer
            st.write("")
            screen_clicked = st.button(
                f"🚫 Screen {len(selected_ids)} Selected",
                disabled=not selected_ids,
                key="screen_selected",
            )

        if screen_clicked:
            selected_urls = df[df['scrape_id'].isin(selected_ids)]['url'].tolist()
            reason_code = SCREEN_REASONS[screen_reason_label]
            n = screen_urls(selected_ids, selected_urls, reason_code)
            st.success(
                f"Screened {n} URL(s) as '{screen_reason_label}' — "
                "removed from queue and flagged in search results."
            )
            st.rerun()

```

### Step 3: Commit

```bash
git add streamlit_app/pages/queue_monitor.py
git commit -m "feat: add Screen Selected action to Queue Monitor with reason picker"
```

### Step 4: Smoke test

1. Open Queue Monitor at `https://recsportsdb.ngrok.app`
2. Verify default filter is PENDING only and info caption is visible
3. Check a row (e.g. a sub-page URL)
4. Select "Sub-Page" from the Reason dropdown
5. Click "🚫 Screen 1 Selected"
6. Verify row disappears from the table
7. Verify `search_results` row for that URL now has `validation_status = FAILED`, `validation_reason = sub_page` (check via Supabase dashboard)
