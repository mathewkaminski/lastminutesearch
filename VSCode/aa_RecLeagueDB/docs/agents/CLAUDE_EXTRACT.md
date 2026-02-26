# CLAUDE_EXTRACT - Scraping & Extraction Context

**Purpose:** Web scraping with YAML accessibility trees, LLM-based data extraction, multi-page navigation
**When to use:** Building/debugging extraction pipeline, improving scrapers, handling complex websites
**Related contexts:** Use [CLAUDE_MANAGE.md](CLAUDE_MANAGE.md) after extraction for validation

---

## Current Phase: Phase 4 - YAML-Based Extraction & Multi-Page Navigation

**What we're building:** Reliable end-to-end pipeline from URL → YAML snapshots → extracted leagues → database storage

**Key files:**
- `scripts/mcp_agent_scraper.py` - MCP agent scraper (Level 0, manual/complex sites)
- `scripts/extract_leagues_yaml.py` - Automated YAML pipeline (Level 1, bulk)
- `src/scraper/mcp_client.py` - MCP server connection utilities
- `src/scraper/mcp_navigator.py` - Claude navigation agent loop
- `src/scraper/playwright_yaml_fetcher.py` - Playwright accessibility tree → YAML
- `src/scraper/yaml_link_parser.py` - Link discovery and scoring from YAML
- `src/extractors/yaml_extractor.py` - GPT-4 extraction from YAML/snapshots
- `src/database/link_store.py` - Navigation link storage with tracking
- `docs/EXTRACTION_ARCHITECTURE.md` - Detailed architecture
- `docs/PHASE_4_QUICK_START.md` - Current phase goals

---

## Extraction Architecture

**Single unified pipeline:** URL → YAML → Links → Leagues → Database

**What it extracts:**
- Organization name, sport/season code
- Dates (season start/end, registration deadline)
- Scheduling (day of week, start time)
- Pricing (team fee, individual fee)
- Competition details (level, gender eligibility)
- Venue information
- Policies (insurance, referee presence)

**Usage:**
```bash
python scripts/extract_leagues_yaml.py https://ottawavolleysixes.com
```

**Multi-page capability:**
- Automatically discovers navigation links from home page
- Fetches high-priority pages (registration, schedule, standings)
- Aggregates all YAML for comprehensive extraction
- Single GPT-4 call extracts all leagues from all pages

**Re-extraction Strategy:**
- If `quality_score < 50`, URL flagged for manual review
- If `num_teams` missing, can trigger enrichment script (future)
- If extraction fails, check YAML snapshot for validity
- Preserve all YAML snapshots for audit trail

---

## Scraping Stack (Fallback Cascade)

**Strategy:** MCP agent for manual/complex sites, YAML pipeline for automated bulk, Firecrawl as last resort.

### Level 0: Playwright MCP Agent (PRIMARY for manual/complex sites)
- **Script:** `scripts/mcp_agent_scraper.py`
- **Use for:** Manual one-off scraping, JS-heavy sites, unusual navigation structures
- **Cost:** Free (local) + Claude API tokens (~$0.01–0.05 per URL)
- **How:** Claude agent controls browser via MCP tools, intelligently follows links
- **Strengths:** Handles dynamic content, accordions, tabs, unusual site structure
- **When to use:** New sites, sites with low quality_score, sites that fail Level 1

### Level 1: Playwright YAML Pipeline (PRIMARY for automated bulk)
- **Script:** `scripts/extract_leagues_yaml.py`
- **Use for:** Automated bulk scraping of known-good sites
- **Cost:** Free (local execution)
- **How:** Hardcoded link discovery (score-based), accessibility tree YAML, GPT-4o extraction
- **Strengths:** Fast, no API cost for navigation, deterministic

### Level 2: Firecrawl API (Fallback Only)
- **Use for:** Sites that defeat local Playwright (anti-bot, complex JavaScript)
- **Cost:** Paid API (minimize usage)

**Caching:** All snapshots cached in `scrapes/{domain}/{timestamp}_{page_type}.yaml` (gitignored) with TTL of 7 days to avoid re-scraping

