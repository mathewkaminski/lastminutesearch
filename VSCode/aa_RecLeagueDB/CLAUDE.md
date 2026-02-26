# RecSportsDB Claude.md File

**Last Updated:** 2026-02-12  
**Project Status:** Active Development
**Primary Developer:** User (with Claude Code)

---

## 🚀 Quick Start - Which Context Do You Need?

Choose the appropriate specialized context file based on your current task:

| Task | Context File | Use When |
|------|-------------|----------|
| **URL Discovery** | [CLAUDE_SEARCH.md](agents/CLAUDE_SEARCH.md) | Finding new leagues to scrape, managing search queue |
| **Scraping & Extraction** | [CLAUDE_EXTRACT.md](agents/CLAUDE_EXTRACT.md) | Building/debugging web scraping, LLM extraction, multi-page navigation |
| **Data Cleaning & Validation** | [CLAUDE_MANAGE.md](agents/CLAUDE_MANAGE.md) | Validating data quality, deduplication, enrichment, re-scraping triggers |
| **Analytics & Queries** | [CLAUDE_QUERY.md](agents/CLAUDE_QUERY.md) | Answering questions about data, running analytics, multi-agent queries |

**Current Phase Focus:** Primarily `CLAUDE_SEARCH.md` `CLAUDE_EXTRACT.md` and `CLAUDE_MANAGE.md`

**Future Work:** Outlined in the Parking_Lot.md file

---

## Project Mission

**RecSportsDB** is an analytics platform for understanding pricing, scheduling, team count, venue locations, league rulesets, and more across adult recreational sports leagues in North America.

**Primary Objective:** Build a normalized, queryable database of structured and unstructured league data optimized for:
- Pricing intelligence (fee analysis, team counts, market positioning, venue locations)
- Scheduling pattern analysis (time slots, venue utilization, seasonal trends)
- Competitive landscape mapping (org density, market gaps, team counts, rule & format innovation)

**Target Scale (February 18th):** Proof of concept with 20-50 high-quality URLs containing 90% or more of all relevant leagues, then iterate based on insights.

**Data Priority:** Current seasons first, historical data secondary.

---

## Technology Stack

- **Language:** Python 3.10+
- **Database:** 
- Supabase (PostgreSQL + pgvector for embeddings)
- Structured: leagues_metadata table
- Unstructured: league_vectors table (RAG)
- **Web Scraping:**
  - Level 0: Playwright MCP Agent (manual/complex sites — `mcp_agent_scraper.py`)
  - Level 1: Playwright YAML pipeline (automated bulk — `extract_leagues_yaml.py`)
  - Level 2: Firecrawl API (paid fallback, minimize usage)
  - Retired: Selenium/undetected-chromedriver (kept in codebase, not used)
  - Caching: Snapshots stored in `scrapes/` (gitignored)
- **AI/LLM:** 
- Extraction: OpenAI GPT-4
- Embeddings: OpenAI text-embedding-3-small (1536 dimensions)
- Enrichment: GPT-4 for fuzzy matching, inference
- **Search:** Serper API (Google search results via API)
- **Development:**
- Version control: Git
- Testing: pytest
- Environment: python-dotenv
- Documentation: Markdown (Claude contexts)

---

## Project Structure

```
00_Scraping_Database/
├── docs/
│   ├── agents/           # Specialized Claude context files
│   │   ├── CLAUDE_EXTRACT.md   # Scraping & extraction context
│   │   ├── CLAUDE_MANAGE.md    # Data management context
│   │   ├── CLAUDE_SEARCH.md    # URL discovery context
│   │   └── CLAUDE_QUERY.md     # Analytics context
│   ├── EXTRACTION_ARCHITECTURE.md
│   ├── PHASE_4_QUICK_START.md
│   └── SSS_CODES.md      # Sport/season coding reference
├── src/                  # Python source code
│   ├── search/           # URL discovery & queue management (CLAUDE_SEARCH.md focus)
│   │   ├── serper_client.py       # Serper API wrapper
│   │   ├── query_generator.py     # Query building & fingerprinting
│   │   ├── result_processor.py    # Result validation & priority scoring
│   │   ├── url_validator.py       # URL validation rules
│   │   ├── queue_manager.py       # Queue management & deduplication
│   │   └── __init__.py            # SearchOrchestrator export
│   ├── extractors/       # LLM-based data extraction (CLAUDE_EXTRACT.md focus)
│   ├── database/         # Supabase client & schemas (CLAUDE_MANAGE.md focus)
│   │   └── validators.py # Data quality validation
│   ├── agents/           # Multi-agent system (future)
│   ├── analytics/        # Analysis programs based on database (CLAUDE_QUERY.md focus)
│   ├── config/           # Configuration files
│   │   ├── sss_codes.py  # SSS code mapping
│   │   └── search_filters.py # Adult rec org/keyword/pattern filters
│   └── utils/            # Helper functions
├── scripts/
│   ├── mcp_agent_scraper.py      # Level 0: MCP agent (manual)
│   ├── extract_leagues_yaml.py   # Level 1: Automated YAML pipeline
│   ├── extract_pipeline.py       # Legacy Selenium pipeline (retired)
│   └── yaml_snapshot_cli.py
├── scrapes/              # Results from web scraping
├── tests/                # Unit tests
├── archive/              # Ignore
├── .env                  # Environment variables (NOT in git)
├── .gitignore            # gitignore
├── requirements.txt      # Python dependencies
├── PARKING_Lot.md        # Plans for future work (not important)
└── CLAUDE.md            # This file - project router
```

