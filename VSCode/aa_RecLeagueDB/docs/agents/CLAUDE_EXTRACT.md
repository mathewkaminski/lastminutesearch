# CLAUDE_EXTRACT - Scraping & Extraction Context

**Purpose:** Web scraping with YAML accessibility trees, LLM-based data extraction, multi-page navigation
**When to use:** Building/debugging extraction pipeline, improving scrapers, handling complex websites
**Related contexts:** Use [CLAUDE_MANAGE.md](CLAUDE_MANAGE.md) after extraction for validation

---

## Pipeline

URL → BFS crawl (5-way decision matrix) → YAML snapshots → GPT-4o extraction → `leagues_metadata`

**Key files:**

| File | Role |
|------|------|
| `scripts/smart_scraper.py` | **Primary L1**: BFS Playwright + Haiku classifier + GPT-4o extraction |
| `scripts/super_scraper.py` | L1.5: Two-pass deep crawl + team count + reconciliation |
| `scripts/extract_leagues_yaml.py` | Legacy L1: YAML pipeline (bulk, still used) |
| `scripts/mcp_agent_scraper.py` | L0: MCP agent (manual/complex, legacy) |
| `src/scraper/smart_crawler.py` | Core BFS crawler — 5-way page-type decision matrix |
| `src/scraper/page_type_classifier.py` | Haiku classifier: HOME / LEAGUE_LIST / LEAGUE_DETAIL / UNRELATED / GENERIC |
| `src/scraper/playwright_yaml_fetcher.py` | Playwright → YAML (rate limit detection, retry) |
| `src/scraper/yaml_link_parser.py` | Link discovery and scoring from YAML |
| `src/extractors/yaml_extractor.py` | GPT-4o extraction from YAML/snapshots |
| `src/database/link_store.py` | Discovered link storage |
| `src/database/snapshot_store.py` | Page snapshot storage and retrieval |

---

## Scraping Stack

| Level | Script | Trigger | Description |
|-------|--------|---------|-------------|
| L1 | `smart_scraper.py` | Automated bulk (primary) | BFS + Haiku 5-way classifier + GPT-4o. Replaces `mcp_agent_scraper.py` for most sites. |
| L1 (legacy) | `extract_leagues_yaml.py` | Automated bulk | Older YAML pipeline — still used for bulk queue runs |
| L1.5 | `super_scraper.py` | Auto when `quality_score < 75` | Pass 1: deep BFS (depth=4, threshold=60). Pass 2: Playwright team count. Reconciliation: MERGE / REPLACE (THIN contradicted) / REVIEW (BORDERLINE contradicted) |
| L0 | `mcp_agent_scraper.py` | Manual | Playwright MCP agent — manual/complex sites, legacy fallback |
| L2 | Firecrawl API | Last resort | Paid — use only when L1/L1.5 fail |

**Quality thresholds** (`src/config/quality_thresholds.py`):
- `DEEP_SCRAPE_THRESHOLD = 75` — triggers super scraper
- `AUTO_REPLACE_THRESHOLD = 60` — reconciler auto-archives existing record when contradicted

**Caching:** Snapshots cached in `scrapes/{domain}/{timestamp}_{page_type}.yaml` (gitignored), TTL 7 days

---

## Link Scoring

`src/scraper/yaml_link_parser.py` scores links found in YAML accessibility trees:

| Priority | Score | Keywords |
|----------|-------|---------|
| HIGH | 100 | registration, register, signup, schedule, standings, scores, bracket |
| MEDIUM | 50 | rules, teams, pricing, fees, venue, divisions, levels, location |
| LOW | 0 | social, contact, about, privacy, legal, help (not followed) |

Links ≥ 100 are fetched. Discovered links stored in `discovered_links` table.

---

## SSS Codes

Sport/season format: `XYY` — first digit = season, last two = sport. Full reference: `docs/SSS_CODES.md`

---

## Roadmap Notes

- **Team Count Enrichment** — Shipped. Teams mode in `fill_in_leagues.py` → `src/checkers/league_checker.py`
- **Firecrawl Fallback** — Integrated as L2 via `src/scraper/firecrawl_client.py`
- **Historical Season Tracking** — Future. Deferred to Parking Lot.
- **Parent-child merge + tiered quality gate** — In progress. See `docs/plans/2026-03-15-parent-child-merge.md` and `docs/plans/2026-03-17-crawler-guardrails-v2.md`

---

**When extraction is done, switch to [CLAUDE_MANAGE.md](CLAUDE_MANAGE.md) for validation, deduplication, and cleaning.**
