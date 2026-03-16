# Plan: Crawler depth, scoring overhaul, and 5-way classification

**Date:** 2026-03-16
**Branch:** `feat/parent-child-merge`
**Triggered by:** capitalvolley.ca scrape failure — only 3 beach volleyball leagues extracted from index page; 3 court volleyball leagues with full detail pages at `/event/*` were never reached.

---

## Problem analysis

capitalvolley.ca has a 3-level URL hierarchy:

```
/activity-type/leagues          (LEAGUE_INDEX — lists both sports)
  /activity/court-volleyball    (sub-index — links to 3 event pages)
    /event/monday-...           (LEAGUE_DETAIL — full data: $247 indiv, $1399 team, venue, dates)
    /event/tuesday-...          (LEAGUE_DETAIL)
    /event/wednesday-...        (LEAGUE_DETAIL)
  /activity/beach-volleyball    (sub-index — offseason, no current events)
```

The scraper entered at `/activity-type/leagues`, correctly classified it as LEAGUE_INDEX, and `_follow_index_links` found the child links. But the extraction only produced 3 beach volleyball leagues attributed to the index URL. The court volleyball detail pages were never reached.

### Root causes

1. **Crawler doesn't recurse into LEAGUE_DETAIL pages.** `_follow_index_links` (smart_crawler.py:127-131) collects LEAGUE_DETAIL pages but never follows their links. `/activity/court-volleyball` → `/event/*` links are lost.

2. **Link scoring tiers miscalibrated.** Sport names and structural keywords like `league`, `division`, `pricing` are stuck at medium priority (50 pts), below the 100-point threshold used in `crawl()` Step A. A "Court Volleyball" link (50 pts) is never followed.

3. **No MEDIUM_DETAIL tier.** The classifier is binary useful/useless — standings, team rosters, rules pages are classified OTHER and dropped. These pages are valuable for later merge/team-count verification.

4. **Sport keywords are hardcoded** in `yaml_link_parser.py` rather than derived from `sss_codes.py:SPORT_CODES`.

5. **SCHEDULE pages are collected for immediate extraction** but they're better suited for later scraping (team counts, matchup verification).

---

## Current link scoring (yaml_link_parser.py)

**High priority (+100 pts):**
```
register, signup, sign up, registration, schedule, standings, upcoming,
leagues, games, season, current, join, enroll, programs, results, details,
more info, more information
```

**Medium priority (+50 pts):**
```
league, division, divisions, team, teams, rules, pricing, format,
competition, sport, sports, calendar, scores, program,
volleyball, basketball, soccer, softball, baseball, hockey, football,
dodgeball, badminton, tennis, pickleball, ultimate, frisbee, lacrosse, rugby
```

---

## New design

### Classifier: 5 page types

Update the Haiku classifier prompt in `page_type_classifier.py` to return one of 5 types:

```
LEAGUE_INDEX   - overview listing multiple leagues/divisions with links to details
LEAGUE_DETAIL  - specific league page: fees, venue, schedule, registration info
MEDIUM_DETAIL  - standings, statistics, team rosters, team listings, rules, policies
SCHEDULE       - game matchups with dates/times/teams
OTHER          - homepage, login, about, contact, blog, etc.
```

Update `_VALID` set to include `MEDIUM_DETAIL`.

### Link scoring: 2 tiers

**High priority (100 pts):**
```
# Existing navigation/action keywords
register, signup, sign up, registration, schedule, standings, upcoming,
leagues, games, season, current, join, enroll, programs, results, details,
more info, more information,
# Promoted structural keywords
league, division, divisions, team, teams, rules, pricing, format,
competition, sport, sports, calendar, scores, program
# Dynamic sport names from SPORT_CODES (see Step 2)
volleyball, basketball, soccer, softball, hockey, football, dodgeball, ...
```

**Medium priority (50 pts):**
```
(reserved for future keywords — currently empty after promotions)
```

All current medium keywords move to high priority. Sport names also go to 100 since sport-named pages on league sites are almost always LEAGUE_INDEX or LEAGUE_DETAIL pages worth following.

### Crawler decision matrix

How `_follow_index_links` handles each classified page:

| Haiku classification | Link score >= 100 | Link score < 100 |
|---|---|---|
| **LEAGUE_INDEX** | Collect + recurse | Collect + recurse |
| **LEAGUE_DETAIL** | Collect + recurse | Collect (no recurse) |
| **SCHEDULE** | Store in `scrape_detail` | Store in `scrape_detail` |
| **MEDIUM_DETAIL** | Store in `scrape_detail` | Store in `scrape_detail` |
| **OTHER** | Collect + recurse | Skip |

Key behaviors:
- **LEAGUE_INDEX**: always collect + recurse regardless of score (classifier signal is strong)
- **LEAGUE_DETAIL**: always collect; recurse only if score >= 100 (high-scored detail pages likely have child links worth following)
- **SCHEDULE / MEDIUM_DETAIL**: always store in `scrape_detail` for later processing (never recurse, never extract now)
- **OTHER with score >= 100**: collect + recurse (existing Step A behavior — high-scored links followed regardless of classification)
- **OTHER with score < 100**: skip

