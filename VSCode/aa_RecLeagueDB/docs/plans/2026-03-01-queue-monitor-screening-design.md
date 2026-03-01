# Queue Monitor Screening Design

**Date:** 2026-03-01
**Goal:** Collapse Search Results Review into Queue Monitor, auto-add PASSED results from Campaign Manager, and let users screen slip-through URLs with a reason.

---

## Architecture

### Pipeline after this change

```
Campaign Manager runs
        │
        ▼
search_results table
   ├── PASSED → scrape_queue (PENDING)   ← auto-added, no manual step
   └── FAILED → stays in search_results  ← never touches QM
        │
        ▼
Queue Monitor (single place for all queue management)
   ├── Default view: PENDING only
   │     Caption: hint for first-timers, disappears once filter is changed
   ├── Run Selected → scrapes, writes to leagues_metadata
   └── Screen Selected → reason picker → DELETE from scrape_queue
                                        → UPDATE search_results row
                                        → won't resurface in future campaigns
```

### What changes

| Component | Change |
|---|---|
| `Campaign Manager` | Auto-adds PASSED results to `scrape_queue` after each search run |
| `app.py` | Remove Search Results Review from nav |
| `Queue Monitor` | Default filter = PENDING only; add caption; add Screen Selected action |

### What does NOT change

- `scrape_queue` schema — no new columns (screen removes the row entirely)
- `search_results` schema — `validation_reason` already exists
- Status dropdown values (PENDING/IN_PROGRESS/COMPLETED/FAILED/SKIPPED)
- Run Selected button, Apply to selected/all, pagination, filters

---

## Queue Monitor UI Changes

### Caption bar

Shown only when status filter is at default (PENDING only). Disappears once user changes the filter.

```
ℹ️ Showing PENDING URLs by default. Use the Status filter to see completed,
   failed, or skipped runs. To remove a URL that shouldn't be scraped,
   select it and use Screen Selected below.
```

### Default status filter

Changed from `['PENDING', 'FAILED']` to `['PENDING']`.

### Screen Selected action

New block in the Actions section, below the existing bulk status controls:

```
── Screen selected URLs ─────────────────────────────────────────
Reason:  [Sub-Page ▼]   [🚫 Screen N Selected]   ← disabled if nothing checked

Options: Sub-Page | Social Media | Pro Team | Other
```

**On confirm:**
1. DELETE from `scrape_queue` WHERE scrape_id IN (selected ids)
2. UPDATE `search_results` SET validation_status='FAILED', validation_reason=<reason>
   WHERE url_canonical IN (selected urls)
3. `st.rerun()`

**Reason → validation_reason mapping:**
| UI Label | validation_reason written |
|---|---|
| Sub-Page | `sub_page` |
| Social Media | `social_media` |
| Pro Team | `professional_sports` |
| Other | `manually_screened` |

---

## Campaign Manager Change

After search results are saved, auto-call `add_to_scrape_queue()` for every PASSED result. The existing dedup logic (Check 1: PENDING/IN_PROGRESS, Check 2: already in leagues_metadata) handles re-runs cleanly.

Success message changes to: "✅ Added N URLs to scrape queue — go to Queue Monitor to run them."

---

## New DB Function

`screen_urls(scrape_ids, urls, reason)` in `queue_viewer.py`:
- Two DB calls: DELETE from scrape_queue + UPDATE search_results
- Returns count of rows deleted
- Tested with mock client (same pattern as existing functions)
