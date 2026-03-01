# Scraper UI Design

**Date:** 2026-03-01
**Goal:** Let users select PENDING URLs in the Queue Monitor, click Run, and watch scraping happen with itemized per-URL results written to leagues_metadata.

---

## Architecture

### Docker changes
- Add `playwright>=1.40.0` to `requirements-streamlit.txt`
- Add `RUN playwright install chromium --with-deps` to `Dockerfile` (after pip install)
- Rebuild `recsports` container (~1.5GB image)

### Queue Monitor UI changes
- New **"▶ Run N Selected"** button in the Actions section (selected rows column)
- Clicking it runs `smart_scraper.run(url)` for each selected URL sequentially
- Uses `st.status()` for live itemized display, one row per URL as it completes
- Shows final summary: total leagues written, total errors

### Queue status lifecycle
| Stage | `status` value |
|---|---|
| Before run | `PENDING` |
| While running | `IN_PROGRESS` |
| Scraper returned ≥1 league | `COMPLETED` |
| Exception or 0 leagues written | `FAILED` |

`scrape_attempts` incremented on every run.

### Dedup fix (bundled)
`queue_manager.add_to_scrape_queue` Check 1 currently blocks on ALL statuses.
Change to only block on `['PENDING', 'IN_PROGRESS']` — allows re-adding FAILED/COMPLETED URLs.

---

## Data Flow

1. User selects checkboxes on PENDING rows in Queue Monitor
2. Clicks "▶ Run N Selected"
3. For each URL:
   a. `bulk_update_status([id], 'IN_PROGRESS')` — marks it running
   b. `smart_scraper.run(url, dry_run=False)` — crawls, extracts, writes to leagues_metadata
   c. `bulk_update_status([id], 'COMPLETED')` or `FAILED` based on result
   d. Increments `scrape_attempts` via direct update
   e. Appends one status line to the live display
4. Summary shown, page reruns

---

## Files Changed

| File | Change |
|---|---|
| `requirements-streamlit.txt` | Add `playwright>=1.40.0` |
| `Dockerfile` | Add playwright browser install step |
| `streamlit_app/pages/queue_monitor.py` | Add Run button + itemized results UI |
| `src/search/queue_manager.py` | Fix dedup to only block PENDING/IN_PROGRESS |
