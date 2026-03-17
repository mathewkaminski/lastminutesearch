# RecSportsDB — CLAUDE.md

**Last Updated:** 2026-03-14
**Project Status:** Active Development

---

## Quick Start — Pick Your Context

| Task | Context File | Streamlit Pages |
|------|-------------|-----------------|
| **URL Discovery** | [CLAUDE_SEARCH.md](docs/agents/CLAUDE_SEARCH.md) | Campaign Manager, Queue Monitor |
| **Scraping & Extraction** | [CLAUDE_EXTRACT.md](docs/agents/CLAUDE_EXTRACT.md) | Queue Monitor (run scraper), Scraper UI (in progress) |
| **Data Cleaning & Validation** | [CLAUDE_MANAGE.md](docs/agents/CLAUDE_MANAGE.md) | Leagues Viewer, Data Quality, URL Merge, League Merge, Org View |
| **Enrichment** | [CLAUDE_MANAGE.md](docs/agents/CLAUDE_MANAGE.md) | Fill In Leagues, Venues Enricher |
| **Analytics & Queries** | [CLAUDE_QUERY.md](docs/agents/CLAUDE_QUERY.md) | (future) |

**Current Focus:** `CLAUDE_EXTRACT.md` (crawler guardrails, parent-child merge) + `CLAUDE_MANAGE.md` (tiered quality gate)

**Future Work:** [Parking_Lot.md](Parking_Lot.md)

---

## Project Mission

**RecSportsDB** is an analytics platform for adult recreational sports leagues in North America.

**Goal:** Build a normalized, queryable database of structured and unstructured league data optimized for pricing intelligence, scheduling pattern analysis, and competitive landscape mapping.

**Data Priority:** Current seasons first. Historical data deferred (see Parking Lot).

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Database | Supabase (PostgreSQL + pgvector) |
| Scraping L1 | `scripts/smart_scraper.py` — primary pipeline (BFS + 5-way classifier + GPT-4o) |
| Scraping L1.5 | `scripts/super_scraper.py` — deep crawl + team count, auto-triggered for low quality |
| Scraping L0 | `scripts/mcp_agent_scraper.py` — manual/complex sites (legacy fallback) |
| Scraping L2 | Firecrawl API — paid fallback only |
| LLM | OpenAI GPT-4o (extraction + enrichment) |
| Embeddings | OpenAI text-embedding-3-small (1536d) |
| Search | Serper API (Google search via API) |
| UI | Streamlit (Docker-hosted) |

---

## Project Structure