---

## Multi-Page Navigation with Link Discovery

**Automatic approach:** Discover and follow navigation links from YAML accessibility tree

**How it works:**

1. **Fetch home page YAML** - Generate accessibility tree from home page
2. **Extract navigation links** - Parse YAML to find all `<a>` elements with URLs
3. **Score links** - Assign priority based on anchor text and page type:
   - **HIGH_PRIORITY (100 points):** registration, register, schedule, standings, scores
   - **MEDIUM_PRIORITY (50 points):** rules, teams, pricing, venue, about, divisions
   - **LOW_PRIORITY (0 points):** social media, contact, privacy, legal
4. **Fetch high-priority pages** - Generate YAML for each link scoring ≥100
5. **Aggregate YAML** - Combine all page YAML into single extraction context

**Link Discovery Implementation:**
```python
from src.scraper.yaml_link_parser import parse_yaml_links, score_links

# Parse YAML to extract links
yaml_tree = yaml.safe_load(yaml_content)
links = parse_yaml_links(yaml_tree)

# Score and filter
scored_links = score_links(links, source_url)
high_priority = [link for link in scored_links if link.score >= 100]
```

**Usage example:**
```bash
python scripts/extract_leagues_yaml.py https://ottawavolleysixes.com --max-pages 5
```

**Multi-page result:**
- Fetches home + up to 4 high-priority linked pages
- Returns dict: `{"home": yaml_content, "schedule": yaml_content, ...}`
- All YAML combined for GPT-4 extraction

**Current capabilities:**
- ✅ Automatic link discovery from YAML
- ✅ Priority-based page selection
- ✅ Multi-page YAML aggregation
- ✅ Caching to avoid re-fetches
- ✅ Link storage with source tracking

**Storage:** Discovered links stored in `discovered_links` table with:
- Source URL and target URL
- Anchor text and priority score
- Page type (registration, schedule, etc.)
- Source tracking (result_id, url_raw)

---

## LLM Extraction from YAML

**Model:** GPT-4 (via OpenAI API)
**Input:** YAML accessibility trees (one or more pages aggregated)
**Output:** Structured JSON array of leagues matching database schema

**YAML Input Format:**
The accessibility tree YAML has this structure:
```yaml
- role: document
  name: "Organization Name"
  children:
    - role: heading
      name: "Spring Soccer"
      level: 1
    - role: table
      name: ""
      children:
        - role: row
          children:
            - role: gridcell
              name: "Monday"
            - role: gridcell
              name: "7pm"
            - role: gridcell
              name: "$80"
            - role: link
              name: "Register Now"
              url: "/register"
```

**Extraction prompt strategy:**
1. Provide YAML structure guide explaining role/name/children hierarchy
2. Provide complete database schema for output
3. Request JSON array with exact field names
4. Include real YAML examples from actual websites
5. Handle ambiguous/missing data with NULL
6. Return completeness percentage for each league

**Field mapping:**
```python
{
    "organization_name": str,
    "sport_season_code": str,  # SSS format (see SSS_CODES.md)
    "season_start_date": "YYYY-MM-DD",
    "season_end_date": "YYYY-MM-DD",
    "day_of_week": enum,  # Monday-Sunday
    "start_time": "HH:MM:SS",
    "team_fee": decimal,
    "individual_fee": decimal,
    "venue_name": str,  # Freeform text (not FK yet)
    "competition_level": str,
    "gender_eligibility": enum,  # Mens, Womens, CoEd, Other, Unsure
    # ... see full schema in database/validators.py
}
```

**SSS Code Assignment:**
- First digit: Seasonality (1=Spring, 2=Summer, 3=Fall, 4=Winter, etc.)
- Last two digits: Sport (01=Soccer, 02=Basketball, etc.)
- See `docs/SSS_CODES.md` for complete reference

**YAML Extraction Advantages:**
- **No HTML cleaning needed** - YAML already semantic
- **No truncation** - full page fits in token limit (~600 tokens vs 12,000 for raw HTML)
- **Clear structure** - role/name/children hierarchy is self-documenting
- **Better accuracy** - less confusing info for GPT-4