### `scrape_detail` table

New table to store supporting URLs discovered during crawl for later processing:

```sql
CREATE TABLE scrape_detail (
    detail_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    scrape_id UUID REFERENCES scrape_queue(scrape_id),
    url TEXT NOT NULL,
    page_type TEXT NOT NULL,          -- 'MEDIUM_DETAIL' or 'SCHEDULE'
    parent_url TEXT,                  -- the page where this link was found
    yaml_content TEXT,                -- cached YAML from crawl (avoid re-fetch)
    full_text TEXT,                   -- cached full text from crawl
    status TEXT DEFAULT 'PENDING',    -- PENDING / COMPLETED / SKIPPED
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Implementation steps

### Step 1: Update classifier to 5 types

**File:** `src/scraper/page_type_classifier.py`

- Update `_PROMPT` to include MEDIUM_DETAIL:
  ```
  LEAGUE_INDEX   - overview listing multiple leagues/divisions with links to details
  LEAGUE_DETAIL  - specific league page: fees, venue, schedule, registration info
  MEDIUM_DETAIL  - standings, statistics, team rosters, team listings, rules, policies
  SCHEDULE       - game matchups with dates/times/teams
  OTHER          - homepage, login, about, contact, blog, etc.
  ```
- Add `"MEDIUM_DETAIL"` to `_VALID` set

### Step 2: Restructure link scoring + dynamic sport keywords

**File:** `src/scraper/yaml_link_parser.py`

#### 2a. Generate sport keywords from SSS codes

Add at module level:

```python
from src.config.sss_codes import SPORT_CODES

_SPORT_KEYWORDS: set[str] = set()
for _sport_name in SPORT_CODES.values():
    for _word in _sport_name.lower().split():
        if len(_word) > 2:  # skip "&", "up", etc.
            _SPORT_KEYWORDS.add(_word)
```

#### 2b. Merge all keywords into high priority

Move all current medium keywords + sport keywords into `high_priority_keywords`:

```python
high_priority_keywords = [
    # Navigation/action
    "register", "signup", "sign up", "registration",
    "schedule", "standings", "upcoming", "leagues", "games",
    "season", "current", "join", "enroll", "programs",
    "results", "details", "more info", "more information",
    # Structural (promoted from medium)
    "league", "division", "divisions", "team", "teams",
    "rules", "pricing", "format", "competition",
    "sport", "sports", "calendar", "scores", "program",
]
```

In `score_links()`, after checking `high_priority_keywords`, also check `_SPORT_KEYWORDS`:

```python
# Sport name keywords (also high priority)
if link.score < 100:
    url_words = set(url_lower.split())
    if url_words & _SPORT_KEYWORDS or any(kw in url_lower for kw in _SPORT_KEYWORDS):
        link.score += 100
```

Remove `medium_priority_keywords` list (or leave empty for future use).

#### 2c. Update `_CATEGORY_KEYWORDS["DETAIL"]`

Remove hardcoded sport names. In `infer_link_category()`, add a dynamic check:

```python
# Check sport keywords for DETAIL category
if any(kw in text for kw in _SPORT_KEYWORDS):
    return "DETAIL"
```

### Step 3: Overhaul `_follow_index_links` decision logic

**File:** `src/scraper/smart_crawler.py`

#### 3a. Score candidates before fetching

After building the `candidates` list (line 118), score them:

```python
from src.scraper.yaml_link_parser import score_links
candidates = score_links(candidates)
```

#### 3b. Implement the decision matrix

Replace the current classify-and-branch block (lines 120-155) with the new matrix:

```python
for link in candidates:
    visited.add(link.url)
    try:
        page_yaml, page_meta = fetch_page_as_yaml(link.url, ...)
        page_type = classify_page(page_yaml)
        full_text = page_meta.get("full_text", "") if page_meta else ""

        if page_type == "LEAGUE_INDEX":
            # Always collect + recurse
            logger.info(f"[Index->INDEX depth={current_depth}] {link.url}")
            league_pages.append((link.url, page_yaml, full_text))
            if parent_map is not None:
                parent_map[link.url] = index_url
            if current_depth < max_index_depth:
                _follow_index_links(...)

        elif page_type == "LEAGUE_DETAIL":
            # Always collect; recurse only if high-scored
            logger.info(f"[Index->DETAIL] {link.url}")
            league_pages.append((link.url, page_yaml, full_text))
            if parent_map is not None:
                parent_map[link.url] = index_url
            if link.score >= 100 and current_depth < max_index_depth:
                _follow_index_links(...)

        elif page_type in ("SCHEDULE", "MEDIUM_DETAIL"):
            # Store in scrape_detail for later processing
            logger.info(f"[Index->{page_type}] {link.url} (saved for later)")
            _store_scrape_detail(
                parent_url=index_url,
                url=link.url,
                page_type=page_type,
                yaml_content=page_yaml,
                full_text=full_text,
            )

        else:  # OTHER
            if link.score >= 100:
                # High-scored OTHER — collect + recurse
                logger.info(f"[Index->OTHER-scored] {link.url}")
                league_pages.append((link.url, page_yaml, full_text))
                if current_depth < max_index_depth:
                    _follow_index_links(...)
            # else: skip

    except Exception as e:
        logger.warning(f"[Index follow] Fetch failed {link.url}: {e}")