---

## Key Architectural Decisions

### 1. Two-Tool Extraction Architecture for Claude_Extract
- **Tool 1:** Core Metadata Extractor (primary pipeline)
- **Tool 2:** Team Count Enrichment (optional script user can run post-ingestion if team count is undefined or low confidence)

### 2. Bifurcated Database Strategy
- **Structured Data:** SQL tables (leagues_metadata)
- **Unstructured Data:** Vector store (league_vectors) for RAG
- Linked via UUIDs outlined in "## UUID Model" below, particularly league_id

### 3. Sport & Season Coding (SSS)
- 3-digit format: XYY (X=season, YY=sport)
- Enables efficient filtering and analysis
- Full reference: [docs/SSS_CODES.md](docs/SSS_CODES.md)

### 4. Multi-Agent Query System (Future)
- Supervisor routes to specialized agents
- Financial Agent, Scheduling Agent, Rules & Vibe Agent
- Built on LangChain/LangGraph when data quality is solid

### 5. Scraping Strategy
- Selenium/Playwright primary (free, local)
- Firecrawl API fallback only (minimizes API costs)
- Aggressive caching to avoid re-scraping

---

# Database Schema

## leagues_metadata (Structured Data - SQL)

### Identifiers
* `league_id` (UUID, PK)
* `organization_id` (UUID, FK to organizations - NEW)
* `url_id` (UUID, FK to urls - NEW)
* `organization_name` (text)
* `url_scraped` (text)

### Sport/Season Classification
* `sport_season_code` (char(3), SSS format)
* `season_year` (int, derived from dates)
* `season_start_date` (date)
* `season_end_date` (date)

### Scheduling
* `day_of_week` (enum: Monday-Sunday)
* `start_time` (time)
* `num_weeks` (int)
* `time_played_per_week` (interval)
* `stat_holidays` (jsonb - holiday schedule exceptions)

### Venue
* `venue_name` (text)

### Competition
* `competition_level` (text, e.g., Rec/Int/Comp)
* `gender_eligibility` (enum: Mens, Womens, CoEd, Other, Unsure)

### Pricing
* `team_fee` (decimal)
* `individual_fee` (decimal)
* `registration_deadline` (date)

### Capacity
* `num_teams` (int)
* `slots_left` (int)

### Policies
* `has_referee` (boolean)
* `requires_insurance` (boolean)
* `insurance_policy_link` (text)

### Quality Tracking
* `quality_score` (int, 0-100, calculated)
* `created_at`, `updated_at` (timestamps)
* `is_archived` (boolean)

### SSS Code Reference
See `docs/SSS_CODES.md`
* Format: XYY (X=season, YY=sport)
* Example: 201 = Summer Soccer (2=Summer, 01=Soccer)

## venues (Structured Data - SQL)

**Purpose:** Physical venue information only

### Fields
* `venue_id` (UUID, PK)
* `venue_name` (text)
* `address` (text)
* `geocode` (geography)
* `created_at`, `updated_at` (timestamps)

## organization_venue_relationships (Structured Data - SQL)

**Purpose:** Organization-specific operational details for venues

### Fields
* `id` (UUID, PK)
* `organization_id` (UUID, FK to organizations)
* `venue_id` (UUID, FK to venues)
* `contact_info` (jsonb) - org-specific contact
* `cost_structure` (jsonb) - what this org pays/charges
* `availability` (jsonb) - when this org has access
* `date_limitations` (jsonb) - this org's booking constraints
* `created_at`, `updated_at` (timestamps)
* Unique constraint on (organization_id, venue_id)

## organizations (Structured Data - SQL)