---

## Data Storage Pipeline

Complete flow from scraping → extraction → storage:

```
URL → YAML Snapshots → Link Discovery → League Extraction → Database
 ↓       ↓               ↓                ↓                   ↓
 1      2               3                4                   5
```

### Step 1: YAML Snapshots → page_snapshots table

**When:** During fetch_yaml_multi_page()
**What's stored:**
```python
{
    "id": UUID,                    # Primary key
    "url": "https://...",          # Source URL
    "content": "role: document...",  # Full YAML accessibility tree
    "snapshot_type": "playwright_yaml",
    "content_format": "yaml",
    "size_bytes": 52000,           # YAML file size
    "token_estimate": 7947,        # Approximate GPT-4 tokens
    "metadata": {
        "page_type": "home",       # home, schedule, registration, etc.
        "method": "multi_page_yaml"
    },
    "created_at": "2026-02-19T..."
}
```

**Why:** Preserves complete page content for audit trail, re-extraction, and debugging

---

### Step 2: Navigation Links → discovered_links table

**When:** During fetch_yaml_multi_page() link discovery phase
**What's stored:**
```python
{
    "id": UUID,
    "source_url": "https://ottawavolleysixes.com",
    "discovered_url": "/schedule",
    "anchor_text": "View Schedule",
    "score": 100,                  # HIGH_PRIORITY = 100, MEDIUM = 50
    "page_type": "schedule",       # Inferred from anchor text
    "snapshot_id": UUID,           # FK to page_snapshots (for home page)
    "result_id": UUID,             # FK to search_results (tracks origin)
    "url_raw": "https://...",      # Original URL from search_results.url_raw
    "status": "pending",           # pending, fetched, extracted, failed
    "created_at": "2026-02-19T..."
}
```

**Purpose:**
- Tracks all navigation paths discovered
- Enables link follow-up (fetch higher-priority pages)
- Provides source tracking for search results integration
- Can be used for future navigation intelligence

**Link Scoring Rules:**
- **HIGH_PRIORITY (100):** registration, register, signup, schedule, standings, scores, bracket
- **MEDIUM_PRIORITY (50):** rules, teams, pricing, fees, venue, divisions, levels, location
- **LOW_PRIORITY (0):** social, contact, about, privacy, legal, help (not followed)

---

### Step 3: Extracted Leagues → leagues_metadata table

**When:** After GPT-4 extraction from aggregated YAML
**What's stored:**
```python
{
    "league_id": UUID,             # Primary key
    "organization_name": "Ottawa Volley Sixes",
    "sport_season_code": "211",    # 2=Winter, 11=Volleyball
    "url_scraped": "https://ottawavolleysixes.com",
    "season_start_date": "2026-01-04",
    "season_end_date": "2026-03-29",
    "day_of_week": "Sunday",
    "start_time": "19:00:00",
    "team_fee": 875.00,
    "individual_fee": None,
    "num_teams": 12,
    "venue_name": "Riverside High School",
    "competition_level": "Recreational",
    "gender_eligibility": "CoEd",
    "num_weeks": 12,
    "time_played_per_week": "1:30:00",
    "has_referee": True,
    "requires_insurance": False,
    "quality_score": 88,           # 0-100, based on completeness
    "created_at": "2026-02-19T...",
    "updated_at": "2026-02-19T..."
}
```

**Required fields:**
- `league_id` (UUID, auto-generated)
- `organization_name`
- `sport_season_code`
- `url_scraped`

**Important fields** (should be present for quality score):
- `day_of_week`
- `start_time`
- `venue_name`
- `team_fee` OR `individual_fee`
- `season_start_date`
- `season_end_date`
- `competition_level`
- `gender_eligibility`

**Optional fields:**
- `num_teams`
- `slots_left`
- `registration_deadline`
- `time_played_per_week`
- `has_referee`
- `requires_insurance`
- `insurance_policy_link`

