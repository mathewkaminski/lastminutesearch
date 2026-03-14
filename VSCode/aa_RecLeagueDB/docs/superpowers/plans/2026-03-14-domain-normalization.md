# Domain Normalization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize domain handling across all tables and the scrapes directory so that `www.gameonguelph.ca` and `gameonguelph.ca` (and any subdomains) resolve to the same organization.

**Architecture:** Add `base_domain` column to `scrape_queue`, `discovered_links`, and normalize the existing `page_snapshots.domain` column. All insert paths populate `base_domain` using the existing `extract_base_domain()` utility. Backfill existing rows via SQL. ScraperUI and link_discoverer use normalized domains for lookups.

**Tech Stack:** PostgreSQL (via psql), Python, Supabase client

**psql access:** `source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL"` from the project root.

---

## Task 1: Add `base_domain` to `scrape_queue` (DB migration)

**Files:**
- Create: `migrations/007_add_base_domain_to_scrape_queue.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- migrations/007_add_base_domain_to_scrape_queue.sql
-- Add base_domain column to scrape_queue for consistent domain grouping

ALTER TABLE public.scrape_queue
  ADD COLUMN IF NOT EXISTS base_domain TEXT;

-- Backfill: strip www. and subdomains from url netloc
UPDATE scrape_queue
SET base_domain = LOWER(
  CASE
    WHEN (regexp_match(
      CASE
        WHEN substring(url from '://([^/:]+)') LIKE 'www.%'
        THEN substring(substring(url from '://([^/:]+)') from 5)
        ELSE substring(url from '://([^/:]+)')
      END,
      '([^.]+\.[^.]+)$'
    ))[1] IS NOT NULL
    THEN (regexp_match(
      CASE
        WHEN substring(url from '://([^/:]+)') LIKE 'www.%'
        THEN substring(substring(url from '://([^/:]+)') from 5)
        ELSE substring(url from '://([^/:]+)')
      END,
      '([^.]+\.[^.]+)$'
    ))[1]
    ELSE CASE
      WHEN substring(url from '://([^/:]+)') LIKE 'www.%'
      THEN substring(substring(url from '://([^/:]+)') from 5)
      ELSE substring(url from '://([^/:]+)')
    END
  END
);

CREATE INDEX IF NOT EXISTS idx_scrape_queue_base_domain ON scrape_queue(base_domain);
```

- [ ] **Step 2: Run migration**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL" -f migrations/007_add_base_domain_to_scrape_queue.sql
```

- [ ] **Step 3: Verify backfill**

```bash
source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL" -c "
SELECT base_domain, count(*) FROM scrape_queue GROUP BY base_domain ORDER BY 2 DESC LIMIT 15;
"
```

Expected: All rows have a non-null `base_domain`, www-prefixed values are stripped.

- [ ] **Step 4: Commit**

```bash
git add migrations/007_add_base_domain_to_scrape_queue.sql
git commit -m "feat: add base_domain column to scrape_queue with backfill"
```

---

## Task 2: Add `base_domain` to `discovered_links` (DB migration)

**Files:**
- Create: `migrations/008_add_base_domain_to_discovered_links.sql`

- [ ] **Step 1: Write migration SQL**

```sql
-- migrations/008_add_base_domain_to_discovered_links.sql
-- Add base_domain column to discovered_links for consistent domain grouping

ALTER TABLE public.discovered_links
  ADD COLUMN IF NOT EXISTS base_domain TEXT;

-- Backfill from source_url
UPDATE discovered_links
SET base_domain = LOWER(
  CASE
    WHEN (regexp_match(
      CASE
        WHEN substring(source_url from '://([^/:]+)') LIKE 'www.%'
        THEN substring(substring(source_url from '://([^/:]+)') from 5)
        ELSE substring(source_url from '://([^/:]+)')
      END,
      '([^.]+\.[^.]+)$'
    ))[1] IS NOT NULL
    THEN (regexp_match(
      CASE
        WHEN substring(source_url from '://([^/:]+)') LIKE 'www.%'
        THEN substring(substring(source_url from '://([^/:]+)') from 5)
        ELSE substring(source_url from '://([^/:]+)')
      END,
      '([^.]+\.[^.]+)$'
    ))[1]
    ELSE CASE
      WHEN substring(source_url from '://([^/:]+)') LIKE 'www.%'
      THEN substring(substring(source_url from '://([^/:]+)') from 5)
      ELSE substring(source_url from '://([^/:]+)')
    END
  END
);