```

#### 3c. Add `_store_scrape_detail` helper

New function in `smart_crawler.py` that inserts into `scrape_detail`:

```python
def _store_scrape_detail(
    parent_url: str,
    url: str,
    page_type: str,
    yaml_content: str = "",
    full_text: str = "",
) -> None:
    """Store a MEDIUM_DETAIL or SCHEDULE URL in scrape_detail for later processing."""
    # Look up scrape_id from scrape_queue by matching parent_url or base_domain
    # Insert into scrape_detail table
    ...
```

This needs a Supabase client import. Follow the pattern used in `src/database/writer.py` for DB access.

#### 3d. Update `crawl()` Step A

Apply the same decision matrix in the Step A loop (lines 273-318). Currently Step A collects everything scored 100+ regardless of classification. Update to use the same 5-way branching: LEAGUE_INDEX/LEAGUE_DETAIL get collected, SCHEDULE/MEDIUM_DETAIL go to `scrape_detail`, OTHER gets collected only if scored 100+.

### Step 4: Migration for `scrape_detail` table

**File:** `migrations/012_create_scrape_detail.sql`

```sql
CREATE TABLE scrape_detail (
    detail_id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    scrape_id UUID REFERENCES scrape_queue(scrape_id),
    url TEXT NOT NULL,
    page_type TEXT NOT NULL,
    parent_url TEXT,
    yaml_content TEXT,
    full_text TEXT,
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scrape_detail_scrape_id ON scrape_detail(scrape_id);
CREATE INDEX idx_scrape_detail_status ON scrape_detail(status);
```

### Step 5: Tests

**File:** `tests/test_page_type_classifier.py` (new)

1. Verify `_VALID` contains all 5 types including `MEDIUM_DETAIL`.

**File:** `tests/test_yaml_link_parser.py` (existing or new)

2. `_SPORT_KEYWORDS` contains expected words: "volleyball", "basketball", "soccer", "dodgeball", "hockey", "lacrosse", "softball", "football", etc.
3. `score_links` gives "Court Volleyball" link 100 points (sport keyword now high priority).
4. `score_links` gives "Volleyball League" link 100 points (not 200 — should only trigger once).

**File:** `tests/test_smart_crawler.py` (new or existing)

5. LEAGUE_DETAIL page with score >= 100: collected + links recursed into.
6. LEAGUE_DETAIL page with score < 100: collected, links NOT recursed into.
7. MEDIUM_DETAIL page: stored in `scrape_detail`, not collected for extraction, not recursed.
8. SCHEDULE page: stored in `scrape_detail`, not recursed.
9. OTHER with score >= 100: collected + recursed.
10. OTHER with score < 100: skipped entirely.

---

## Files to change

| File | Change |
|------|--------|
| `src/scraper/page_type_classifier.py` | Add MEDIUM_DETAIL to prompt and `_VALID` set |
| `src/scraper/yaml_link_parser.py` | Derive sport keywords from `SPORT_CODES`; promote all keywords to high priority |
| `src/scraper/smart_crawler.py` | 5-way decision matrix in `_follow_index_links` and Step A; LEAGUE_DETAIL recursion; `_store_scrape_detail` helper |
| `migrations/012_create_scrape_detail.sql` | New table for MEDIUM_DETAIL/SCHEDULE URLs |
| `tests/test_page_type_classifier.py` | Test 5-type classification |
| `tests/test_yaml_link_parser.py` | Test dynamic sport keywords and scoring |
| `tests/test_smart_crawler.py` | Test decision matrix behaviors |

## Out of scope

- Re-scraping capitalvolley.ca (do manually after implementing)
- Building the UI for reviewing `scrape_detail` entries (future work)
- Changing the LLM extraction logic (extraction is fine; problem was pages never fetched)

## Verification

After implementing, re-run the scraper on capitalvolley.ca with `force_refresh=True` and confirm:
1. `/activity/court-volleyball` is visited and classified (check logs)
2. `/event/monday-...`, `/event/tuesday-...`, `/event/wednesday-...` are visited as LEAGUE_DETAIL
3. 6+ leagues extracted (3 court volleyball + beach volleyball if in season)
4. Court volleyball leagues: sport_name="Volleyball", venue_name set, team_fee=1399, individual_fee=247, players_per_side=6
5. Any standings/rules pages found are stored in `scrape_detail` with correct page_type