**Deduplication:** Before insertion, check for duplicate using 8-field uniqueness model:
- organization_name, sport_season_code, season_year, venue_name, day_of_week, competition_level, gender_eligibility, num_weeks
- If duplicate found: keep highest quality_score, delete old record

---

### Step 4 (Future): Unstructured Data → league_vectors table

**What gets vectorized:**
- Rulebooks
- Safety waivers
- Skill level descriptions
- Qualitative reviews
- Policy documents

**Process:**
1. Chunk text (max 1000 tokens per chunk)
2. Generate OpenAI embeddings (1536 dimensions)
3. Store in `league_vectors` with `league_id` FK
4. Add metadata (source, chunk_index, etc.)

**Usage:** RAG queries for "vibe" questions (Rules & Vibe Agent)

---

## Venue Handling (Current Approach)

**Status:** Freeform text field, NOT normalized FK

**Why:** Proof-of-concept phase, manual venue normalization comes later

**Extraction strategy:**
- Extract exact venue name from website
- Include city if mentioned (e.g., "Maple Leaf Gardens, Toronto")
- Leave as-is, don't try to geocode or normalize yet

**Future:** `venues` table will store normalized venue data, FK in `leagues_metadata.venue_id`

---

## Testing & Validation

**Primary YAML extraction script:**
```bash
# Test single URL - full pipeline with dry-run (no database writes)
python scripts/extract_leagues_yaml.py https://ottawavolleysixes.com --dry-run

# Extract and store to database
python scripts/extract_leagues_yaml.py https://ottawavolleysixes.com

# Extract with custom page limit
python scripts/extract_leagues_yaml.py https://ottawavolleysixes.com --max-pages 3

# Force refresh (bypass cache)
python scripts/extract_leagues_yaml.py https://ottawavolleysixes.com --no-cache

# Get results as JSON
python scripts/extract_leagues_yaml.py https://ottawavolleysixes.com --json
```

**What gets reported:**
- Pages fetched (home + linked pages)
- Total YAML size and token estimates
- Navigation links discovered and stored
- Leagues extracted per page
- Leagues successfully inserted to database
- YAML snapshots stored with IDs
- Any extraction errors encountered

**Example successful output:**
```
EXTRACTION RESULTS
URL: https://www.ottawavolleysixes.com
Status: SUCCESS

Pages Fetched: 2
Total Leagues Extracted: 18
Leagues Stored to DB: 18
Discovered Links: 37
Snapshots Stored: 2

Leagues by page:
  home               :   9 leagues
  schedule           :   9 leagues

Snapshots Stored: 2
  [snapshot_id_1]
  [snapshot_id_2]
```

**Data quality checks:**
- ✅ All required fields present (organization_name, sport_season_code, url_scraped)
- ✅ Quality score calculated (0-100 based on field completeness)
- ✅ At least 5/8 important fields populated
- ✅ Valid SSS codes assigned
- ✅ No extraction errors logged

**See [CLAUDE_MANAGE.md](CLAUDE_MANAGE.md) for post-extraction validation and cleaning**

---

## Common Extraction Challenges & YAML Solutions

### Challenge 1: Fees hidden behind login
**Problem:** YAML may not show content behind login walls
**Solution:** Look for pricing pages, FAQs, or past season info in YAML structure

### Challenge 2: Dates in non-standard format
**Problem:** "Spring 2024" or "Jan 4 - Mar 29" needs parsing
**Solution:** GPT-4 is good at parsing contextual dates from YAML text nodes

### Challenge 3: Multiple leagues on one page
**Problem:** Need to extract each as separate record
**Solution:** YAML tables with role="row" make it clear - GPT-4 extracts each row as league

### Challenge 4: Sport/season ambiguous
**Problem:** YAML may not clearly indicate sport type
**Solution:** Use page title from YAML, URL patterns, context clues to infer SSS code

### Challenge 5: Team count not on main page
**Problem:** `num_teams` often only on standings/schedule
**Solution:** Multi-page YAML fetching automatically includes schedule page