CREATE INDEX IF NOT EXISTS idx_discovered_links_base_domain ON discovered_links(base_domain);
```

- [ ] **Step 2: Run migration**

```bash
source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL" -f migrations/008_add_base_domain_to_discovered_links.sql
```

- [ ] **Step 3: Verify backfill**

```bash
source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL" -c "
SELECT base_domain, count(*) FROM discovered_links GROUP BY base_domain ORDER BY 2 DESC LIMIT 15;
"
```

- [ ] **Step 4: Commit**

```bash
git add migrations/008_add_base_domain_to_discovered_links.sql
git commit -m "feat: add base_domain column to discovered_links with backfill"
```

---

## Task 3: Normalize `page_snapshots.domain` (backfill only)

**Files:**
- Create: `migrations/009_normalize_page_snapshots_domain.sql`

The `page_snapshots.domain` column already exists but contains raw netloc values (e.g. `www.ottawavolleysixes.com`). Normalize in place.

- [ ] **Step 1: Write migration SQL**

```sql
-- migrations/009_normalize_page_snapshots_domain.sql
-- Normalize existing page_snapshots.domain to strip www. and subdomains

UPDATE page_snapshots
SET domain = LOWER(
  CASE
    WHEN (regexp_match(
      CASE
        WHEN domain LIKE 'www.%' THEN substring(domain from 5)
        ELSE domain
      END,
      '([^.]+\.[^.]+)$'
    ))[1] IS NOT NULL
    THEN (regexp_match(
      CASE
        WHEN domain LIKE 'www.%' THEN substring(domain from 5)
        ELSE domain
      END,
      '([^.]+\.[^.]+)$'
    ))[1]
    ELSE CASE
      WHEN domain LIKE 'www.%' THEN substring(domain from 5)
      ELSE domain
    END
  END
)
WHERE domain LIKE 'www.%'
   OR domain != LOWER(domain);