### Fields
* `organization_id` (UUID, PK)
* `organization_name` (text, canonical)
* `alternate_names` (text[])
* `website_urls` (text[])
* `contact_info` (jsonb)
* `founded_date` (date)
* `created_at`, `updated_at` (timestamps)

## league_vectors (Unstructured Data - pgvector)

**Purpose:** RAG queries for qualitative questions

### Fields
* `id` (UUID, PK)
* `league_id` (UUID, FK to leagues_metadata)
* `content` (text, chunked document)
* `embedding` (vector(1536), OpenAI embedding)
* `metadata` (jsonb)
* `created_at` (timestamp)

### What gets vectorized
* Rulebooks
* Safety waivers
* Skill level descriptions
* Policy documents
* Qualitative website text

---

## UUID Model

**A unique league is defined by:**
1. organization_name
2. sport_season_code
3. season_year (derived from max year of season_start_date and season_end_date)
4. venue_name (with assigned venue_ID)
5. day_of_week
6. competition_level
7. gender_eligibility
8. num_weeks

If any of these differ, it represents a distinct league instance and a unique league_id should be assigned. 

**ID Architecture (Normalized):**

- **league_id** (UUID, primary key)
  - Represents a unique league instance
  - One league_id = one specific league offering
  - Example: "TSSC Monday Night Soccer - Fall 2024 - Rec Division"
  
- **organization_id** (UUID, NEW - needs to be added to schema)
  - Links multiple leagues to same organization
  - Enables: org-level analytics, deduplication, contact info storage
  - Population: AI-assisted matching on org_name + url_scraped domain
  - Example: All leagues operated by "Toronto Sports & Social Club" share same organization_id
  
- **url_id** (UUID, NEW - needs to be added to schema)
  - Normalized URL identifier (one url_id can have many league_id records)
  - Enables: scraping efficiency, data organization
  - Population: Generated from normalized url_scraped (lowercase, strip params)
  - Example: maxvolley.com has one url_id, multiple leagues from that page
  
- **venue_id** (DEFERRED - not implemented yet)
  - Future: FK to normalized venues table
  - Current: Use venue_name text field
  - Migration: AI-assisted venue matching when ready
  
- **league_season_id** (DEFERRED - not implemented yet)
  - Future: Separate recurring league identity from specific season instance
  - Current: Conflate league + season for POC simplicity
  - Will enable: Year-over-year analysis, pricing trends

**League Uniqueness Definition**
If two records have identical (organization_id, sport_season_code, season_year, venue_name, day_of_week, competition_level, gender_eligibility, num_weeks):
→ They are duplicates
→ For structured data, keep record with highest quality_score, or if tied then most recent scraped data. Move old data to an archive folder.
→ For unstructured data, keep most recent record and Delete old unstructured data (league_vectors) and replace with new
→ Delete duplicate

---

## Environment Variables

Located in `.env` (root directory, NOT in git):
```bash
# URL Discovery & Search (CLAUDE_SEARCH.md)
SERPER_API_KEY=<your-serper-api-key>

# Database
SUPABASE_URL=<your-supabase-url>
SUPABASE_KEY=<service-role-key>

# LLM & Extraction (CLAUDE_EXTRACT.md)
OPENAI_API_KEY=<your-openai-key>
FIRECRAWL_API_KEY=<your-firecrawl-key>
```

See `.env.example` for template.

---

## Development Workflow

1. **Choose your context:** Pick the appropriate `CLAUDE_*.md` file from table above
2. **Understand architecture:** Read [EXTRACTION_ARCHITECTURE.md](docs/EXTRACTION_ARCHITECTURE.md)
3. **Check current phase:** Review [PHASE_4_QUICK_START.md](docs/PHASE_4_QUICK_START.md)
4. **Test locally:** Use `scripts/test_full_pipeline.py`
5. **Validate data:** Use `scripts/test_full_pipeline.py --validate`
6. **Update docs:** Keep context files in sync when architecture changes

## Critical Resources

### Documentation
- [SSS Codes](docs/SSS_CODES.md) - Sport/season reference
- [Extraction Architecture](docs/EXTRACTION_ARCHITECTURE.md) - Two-tool design

### External Resources
- Supabase Dashboard: https://vcshpjnlwkahkdkhjptp.supabase.co

---

## What NOT to Touch

- `.env` - Never commit to git

---

## Coding Standards

- **Style:** PEP 8, type hints, Google-style docstrings
- **Paths:** Use `pathlib`, not `os.path`
- **Errors:** Explicit exception handling with logging
- **Database:** Parameterized queries only, use Supabase client
- **Naming:** 
  - Files: `snake_case.py`
  - Classes: `PascalCase`
  - Functions/Variables: `snake_case`
  - Constants: `UPPER_SNAKE_CASE`

---