### Challenge 6: JavaScript renders critical content
**Problem:** Static YAML extraction misses JS-rendered content
**Solution:** Playwright waits for `networkidle` before extraction - catches most JS content

### Challenge 7: YAML still missing critical fields
**Problem:** Some websites are just poorly structured
**Solution:** Flag for manual review if quality_score < 50, preserve YAML snapshot for investigation

---

## Error Handling

**Scraping errors:**
- Retry 3x with exponential backoff
- Escalate to next scraping level (Playwright → Firecrawl)
- Log failure reason and HTML snapshot

**Extraction errors:**
- Log raw HTML that caused failure
- Return partial data with NULLs for missing fields
- Flag for manual review if quality_score < 30

**Database errors:**
- Use parameterized queries (no SQL injection)
- Handle unique constraint violations (duplicate league_id)
- Rollback transaction on failure

---

## Environment Variables

Located in `.env` (root directory):
```
OPENAI_API_KEY=<your-key>
FIRECRAWL_API_KEY=<your-key>  # Only for fallback
SUPABASE_URL=<your-url>
SUPABASE_KEY=<service-role-key>
```

---

## Success Criteria

**YAML Extraction Pipeline Success:**
- ✅ YAML snapshots generated for home + high-priority pages
- ✅ Navigation links extracted and scored correctly
- ✅ Discovered links stored in `discovered_links` table with source tracking
- ✅ Leagues extracted from aggregated YAML using GPT-4
- ✅ All extracted leagues inserted into `leagues_metadata` table
- ✅ YAML snapshots stored in `page_snapshots` table
- ✅ Quality score ≥ 50
- ✅ At least 5/8 important fields populated
- ✅ SSS code correctly assigned
- ✅ No extraction errors logged

**Actual Performance (Ottawa Volley Sixes test):**
| Metric | Value |
|--------|-------|
| Pages fetched | 2 (home + schedule) |
| Navigation links found | 37 |
| Leagues extracted | 18 |
| Leagues stored to DB | 18 |
| Average quality score | 88% |
| YAML size | 104 KB (~15,894 tokens) |
| Token reduction vs HTML | ~34% |

**Extraction needs improvement when:**
- ⚠️ Quality score < 50
- ⚠️ Important fields missing (fees, dates, venue)
- ⚠️ YAML accessibility tree generation failed
- ⚠️ Multi-page navigation found 0 high-priority links

---

## YAML Extraction Quick Reference

**JavaScript accessibility tree extraction (used by Playwright):**
```javascript
// Playwright automatically generates this when you call page.evaluate()
// It extracts semantic structure: role, name, children hierarchy
// No HTML cleaning needed - already structured as YAML

const tree = {
  role: "document",
  name: "page_title",
  children: [
    {
      role: "heading",
      name: "League Name",
      level: 1
    },
    {
      role: "link",
      name: "Register Now",
      url: "/register"
    }
  ]
}
```

**YAML output format (after yaml.dump()):**
```yaml
- role: document
  name: page_title
  children:
    - role: heading
      name: League Name
      level: 1
    - role: link
      name: Register Now
      url: /register
```

---

## Next Steps (Phase Roadmap)

**Phase 5 (Current):** Playwright MCP Agent
- `scripts/mcp_agent_scraper.py` built and working for manual one-off scraping
- Use for complex sites and new URL validation
- Scale to automated queue processing when comfortable

**Phase 5.2 (Next):** Firecrawl Fallback Integration
- Add Firecrawl for sites that defeat both MCP and YAML approaches
- Automatic escalation when Playwright fails

**Phase 6 (Future):** Historical Season Tracking
- Separate `leagues` from `league_seasons`
- Track year-over-year pricing changes
- Multi-season extraction

**Phase 7 (Future):** Team Count Enrichment
- Secondary extraction for `num_teams` field
- Use standings/schedule pages
- Only trigger when `num_teams` is NULL or low confidence

---

**When extraction is done, switch to [CLAUDE_MANAGE.md](CLAUDE_MANAGE.md) for validation, deduplication, and cleaning.**