```

- [ ] **Step 2: Run migration**

```bash
source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL" -f migrations/009_normalize_page_snapshots_domain.sql
```

- [ ] **Step 3: Verify**

```bash
source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL" -c "
SELECT domain, count(*) FROM page_snapshots GROUP BY domain ORDER BY 2 DESC;
"
```

Expected: `www.ottawavolleysixes.com` -> `ottawavolleysixes.com`

- [ ] **Step 4: Commit**

```bash
git add migrations/009_normalize_page_snapshots_domain.sql
git commit -m "fix: normalize page_snapshots.domain to strip www prefix"
```

---

## Task 4: Populate `base_domain` on insert — `queue_manager.py`

**Files:**
- Modify: `src/search/queue_manager.py:72-81`

- [ ] **Step 1: Add extract_base_domain import and populate on insert**

At top of file, add import:
```python
from src.utils.domain_extractor import extract_base_domain
```

In `add_to_scrape_queue()`, modify the `queue_data` dict (line ~73):
```python
        queue_data = {
            'url': url_canonical,
            'base_domain': extract_base_domain(url_canonical),
            'source_result_id': result_id,
            'organization_name': org_name,
            'sport_season_code': sport_season_code,
            'priority': priority,
            'status': 'PENDING',
            'scrape_attempts': 0
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/search/queue_manager.py
git commit -m "feat: populate base_domain on scrape_queue insert"
```

---

## Task 5: Populate `base_domain` on insert — `link_store.py`

**Files:**
- Modify: `src/database/link_store.py:57-69`

- [ ] **Step 1: Add import and populate on insert**

At top of file (after existing imports):
```python
from src.utils.domain_extractor import extract_base_domain
```

In `store_discovered_links()`, add `base_domain` to `link_data` dict (line ~58):
```python
                link_data = {
                    "id": str(uuid4()),
                    "source_url": url,
                    "discovered_url": link.get("url") or link.url,
                    "anchor_text": link.get("anchor_text") or getattr(link, "anchor_text", ""),
                    "score": link.get("score") or getattr(link, "score", 0),
                    "page_type": link.get("page_type") or getattr(link, "page_type", None),
                    "clickable": link.get("clickable") or getattr(link, "clickable", False),
                    "snapshot_id": snapshot_id,
                    "result_id": result_id,
                    "url_raw": url_raw,
                    "base_domain": extract_base_domain(url),
                }
```

- [ ] **Step 2: Commit**

```bash
git add src/database/link_store.py
git commit -m "feat: populate base_domain on discovered_links insert"
```

---

## Task 6: Normalize `page_snapshots.domain` on insert — `snapshot_store.py`

**Files:**
- Modify: `src/database/snapshot_store.py:6,40-41`

- [ ] **Step 1: Replace raw netloc with extract_base_domain**

Replace the urlparse import usage. At top of file, add:
```python
from src.utils.domain_extractor import extract_base_domain
```

Replace lines 39-41:
```python
    # Extract domain from URL
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
```

With:
```python
    # Extract normalized base domain from URL
    domain = extract_base_domain(url)
```

The `urlparse` import can stay if used elsewhere in the file; if not, remove it.

- [ ] **Step 2: Commit**

```bash
git add src/database/snapshot_store.py
git commit -m "fix: use extract_base_domain for page_snapshots.domain on insert"
```

---

## Task 7: Fix ScraperUI YAML lookup to use `extract_base_domain`

**Files:**
- Modify: `streamlit_app/pages/scraper_ui.py:70-76,82-87`

Note: The www-stripping fix was already partially applied. This task replaces it with the proper `extract_base_domain()` call for full subdomain normalization.

- [ ] **Step 1: Add import and update both lookup functions**

Add import at top of file:
```python
from src.utils.domain_extractor import extract_base_domain
```

In `_find_cached_yamls()`, replace domain extraction:
```python
    parsed = urlparse(url)
    domain = extract_base_domain(url)
    domain_dir = SCRAPES_DIR / domain
```

In `_find_cached_yaml_for_path()`, same change:
```python
    domain = extract_base_domain(url)
    domain_dir = SCRAPES_DIR / domain
```

Remove the `if domain.startswith("www."):` lines added earlier (now handled by `extract_base_domain`).

- [ ] **Step 2: Commit**

```bash
git add streamlit_app/pages/scraper_ui.py
git commit -m "fix: use extract_base_domain for ScraperUI YAML lookup"
```

---

## Task 8: Fix `link_discoverer.py` domain comparison

**Files:**
- Modify: `src/scraper/link_discoverer.py:123,180,183`

Currently uses raw `urlparse().netloc` for same-domain checks, so `www.gameonguelph.ca` links on a `gameonguelph.ca` page would be rejected. Normalize both sides.

- [ ] **Step 1: Add import and normalize domain comparisons**

Add import at top of file:
```python
from src.utils.domain_extractor import extract_base_domain
```

Line 123, change:
```python
        base_domain = urlparse(base_url).netloc.lower()
```
To:
```python
        base_domain = extract_base_domain(base_url)
```

Line 180-183, change:
```python
        link_domain = parsed.netloc.lower()

        # Check if same domain
        if link_domain != base_domain:
```
To:
```python
        link_domain = extract_base_domain(url)

        # Check if same base domain (normalizes www. and subdomains)
        if link_domain != base_domain:
```

- [ ] **Step 2: Commit**

```bash
git add src/scraper/link_discoverer.py
git commit -m "fix: normalize domain comparison in link_discoverer"
```

---

## Task 9: Verify end-to-end

- [ ] **Step 1: Run existing tests**

```bash
cd C:/Users/mathe/VSCode/aa_RecLeagueDB
python -m pytest tests/test_domain_extractor.py -v
python -m pytest tests/test_link_discoverer.py -v
```

Expected: All pass.

- [ ] **Step 2: Verify DB state**

```bash
source <(grep SUPABASE_DB_URL .env) && psql "$SUPABASE_DB_URL" -c "
-- Confirm no www. in any base_domain/domain column
SELECT 'scrape_queue' as tbl, count(*) FROM scrape_queue WHERE base_domain LIKE 'www.%'
UNION ALL
SELECT 'discovered_links', count(*) FROM discovered_links WHERE base_domain LIKE 'www.%'
UNION ALL
SELECT 'page_snapshots', count(*) FROM page_snapshots WHERE domain LIKE 'www.%'
UNION ALL
SELECT 'leagues_metadata', count(*) FROM leagues_metadata WHERE base_domain LIKE 'www.%';
"
```

Expected: All counts = 0.

- [ ] **Step 3: Final commit (if any fixups needed)**
