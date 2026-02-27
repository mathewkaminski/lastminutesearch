# Smart Crawler Design

**Date:** 2026-02-27
**Status:** Approved

---

## Goal

Replace the MCP agent as the primary scraping pipeline with a deterministic Playwright crawler that uses a lightweight AI classifier to detect league pages, then hands confirmed league pages to a full GPT-4o extractor. The MCP agent (`mcp_agent_scraper.py`) becomes last-resort only.

---

## Problem With Current Approach

The MCP agent (Claude driving browser via `@playwright/mcp`) spends the majority of turns executing JavaScript on a small number of pages rather than navigating efficiently. In a recent Ottawa Volley Sixes run: 39 of 60 turns were `browser_run_code`, only 14 were actual page navigations. The agent is slow (~15 min/site), rate-limited at 30K tokens/min, and expensive.

---

## Architecture

Three sequential phases:

### Phase 1 — Navigate (deterministic, no AI)

Headless Playwright fetches pages and converts them to YAML accessibility trees (existing `playwright_yaml_fetcher.py`). Links are scored using `NAVIGATION_KEYWORDS` (existing `yaml_link_parser.py`):

- **Primary links** (score=100): `register`, `registration`, `schedule`, `standings`, `upcoming leagues`, `pricing`, `fees`, etc.
- **Secondary links** (score=50): `divisions`, `rules`, `teams`, `calendar`, `bracket`, etc.
- **Excluded** (score=0): social media, login, privacy, contact, etc.

### Phase 2 — Classify (lightweight AI, per page)

After each page fetch, Claude Haiku answers: *"Does this page contain sports league listings with registration info, fees, or schedules? YES or NO."*

Input is the first ~2000 tokens of the YAML (truncated for cost). No retries needed — a wrong NO is acceptable (we continue crawling); a wrong YES just triggers the extractor early.

### Phase 3 — Extract (GPT-4o, only on confirmed league pages)

Existing `yaml_extractor.py` runs on each page the classifier confirmed. After extraction, the crawler may go one additional level deeper from that page to capture league detail sub-pages (e.g. individual registration or standings pages).

---

## Navigation Algorithm

```
Layer 0: Home page
  → Score all links into PRIMARY (100) and SECONDARY (50) buckets

STEP A — Visit ALL primary links (always, no early exit):
  → Fetch YAML for each
  → Classify each with Haiku
  → Collect all pages where classifier returns YES

STEP B — (only if Step A found zero league pages)
  → Visit secondary links one at a time
  → Stop at first YES

STEP C — (only if Steps A+B found nothing)
  → From each primary page, follow the TOP-scored keyword link
  → Classify → stop at first YES
  → Repeat down to max depth 4 total layers

STOP conditions:
  → Max depth 4 reached with no leagues found → log, exit
  → Steps A+B+C each return results when leagues are confirmed
```

---

## Target Fields & Completeness Threshold

The extractor targets these 12 fields:

| Field | Notes |
|---|---|
| `organization_name` | Required (must be present) |
| `sport_season_code` | Required (SSS format) |
| `season_start_date` | YYYY-MM-DD |
| `season_end_date` | YYYY-MM-DD |
| `day_of_week` | Enum: Monday–Sunday |
| `start_time` | HH:MM:SS (earliest if multiple) |
| `team_fee` | Decimal |
| `individual_fee` | Decimal |
| `venue_name` | Freeform text |
| `competition_level` | e.g. Recreational, Intermediate |
| `gender_eligibility` | Enum: Mens, Womens, CoEd, Other, Unsure |
| `players_per_side` | Integer (e.g. 6 for 6v6) |

**DB write rule:**
- `organization_name` + `sport_season_code` must be present
- ≥50% of the remaining 10 fields filled → write to DB (tagged `PARTIAL` or better)
- <50% → log and skip (not written)

**`num_teams` is explicitly excluded** from this crawler. It is populated separately by `count_teams_scraper.py` after the fact.

---

## Components

### New files

| File | Responsibility |
|---|---|
| `src/scraper/smart_crawler.py` | BFS navigation engine; owns layer logic, link prioritization, early-exit rules; returns list of `(url, yaml)` pairs classified as league pages |
| `src/scraper/league_classifier.py` | Lightweight Haiku classifier; `has_league_data(yaml: str) -> bool` |
| `scripts/smart_scraper.py` | CLI entrypoint: `--url`, `--dry-run`, `--log-level` |

### Reused unchanged

| File | Role |
|---|---|
| `src/scraper/playwright_yaml_fetcher.py` | Page → YAML (headless Playwright + JS eval) |
| `src/scraper/yaml_link_parser.py` | Link scoring against `NAVIGATION_KEYWORDS` |
| `src/extractors/yaml_extractor.py` | Full GPT-4o league data extraction |
| `src/database/writer.py` | DB insert/update with deduplication |

### Modified

| File | Change |
|---|---|
| `src/database/writer.py` | Lower completeness write floor from 60% to 50% in `_prepare_for_insert()` |

---

## Full Data Flow

```
smart_scraper.py --url https://example.com
        │
        ▼
smart_crawler.crawl(url)
        │
        ├─ fetch home YAML         [playwright_yaml_fetcher]
        ├─ score all links         [yaml_link_parser]
        │
        ├─ STEP A: visit ALL primary links
        │     → fetch YAML → classify (Haiku) → collect YES pages
        │
        ├─ STEP B: (if A found nothing) visit secondary links, stop at first YES
        │
        ├─ STEP C: (if A+B found nothing) follow top link per branch, max depth 4
        │
        └─ returns [(url, yaml), ...] for confirmed league pages
                │
                ▼
        yaml_extractor.py          [GPT-4o, once per league page]
                │
                ├─ completeness ≥50%? → writer.py → leagues_metadata
                └─ completeness <50%? → log and skip
```

---

## What This Replaces

- `scripts/extract_leagues_yaml.py` — superseded by `scripts/smart_scraper.py` for bulk runs
- The MCP agent (`scripts/mcp_agent_scraper.py`) remains available as a last-resort manual tool for sites that require login, complex JS interactions, or multi-step flows the smart crawler can't handle

---

## Out of Scope

- `num_teams` — handled by `count_teams_scraper.py` separately
- Login-gated content — MCP agent only
- `stat_holidays`, `num_weeks`, `time_played_per_week` — extracted by GPT-4o if visible; not required for the 50% threshold
