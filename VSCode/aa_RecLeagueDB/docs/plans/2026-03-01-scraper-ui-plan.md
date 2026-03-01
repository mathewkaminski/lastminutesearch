# Scraper UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "▶ Run Selected" button to the Queue Monitor that scrapes selected URLs with Playwright and writes results to `leagues_metadata`, showing itemized per-URL results live.

**Architecture:** Four tasks — fix the dedup bug in `queue_manager.py`, add `update_scrape_result()` to `queue_viewer.py`, install Playwright in the Docker image, then wire the Run button into `queue_monitor.py`. All DB logic stays in the typed layer (`queue_viewer.py`); no raw Supabase calls in the UI page.

**Tech Stack:** Python 3.11, Streamlit `st.status()`, Playwright (Chromium), supabase-py, pytest + unittest.mock

---

## Context You Need

- **`scrape_queue` fields:** `scrape_id` (UUID PK), `url`, `status` (PENDING/IN_PROGRESS/COMPLETED/FAILED/SKIPPED), `scrape_attempts` (int), `priority`, `organization_name`, `sport_season_code`
- **Scraper entry point:** `scripts/smart_scraper.py::run(url, dry_run=False)` — returns `{'leagues_written': int, 'errors': list, 'pages_with_leagues': int, 'leagues_extracted': int}`
- **`scripts/` is a Python package** — has `__init__.py`, import as `from scripts.smart_scraper import run`
- **Existing DB helpers:** `bulk_update_status(ids, status)` in `src/database/queue_viewer.py` — use this to flip status before/after running
- **Test helper:** `_make_builder(data, count)` in `tests/test_queue_viewer.py` — copy it into `tests/test_queue_manager.py` for queue_manager tests
- **All commands run from:** `C:/Users/mathe/VSCode/aa_RecLeagueDB`

---

## Task 1: Fix Dedup in `queue_manager.py`

**Files:**
- Modify: `src/search/queue_manager.py:41-44`
- Create: `tests/test_queue_manager.py`

**The bug:** Check 1 queries `scrape_queue` for the URL across ALL statuses. A FAILED or COMPLETED row incorrectly blocks re-adding the URL. Fix: filter to only PENDING and IN_PROGRESS.

### Step 1: Write the failing tests

```python
# tests/test_queue_manager.py
from unittest.mock import MagicMock, patch


def _make_builder(data=None, count=0):
    mock_builder = MagicMock()
    for method in ['select', 'eq', 'in_', 'or_', 'order', 'range',
                   'ilike', 'update', 'neq', 'insert', 'limit']:
        getattr(mock_builder, method).return_value = mock_builder
    mock_result = MagicMock()
    mock_result.count = count
    mock_result.data = data if data is not None else []
    mock_builder.execute.return_value = mock_result
    mock_client = MagicMock()
    mock_client.table.return_value = mock_builder
    return mock_client, mock_builder, mock_result


def test_add_to_queue_checks_only_pending_and_in_progress():
    """Dedup query uses .in_('status', ['PENDING', 'IN_PROGRESS'])."""
    mock_client, mock_builder, _ = _make_builder(data=[])
    with patch('src.search.queue_manager.get_client', return_value=mock_client):
        import importlib, src.search.queue_manager as qm
        importlib.reload(qm)
        qm.add_to_scrape_queue('result-1', 'https://example.com/leagues', 'TestOrg', 2)
    mock_builder.in_.assert_any_call('status', ['PENDING', 'IN_PROGRESS'])


def test_add_to_queue_skips_when_pending_exists():
    """URL already PENDING/IN_PROGRESS → returns False (skipped)."""
    mock_client, mock_builder, _ = _make_builder(
        data=[{'scrape_id': 'existing-id'}]  # found in queue
    )
    with patch('src.search.queue_manager.get_client', return_value=mock_client):
        import importlib, src.search.queue_manager as qm
        importlib.reload(qm)
        result = qm.add_to_scrape_queue('result-1', 'https://example.com/leagues', 'TestOrg', 2)
    assert result is False
    mock_builder.insert.assert_not_called()


def test_add_to_queue_allows_when_no_active_entry():
    """URL not in queue as PENDING/IN_PROGRESS → inserts and returns True."""
    mock_client, mock_builder, _ = _make_builder(data=[])
    with patch('src.search.queue_manager.get_client', return_value=mock_client):
        import importlib, src.search.queue_manager as qm
        importlib.reload(qm)
        result = qm.add_to_scrape_queue('result-1', 'https://example.com/leagues', 'TestOrg', 2)
    assert result is True
    mock_builder.insert.assert_called_once()
```

### Step 2: Run — verify FAIL

```bash
pytest tests/test_queue_manager.py -v
```

Expected: `test_add_to_queue_checks_only_pending_and_in_progress` FAILS (`.in_()` not called on status), `test_add_to_queue_skips_when_pending_exists` may pass, `test_add_to_queue_allows_when_no_active_entry` may fail.

### Step 3: Apply the fix