```
aa_RecLeagueDB/
├── CLAUDE.md                    # This file — project router
├── Parking_Lot.md               # Future work
├── .env                         # Secrets (NOT in git)
├── Dockerfile / requirements.txt
│
├── docs/
│   ├── agents/                  # Claude context files
│   │   ├── CLAUDE_SEARCH.md     # URL discovery
│   │   ├── CLAUDE_EXTRACT.md    # Scraping & extraction
│   │   ├── CLAUDE_MANAGE.md     # Data management
│   │   └── CLAUDE_QUERY.md      # Analytics
│   ├── plans/                   # Implementation plans (dated)
│   ├── DATABASE_SCHEMA.md       # Full schema reference
│   └── SSS_CODES.md             # Sport/season coding reference
│
├── src/
│   ├── search/                  # URL discovery & queue management
│   ├── scraper/                 # Web scraping (YAML/smart crawler stack)
│   ├── extractors/              # LLM-based data extraction
│   ├── database/                # Supabase client & validators
│   ├── enrichers/               # Field enrichment, venue lookup, confidence scoring
│   ├── checkers/                # League checker, team count extraction, Playwright navigator
│   ├── analytics/               # Analysis modules (future)
│   ├── config/                  # SSS codes, search filters, quality thresholds
│   ├── agents/                  # Agent modules (future)
│   └── utils/
│
├── streamlit_app/
│   ├── app.py                   # Entry point + navigation
│   └── pages/
│       ├── campaign_manager.py      # Search: city + sport → run Serper, queue URLs
│       ├── queue_monitor.py         # Search/Scrape: browse queue, bulk-update, run scraper, screen URLs
│       ├── scraper_ui.py            # Scrape: view source YAML, re-scrape with Firecrawl, extract leagues
│       ├── fill_in_leagues.py       # Enrich: multi-mode enrichment (Fill Fields / Teams / Deep-dive)
│       ├── leagues_viewer.py        # Manage: browse/filter leagues_metadata, export CSV
│       ├── data_quality.py          # Manage: quality score distribution, field coverage
│       ├── url_merge.py             # Manage: dedup within a single url_scraped
│       ├── league_merge.py          # Manage: cross-URL dedup using 6-field identity model
│       ├── merge_tool.py            # Manage: surface and resolve suspected duplicate league records
│       ├── venues_enricher.py       # Enrich: resolve venue names via Google Places API
│       └── org_view.py              # Manage: browse leagues grouped by base_domain, set listing_type
│
├── scripts/
│   ├── smart_scraper.py         # L1 primary: BFS Playwright + Haiku classifier + GPT-4o extraction
│   ├── super_scraper.py         # L1.5: Two-pass deep crawl + team count + reconciliation
│   ├── extract_pipeline.py      # Orchestrator: ties all pipeline phases together
│   ├── extract_leagues_yaml.py  # Legacy L1: Automated YAML pipeline (bulk)
│   ├── mcp_agent_scraper.py     # L0: MCP agent (manual/complex sites, legacy)
│   ├── count_teams_scraper.py   # Standalone team count scraper
│   ├── backfill_city.py         # Maintenance: backfill city field
│   ├── backfill_listing_type.py # Maintenance: backfill listing_type field
│   └── yaml_snapshot_cli.py     # CLI: inspect YAML snapshots
│
├── tests/                       # All test files
├── migrations/                  # SQL migration files
├── scrapes/                     # Scrape cache (gitignored)
└── archive/                     # Old plans, session notes, scrape snapshots
```

---

## Key Architectural Decisions

1. **Two-tool extraction:** Tool 1 = core metadata, Tool 2 = team count enrichment (optional post-ingestion)
2. **Bifurcated DB:** SQL (`leagues_metadata`) for structured data, pgvector (`league_vectors`) for RAG
3. **SSS codes:** 3-digit sport/season format XYY — full reference in [docs/SSS_CODES.md](docs/SSS_CODES.md)
4. **Scraping cascade:** L1 `smart_scraper.py` (primary, 5-way BFS decision matrix) → L1.5 `super_scraper.py` (auto-triggered for quality_score < 75) → L0 `mcp_agent_scraper.py` (manual/complex) → L2 Firecrawl (paid, last resort). Core routing lives in `src/scraper/smart_crawler.py`.
5. **Full schema + UUID model:** [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md)

---

## Environment Variables

In `.env` (root, never commit):
```bash
SUPABASE_URL=
SUPABASE_KEY=          # service role key
PSQL_CONNECTION_STRING= # direct psql connection to Supabase PostgreSQL
OPENAI_API_KEY=
SERPER_API_KEY=
FIRECRAWL_API_KEY=
```

---

## Development Workflow

1. Pick the right context file from the Quick Start table above
2. Check [docs/plans/](docs/plans/) for any active implementation plans
3. Run tests from `tests/` directory
4. Validate data after any extraction: `python scripts/extract_leagues_yaml.py <url>`
5. Keep agent context files in sync when architecture changes

---

## Coding Standards

- **Style:** PEP 8, type hints, Google-style docstrings
- **Paths:** `pathlib`, not `os.path`
- **Errors:** Explicit exception handling with logging
- **Database:** Parameterized queries, use Supabase client
- **Naming:** `snake_case` files/functions/vars, `PascalCase` classes, `UPPER_SNAKE_CASE` constants

## What NOT to Touch

- `.env` — never commit to git
- `scrapes/` — gitignored scrape cache, don't manually edit
