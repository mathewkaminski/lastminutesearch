# Fill Fields Enricher Redesign
**Date:** 2026-03-20
**Status:** Approved

## Problem

The Fill Fields enrichment mode has two failure modes observed in production:

1. **Always defaults to Firecrawl.** `enrich_url` fetches a domain-level snapshot from the Supabase `page_snapshots` table. This table entry is matched by domain only, so it often returns content from a different page on the same site (e.g. the homepage when the league URL is `/leagues/curling`). The snapshot extraction returns empty patches, the mini-crawl fails to fill remaining fields, and Firecrawl triggers automatically.

2. **Firecrawl hallucinates.** Claude Haiku fills null fields with plausible-sounding but unsupported values when page content doesn't clearly contain the answer. The current prompt wording ("Return null for any field not clearly stated") is insufficient to prevent this.

Additionally, the extraction surface is too narrow: the accessibility tree YAML truncates element names at 100 characters, cutting off text blocks like fee tables and schedule paragraphs.

## Design

### 1. `field_enricher.py` — `enrich_url` fetch flow

Replace the DB snapshot lookup with direct URL-specific Playwright cache, then live Playwright as fallback. Remove Firecrawl from the automatic path. Add `use_firecrawl=False` parameter to opt into Firecrawl explicitly.

**New flow:**
```
1. fetch_page_as_yaml(url, use_cache=True, max_full_text_chars=40000)
      → cache hit: extract from YAML + full_text
      → cache miss: go to step 2
2. fetch_page_as_yaml(url, force_refresh=True, max_full_text_chars=40000)  [live Playwright]
      → extract from YAML + full_text
      → if exception raised: return empty FieldEnrichResult per league with error message
3. mini-crawl for still-missing fields (unchanged)
4. Done — report filled / skipped fields
```

When `use_firecrawl=True` (explicit Firecrawl mode):
```
5. FirecrawlClient.scrape(url) → extract from markdown content
```

The `source` field on `FieldEnrichResult` gains a new value: `"playwright"` (live fetch), alongside existing `"cache"`, `"firecrawl"`, `"none"`.

Remove `get_snapshots_by_domain` import, the `extract_base_domain` local import (line 118 of current file), and all related calls entirely from `FieldEnricher`.

### 2. `playwright_yaml_fetcher.py` — richer YAML capture

Fix the 100-character name truncation in `EXTRACT_ACCESSIBILITY_TREE_JS`. Change:
```js
name: element.textContent && element.textContent.slice(0, 100).trim()
```
to:
```js
name: element.textContent && element.textContent.slice(0, 500).trim()
```

This allows fee tables, schedule blocks, and description paragraphs to survive into the YAML tree without truncation. The `max_full_text_chars` default in `fetch_page_as_yaml` stays at 15,000. Enrichment calls explicitly pass `max_full_text_chars=40000` — this keeps the larger capture scoped to enrichment only and avoids silently increasing token costs in the main scraper pipeline (`smart_crawler.py`, `fetch_yaml_multi_page`).

### 3. `field_enricher.py` — `_build_prompt` + `_extract`

`_build_prompt` receives `full_text: str` as a new parameter. `full_text` is inserted verbatim (already capped to 40,000 chars by the `fetch_page_as_yaml` call in step 1/2 above — no further trimming needed). Both YAML and full_text are included in the prompt:

```
PAGE STRUCTURE (accessibility tree YAML):
{yaml_content}

PAGE TEXT (rendered plain text):
{full_text}
```

The null instruction is strengthened to:
```
CRITICAL: If a field's value is not EXPLICITLY and UNAMBIGUOUSLY stated on
this page, you MUST return null. Do NOT infer, estimate, or fill in plausible
values. When in doubt, return null.
```

`_extract` signature gains `full_text: str = ""` and passes it through to `_build_prompt`.

### 4. `fill_in_leagues.py` — UI changes

**Mode selector:** Add "Firecrawl" as a fourth option:
```python
options=["Fill Fields", "Teams", "Deep-dive", "Firecrawl"]
```
With description: `"Fetches page via Firecrawl API and extracts missing fields. Use when Fill Fields returns no results."`

`_run_fill_fields` gains a `use_firecrawl: bool = False` parameter and passes it to `enricher.enrich_url`. The caller dispatches both "Fill Fields" and "Firecrawl" modes via the same branch, passing `use_firecrawl=(mode == "Firecrawl")`.

**Results display:** The `mode_label == "Fill Fields"` branch at the bottom of the page is extended to `mode_label in ("Fill Fields", "Firecrawl")` so Firecrawl run results are rendered correctly.

The source badge map gains `"playwright": "Live Playwright"`:
```python
{"cache": "Cache", "playwright": "Live Playwright", "firecrawl": "Firecrawl", "none": "No data"}
```

**Run Selected button position:** Move from below the URL list to immediately after the mode description + divider, before the URL list. The page flow becomes:

```
Mode selector
Mode description
[Run Selected]  ← moved here
──────────────
Select URLs
Filters & Sorting
URL checkboxes
Preview panel
```

Button remains disabled when `len(selected_urls) == 0`.

## Files Changed

| File | Change |
|------|--------|
| `src/enrichers/field_enricher.py` | New fetch flow, `use_firecrawl` param, `full_text` extraction, remove DB snapshot + dead imports, handle live Playwright fetch failure |
| `src/scraper/playwright_yaml_fetcher.py` | Fix 100→500 char YAML name truncation; `max_full_text_chars` default stays 15,000 |
| `streamlit_app/pages/fill_in_leagues.py` | Add Firecrawl mode, `use_firecrawl` param on `_run_fill_fields`, extend results display branch, add "playwright" badge, move Run Selected button |

## Out of Scope

- Saving newly discovered links to `scrape_queue` for future crawling (noted for future work)
- Upgrading extraction model from Haiku to Sonnet (revisit after testing)
- Changes to mini-crawl link scoring logic