In `src/search/queue_manager.py`, find the Check 1 block (lines ~41-44):

**Replace:**
```python
        # Check 1: Already in scrape_queue?
        existing_queue = client.table('scrape_queue').select('scrape_id').eq(
            'url', url_canonical
        ).limit(1).execute()
```

**With:**
```python
        # Check 1: Already in scrape_queue with an active status?
        existing_queue = (
            client.table('scrape_queue')
            .select('scrape_id')
            .eq('url', url_canonical)
            .in_('status', ['PENDING', 'IN_PROGRESS'])
            .limit(1)
            .execute()
        )
```

### Step 4: Run — verify PASS

```bash
pytest tests/test_queue_manager.py -v
```

Expected: all 3 tests PASS.

### Step 5: Commit

```bash
git add src/search/queue_manager.py tests/test_queue_manager.py
git commit -m "fix: dedup check only blocks PENDING/IN_PROGRESS, allows re-add of FAILED/COMPLETED"
```

---

## Task 2: Add `update_scrape_result` to `queue_viewer.py`

**Files:**
- Modify: `src/database/queue_viewer.py`
- Modify: `tests/test_queue_viewer.py`

**Purpose:** Single function that atomically sets status + increments `scrape_attempts` after a scrape job finishes. The UI calls this once per URL instead of two separate update calls.

### Step 1: Add tests to `tests/test_queue_viewer.py`

Append these tests at the end of the file:

```python
# ── update_scrape_result ─────────────────────────────────────────────────────

def test_update_scrape_result_sets_status_and_increments_attempts():
    """Sets new status and increments scrape_attempts by 1."""
    mock_client, mock_builder, _ = _make_builder(data=[{'scrape_attempts': 2}])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import update_scrape_result
        update_scrape_result('scrape-id-1', 'COMPLETED')
    mock_builder.update.assert_called_once()
    call_payload = mock_builder.update.call_args[0][0]
    assert call_payload['status'] == 'COMPLETED'
    assert call_payload['scrape_attempts'] == 3   # 2 + 1


def test_update_scrape_result_handles_null_attempts():
    """scrape_attempts=None in DB is treated as 0."""
    mock_client, mock_builder, _ = _make_builder(data=[{'scrape_attempts': None}])
    with patch('src.database.queue_viewer.get_client', return_value=mock_client):
        from src.database.queue_viewer import update_scrape_result
        update_scrape_result('scrape-id-1', 'FAILED')
    call_payload = mock_builder.update.call_args[0][0]
    assert call_payload['scrape_attempts'] == 1   # None → 0, then +1
```

### Step 2: Run — verify FAIL

```bash
pytest tests/test_queue_viewer.py::test_update_scrape_result_sets_status_and_increments_attempts tests/test_queue_viewer.py::test_update_scrape_result_handles_null_attempts -v
```

Expected: `ImportError: cannot import name 'update_scrape_result'`

### Step 3: Implement `update_scrape_result`

Add this function at the end of `src/database/queue_viewer.py` (before the final newline):

```python
def update_scrape_result(scrape_id: str, new_status: str) -> None:
    """Set status and increment scrape_attempts after a scrape job finishes.

    Two DB calls: fetch current attempts, then update status + incremented count.
    Safe for concurrent use at the small queue sizes this app targets.

    Args:
        scrape_id: UUID of the scrape_queue row
        new_status: 'COMPLETED' or 'FAILED'
    """
    client = get_client()

    # Fetch current attempt count
    row = (
        client.table('scrape_queue')
        .select('scrape_attempts')
        .eq('scrape_id', scrape_id)
        .execute()
    )
    current = (row.data[0].get('scrape_attempts') or 0) if row.data else 0

    client.table('scrape_queue').update({
        'status': new_status,
        'scrape_attempts': current + 1,
    }).eq('scrape_id', scrape_id).execute()
```

### Step 4: Run — verify PASS

```bash
pytest tests/test_queue_viewer.py -v
```

Expected: all 13 tests PASS (11 original + 2 new).

### Step 5: Commit

```bash
git add src/database/queue_viewer.py tests/test_queue_viewer.py
git commit -m "feat: add update_scrape_result to queue_viewer (status + increment scrape_attempts)"
```

---

## Task 3: Add Playwright to Docker

**Files:**
- Modify: `requirements-streamlit.txt`
- Modify: `Dockerfile`

No unit tests — verified by successful `docker build` and `docker compose up`.

### Step 1: Add playwright to `requirements-streamlit.txt`

Find the `# Web UI` section and add playwright above it:

```
# Browser automation (for smart_scraper crawl)
playwright>=1.40.0

# Web UI
streamlit>=1.31.0
```

### Step 2: Add browser install step to `Dockerfile`

The current Dockerfile ends with `EXPOSE 8501` and `CMD [...]`. Add the playwright install **after** the pip install line:

**Find:**
```dockerfile
RUN pip install --no-cache-dir -r requirements-streamlit.txt

EXPOSE 8501
```

