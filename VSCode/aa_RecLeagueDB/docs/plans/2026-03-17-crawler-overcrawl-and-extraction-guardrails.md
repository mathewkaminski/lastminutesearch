# Plan: Crawler Over-Crawl Fix & Extraction Guardrails

**Date:** 2026-03-17
**Problem:** racentre.com scraped 61 pages (should be ~10), extracted 90 "leagues" including swimming lessons, Zumba, bridge clubs, and children's camps. Only 4-10 made it to DB, with 99 validation errors.

## Root Cause Analysis

### Issue 1: Crawler fetches duplicate pages
The site's nav bar appears on EVERY page. When the crawler visits `sports-recreation.html` (classified LEAGUE_INDEX or OTHER with score >= 100), it follows ALL nav links again. Each sport page's nav bar re-lists the same links. Result: 18 pages fetched twice (61 total, only 43 unique paths).

The `_normalize_url` function strips `www.` and fragments correctly, and the `visited` set catches most duplicates. But `collected_pages` is a plain list with no dedup check — pages can be appended multiple times if they're reached via different code paths (Layer 0 `_follow_index_links` + Step A).

**Files:** `src/scraper/smart_crawler.py`

### Issue 2: Crawler follows entire site nav, not just league-relevant links
The racentre.com nav bar has sections for Fitness, Children, Aquatics, Events, etc. Links like "Swim Lessons", "Junior Athletes", "Summer Camps" score 100 because they contain structural keywords ("programs", "sports", "camps"). The crawler happily follows them all.

There's no **page budget** — the crawler will fetch as many pages as the link tree provides.

**Files:** `src/scraper/smart_crawler.py`

### Issue 3: LLM extraction has no guardrails about what counts as a "league"
The extraction prompt says "Extract ALL distinct leagues from this page" with no definition of what a league IS. Swimming lessons, Zumba classes, duplicate bridge, and children's day camps are extracted as "leagues." The prompt needs guardrails to exclude:
- Individual lessons/classes (swimming, yoga, personal training)
- Drop-in sessions (unless structured as a league with teams)
- Children's/youth programs (we only want adult rec leagues)
- Card games, board games, social clubs (bridge, euchre, chess)
- Fitness classes (Zumba, line dancing, group fitness)

**Files:** `src/extractors/yaml_extractor.py`

### Issue 4: No dedup on collected_pages before extraction
Even after fixing the visited set, `collected_pages` can contain the same URL multiple times. The extraction pipeline processes every entry, resulting in duplicate league extractions (e.g., 3 identical Squash leagues in DB).

**Files:** `scripts/extract_leagues_yaml.py` or `src/scraper/smart_crawler.py`

## Implementation Steps

### Step 1: Add page budget to crawler
**File:** `src/scraper/smart_crawler.py`

Add a `MAX_PAGES` constant (default 25) at module level. Check against `len(collected_pages)` before fetching each new page in both `_follow_index_links` and Step A. When the budget is hit, log a warning and stop fetching.

```python
MAX_PAGES = 25  # Hard cap on pages fetched per crawl
```

In `_follow_index_links`, add at top of the loop:
```python
if len(league_pages) >= MAX_PAGES:
    logger.warning(f"Page budget reached ({MAX_PAGES}), stopping link following")
    break
```

Same check in Step A loop (line ~369):
```python
if len(collected_pages) >= MAX_PAGES:
    logger.warning(f"Page budget reached ({MAX_PAGES}), stopping Step A")
    break
```

**Verify:** Run crawler on racentre.com, confirm it stops at 25 pages.

### Step 2: Dedup collected_pages by normalized URL
**File:** `src/scraper/smart_crawler.py`

Before returning from `crawl()`, dedup `collected_pages` by normalized URL, keeping the first occurrence:

```python
# Dedup collected_pages by normalized URL (keep first occurrence)
seen_collected = set()
deduped = []
for url, yaml_content, full_text in collected_pages:
    norm = _normalize_url(url)
    if norm not in seen_collected:
        seen_collected.add(norm)
        deduped.append((url, yaml_content, full_text))
collected_pages = deduped
```

Add this just before the `if not collected_pages:` check near the end of `crawl()`.

**Verify:** Run crawler on racentre.com, confirm no duplicate URLs in output.

### Step 3: Add extraction guardrails to LLM prompt
**File:** `src/extractors/yaml_extractor.py`

In `_build_yaml_extraction_prompt`, add the following to the `INSTRUCTIONS` section (after line 265 "Extract ALL distinct leagues from this page"):

```
- ONLY extract ADULT recreational sports LEAGUES — structured programs where teams/individuals register for a multi-week season with scheduled games or matches
- DO NOT extract: children's/youth programs, swimming lessons, fitness classes (Zumba, yoga, dance), drop-in sessions, card/board game clubs (bridge, euchre, chess), training programs (CIT, LIT), camps, or one-time events
- A "league" must involve: (a) a sport or physical competition, (b) scheduled recurring games/matches, (c) registration for adults. If unsure, skip it.
```

**Verify:** Run dry-run extraction on racentre.com cached YAML. Confirm swimming lessons, Zumba, bridge, children's camps are NOT extracted. Ball Hockey, Softball, Volleyball, Pickleball, Squash, Curling, Soccer, Badminton SHOULD be extracted.

### Step 4: Add tests

**File:** `tests/test_smart_crawler.py`
- Test that `collected_pages` has no duplicate URLs after `crawl()` returns
- Test that page budget stops crawling when hit

**File:** `tests/test_yaml_extractor.py`
- No new extraction tests needed (prompt changes are behavioral, covered by dry-run verification)

### Step 5: Run full test suite
Run `python -m pytest tests/ -x -q` and confirm no regressions (expect same pre-existing failures only: `test_classify_truncates_large_input` and `test_match_league_by_division`).

### Step 6: Verification — dry-run racentre.com
Run extraction in dry-run mode:
```python
from scripts.extract_leagues_yaml import extract_leagues_from_url
result = extract_leagues_from_url('https://www.racentre.com/ra-sportsleagues.html', use_cache=True, dry_run=True)
```

**Expected:**
- Pages fetched: <= 25 (was 61)
- No duplicate pages
- Leagues extracted should be ONLY adult rec sports: Ball Hockey, Softball, Volleyball (multiple divisions), Pickleball, Squash, Curling, Badminton, Soccer 7s, Archery
- Should NOT include: Swimming lessons, Zumba, Judo (if it's a class not a league), Duplicate Bridge, Euchre, Goodfit fitness, children's camps

### Step 7: Clean up racentre DB entries
After confirming the fix works, delete the bad entries from `leagues_metadata`:
```sql
DELETE FROM leagues_metadata WHERE url_scraped ILIKE '%racentre%';
```
Then re-run the scraper for real (not dry-run) to get clean data.

## Out of Scope
- Changing the 5-way classifier or link scoring tiers (working correctly)
- Building UI for scrape_detail review
- Modifying the quality gate thresholds

## Key Files Reference
- `src/scraper/smart_crawler.py` — crawler with decision matrix (Steps 1, 2)
- `src/extractors/yaml_extractor.py:214` — `_build_yaml_extraction_prompt()` (Step 3)
- `scripts/extract_leagues_yaml.py` — orchestrator that calls crawler + extractor
- `tests/test_smart_crawler.py` — crawler tests (Step 4)