**Replace with:**
```dockerfile
RUN pip install --no-cache-dir -r requirements-streamlit.txt
RUN playwright install chromium --with-deps

EXPOSE 8501
```

### Step 3: Rebuild the image

```bash
cd "C:/Users/mathe/VSCode/aa_RecLeagueDB"
docker build -t recsports-test .
```

Expected: `Successfully built <id>` — no errors. Build will take 2-4 minutes (downloading Chromium ~170MB). Final image size: ~1.4-1.6GB.

If build fails at `playwright install` with a permissions error, change to:
```dockerfile
RUN playwright install chromium --with-deps || true
```
Then check the output carefully — it usually fails on missing system libs, which `--with-deps` handles.

### Step 4: Verify playwright works inside the image

```bash
docker run --rm recsports-test python -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"
```

Expected: `Playwright OK`

### Step 5: Commit

```bash
git add requirements-streamlit.txt Dockerfile
git commit -m "feat: add Playwright+Chromium to Docker image for scraper UI"
```

---

## Task 4: Add "Run Selected" Button to Queue Monitor

**Files:**
- Modify: `streamlit_app/pages/queue_monitor.py`

No unit tests for UI. Verified by smoke test (run button triggers scraper, leagues appear in DB).

### Step 1: Add imports at the top of `queue_monitor.py`

Find the existing imports block:

```python
from src.database.queue_viewer import (
    VALID_STATUSES,
    bulk_update_by_filter,
    bulk_update_status,
    get_queue_row_count,
    get_queue_rows,
    get_queue_stats,
)
```

Replace with (adds `update_scrape_result`):

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

### Step 2: Add the Run button section

Find the divider that separates Actions from the Serper expander:

```python
    st.divider()

    # ── Add via Serper ────────────────────────────────────────────────────────
```

Insert the Run section immediately before that divider:

```python
    # ── Run scraper ───────────────────────────────────────────────────────────
    if rows and 'scrape_id' in pd.DataFrame(rows).columns:
        st.markdown("**▶ Scrape selected URLs**")
        if st.button(
            f"▶ Run {len(selected_ids)} Selected",
            disabled=not selected_ids,
            type="primary",
            key="run_scraper",
        ):
            from scripts.smart_scraper import run as scraper_run

            selected_df = df[df['scrape_id'].isin(selected_ids)][['scrape_id', 'url']]
            total_leagues = 0
            total_errors = 0

            with st.status(
                f"Running {len(selected_ids)} URL(s)...", expanded=True
            ) as run_status:
                for _, row in selected_df.iterrows():
                    sid = row['scrape_id']
                    url = row['url']
                    run_status.update(label=f"Running: {url[:70]}...")
                    bulk_update_status([sid], 'IN_PROGRESS')
                    try:
                        result = scraper_run(url, dry_run=False)
                        written = result.get('leagues_written', 0)
                        errors = result.get('errors', [])
                        new_status = (
                            'FAILED' if (written == 0 and errors) else 'COMPLETED'
                        )
                        update_scrape_result(sid, new_status)
                        total_leagues += written
                        if errors:
                            total_errors += len(errors)
                            icon = '✅' if written > 0 else '❌'
                            st.write(
                                f"{icon} **{url}** — "
                                f"{written} league(s) written, {len(errors)} error(s)"
                            )
                            for err in errors:
                                st.caption(f"  ↳ {err[:120]}")
                        else:
                            st.write(
                                f"✅ **{url}** — {written} league(s) written"
                            )
                    except Exception as exc:
                        update_scrape_result(sid, 'FAILED')
                        total_errors += 1
                        st.write(f"❌ **{url}** — {str(exc)[:120]}")

                summary = (
                    f"Done — {total_leagues} league(s) written "
                    f"across {len(selected_ids)} URL(s)"
                )
                if total_errors:
                    summary += f", {total_errors} error(s)"
                run_status.update(
                    label=summary,
                    state="complete" if total_errors == 0 else "error",
                    expanded=True,
                )
            st.rerun()

    st.divider()

    # ── Add via Serper ────────────────────────────────────────────────────────
```

### Step 3: Rebuild and restart the container

```bash
cd "C:/Users/mathe/n8n-docker"
docker compose build recsports
docker compose up -d recsports
```

Expected: container restarts, no errors in `docker compose logs recsports`.

### Step 4: Smoke test

1. Navigate to Queue Monitor on `https://recsportsdb.ngrok.app`
2. Select one PENDING URL checkbox
3. Click **▶ Run 1 Selected**
4. Watch the `st.status()` box:
   - Label changes to "Running: https://..."
   - After completion: shows ✅ or ❌ with league count
   - Final label: "Done — N league(s) written..."
5. Check Queue Monitor — that row's status should now be COMPLETED or FAILED
6. Check `leagues_metadata` table via Supabase dashboard for new rows

### Step 5: Commit

```bash
cd "C:/Users/mathe/VSCode/aa_RecLeagueDB"
git add streamlit_app/pages/queue_monitor.py
git commit -m "feat: add Run Selected button to Queue Monitor with live itemized scraper results"
```
