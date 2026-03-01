# CLAUDE_SEARCH - URL Discovery & Queue Management

**Purpose:** Find adult rec sports websites via Serper API search, validate URLs, populate scrape queue
**Input:** City + sport from Streamlit UI → **Output:** `scrape_queue` table
**Handoff:** Queue consumed by [CLAUDE_EXTRACT.md](CLAUDE_EXTRACT.md)
**Architecture:** SearchOrchestrator coordinates query generation → search execution → validation → queuing

---

## Scope

**IN SCOPE:**
- Serper API search execution (Google search results via API)
- URL validation (pass/fail with detailed categorization)
- Scrape queue management with multi-level deduplication
- Streamlit campaign manager interface
- Configuration-driven filtering (known orgs, keywords, patterns)

**OUT OF SCOPE:**
- Web scraping (→ CLAUDE_EXTRACT)
- Data normalization (→ CLAUDE_MANAGE)
- League analytics (→ CLAUDE_QUERY)

---

## Database Tables (Already Created)

### 1. `search_queries`
Tracks searches executed. Key fields:
- `query_id`, `query_text`, `city`, `sport`, `season`, `year`
- `query_fingerprint` (auto-generated for dedup)
- `status` (enum: PENDING/IN_PROGRESS/COMPLETED/FAILED)
- `total_results`, `valid_results`

### 2. `search_results`
All URLs from Google (passed + failed). Key fields:
- `result_id`, `query_id`
- `url_raw`, `url_canonical` (auto-normalized)
- `validation_status` (enum: PENDING/PASSED/FAILED)
- `validation_reason`, `priority` (1-3)

### 3. `scrape_queue`
Only validated URLs ready to scrape. Key fields:
- `scrape_id`, `url` (canonical)
- `priority` (1=high, 3=low)
- `status` (enum: PENDING/IN_PROGRESS/COMPLETED/FAILED/SKIPPED)

**Auto-magic:** 
- `url_canonical` auto-populated from `url_raw` (removes UTM, www, normalizes case)
- `query_fingerprint` auto-populated (lowercase city|state|country|sport|season|year)

**Dedup:** Check `query_fingerprint` before inserting to avoid re-searching same thing

---

## Search Query Pattern

```python
def build_query(city: str, sport: str, season: str = None) -> str:
    """Build a Google search query string."""
    if season:
        return f"{city} {season} adult rec {sport} league"
    return f"{city} adult rec {sport} league"
```

**Examples:**
- "Toronto adult rec soccer league"
- "Chicago summer adult rec basketball league"

**Pattern:** Always includes "adult rec" to target recreational leagues, not professional or youth

---

## URL Validation Rules

**Source:** [src/search/url_validator.py](../../src/search/url_validator.py)

### ✅ PASS Criteria:
- Valid domain extensions: `.com`, `.org`, `.net`, `.ca`, `.io`, `.app`
- AND contains valid keywords: "league", "register", "schedule", "sign up", "team", "roster", "season"

### ❌ FAIL Criteria (any of):
- Invalid file extensions: `.pdf`, `.doc`, `.docx`, `.jpg`, `.png`, `.xlsx`, `.csv`
- Invalid/exclusion domains: Facebook, Instagram, Twitter, TikTok, Reddit, Yelp, YouTube, Wikipedia, LinkedIn, Pinterest
- Professional sports patterns: MLS, NBA, NFL, NHL, MLB, CanPL, Toronto FC, Raptors, Maple Leafs, Blue Jays, etc.
- Youth organization patterns: "youth", "minor", "junior", "kids", "u18", "u16", "u14", "district association", "academy", "rep team", "house league"
- Invalid keywords: "news article", "blog post", "review", "facility rental", "equipment shop", "sports bar", "gym"
- Age range patterns: "u18", "u16", "u14", "u12", etc.

### ✅ Enhanced PASS Classification (Validation Reasons):
- `valid_adult_rec_league` - Passed with explicit adult rec indicators (2+ keywords: adult, rec, recreational, coed, social, beer league)
- `valid_league_page` - Passed with league-related keywords
- `invalid_file_type` - PDF, DOC, image files
- `social_media` - Facebook, Instagram, Twitter, etc.
- `review_site` - Yelp, Google Maps
- `professional_sports` - MLS, NBA, professional teams
- `youth_organization` - Youth leagues, district associations
- `not_league_content` - News, blogs, equipment shops, facilities

---

## Priority Assignment (Weighted Scoring System)

**Source:** [src/search/result_processor.py](../../src/search/result_processor.py)

Priority is calculated using a weighted scoring system that sums points from multiple factors:

### Scoring Components:
- **Known organization:** +40 points (recognized adult rec orgs like TSSC, Volo, ZogSports)
- **Adult rec keywords:** +10 points each, max 30 (adult, rec, recreational, coed, social, beer league, mens, womens, mixed)
- **Search rank bonus:** 20 (rank 1-3), 15 (rank 4-6), 10 (rank 7-10), 5 (rank 11+)
- **League keywords:** +10 points (league, register, registration, schedule)
- **Domain quality:** +10 points (.org, .ca domains)
- **Explicit adult rec validation:** +20 points (2+ adult rec keyword matches in content)

### Priority Thresholds:
- **Priority 1 (High):** 40+ points
- **Priority 2 (Medium):** 20-39 points
- **Priority 3 (Low):** <20 points

### Known Adult Rec Organizations:
Full list in [src/config/search_filters.py](../../src/config/search_filters.py)
- US: TSSC, Volo, ZogSports, JAM Sports, Underdog, Club WAKA, NAKID, Play CSA
- Canadian: OSSC, KSSC, MTLSPORTSOCIAL, VSSC, CSSC, ESSC, CapitalVolley, Ottawa Rec Sports, etc.

---

## Workflow: User Input → Queue

```
┌─────────────────────────────────────────────────────────────────┐
│                   SearchOrchestrator (Main Controller)          │
└─────────────────────────────────────────────────────────────────┘
                              │
     ┌────────────────────────┼────────────────────────┐
     │                        │                        │
     ▼                        ▼                        ▼
  STEP 1              STEP 2                      STEP 3
Query Gen          Search Exec                Result Processing
     │                  │                          │
     │                  │                          │
  build_query       Serper API                  validate_url
  fingerprint       (HTTP POST)                 extract_org
  check_dups        retry_logic                 calc_priority
     │                  │                          │
     └────────────────────┼──────────────────────┘
                          │
                    search_results table
                    (all URLs stored)
                          │
                    STEP 4: Queue Manager
                          │
                    Check duplicates:
                    ├─ Already in queue?
                    ├─ Already scraped?
                    └─ If new → add to scrape_queue
                          │
                    scrape_queue table
                    (PENDING URLs)
                          │
                    Consumed by CLAUDE_EXTRACT.md
```

**SearchOrchestrator Orchestration:**
1. User enters city + sport in Streamlit UI
2. Generate all city × sport × season queries
3. Filter duplicates (last 30 days, by fingerprint)
4. For each new query:
   - Insert into search_queries (status=IN_PROGRESS)
   - Execute Serper API search
   - Validate each URL (url_validator.py)
   - Extract organization name
   - Calculate weighted priority
   - Store in search_results
   - Add valid URLs to scrape_queue (with dedup checks)
   - Update search_queries (status=COMPLETED)
5. Return campaign summary with metrics

---

## Code Structure

```
src/search/
  ├── __init__.py               # Exports SearchOrchestrator
  ├── serper_client.py          # Serper API wrapper (Google search results via API)
  ├── query_generator.py        # Build queries, fingerprinting, duplicate detection
  ├── result_processor.py       # Validate & process results, weighted priority scoring
  ├── url_validator.py          # URL validation rules & organization extraction
  └── queue_manager.py          # Queue management with multi-level deduplication

src/config/
  └── search_filters.py         # Configuration: known orgs, keywords, patterns

streamlit_app/pages/
  ├── campaign_manager.py       # Main search UI (city + sport input)
  └── queue_monitor.py          # Queue status, bulk actions, and URL screening
```

**Key Class:**
- **SearchOrchestrator** (`src/search/__init__.py`) - Orchestrates the entire workflow (query generation → search → validation → queuing)

---

## Key Implementation Details

See actual implementations in source files - all modules follow clean separation of concerns:

- **[src/search/__init__.py](../../src/search/__init__.py)**: SearchOrchestrator class orchestrating query → search → validate → queue
- **[src/search/query_generator.py](../../src/search/query_generator.py)**: Builds queries with "adult rec" pattern, generates fingerprints, detects duplicates
- **[src/search/serper_client.py](../../src/search/serper_client.py)**: Serper API wrapper with exponential backoff retry (1s, 1.5s, 2.25s)
- **[src/search/result_processor.py](../../src/search/result_processor.py)**: Validates results and calculates weighted priority scores
- **[src/search/url_validator.py](../../src/search/url_validator.py)**: URL validation rules, org extraction, URL canonicalization
- **[src/search/queue_manager.py](../../src/search/queue_manager.py)**: Multi-level deduplication (queue, already scraped, mark as queued)

---

## Streamlit Campaign Manager Interface

**File:** [streamlit_app/pages/campaign_manager.py](../../streamlit_app/pages/campaign_manager.py)

**Simplified Interface:**
The UI focuses on single city + sport search (not bulk campaigns):

```python
def render():
    """Render the Campaign Manager page - simplified for single city/sport search."""
    st.title("🎯 Adult Rec League Search")

    # Simple input: City and Sport
    col1, col2 = st.columns(2)
    with col1:
        city = st.text_input("City", value="Toronto", placeholder="e.g., Toronto")
    with col2:
        sport = st.text_input("Sport", value="Volleyball", placeholder="e.g., Soccer, Volleyball")

    # Execute button
    if st.button("🔍 Search", type="primary", use_container_width=True):
        if city and sport:
            with st.spinner("Searching for adult rec leagues..."):
                db = get_client()
                orchestrator = SearchOrchestrator(supabase_client=db)

                # Execute search campaign
                campaign_results = orchestrator.execute_search_campaign(
                    cities=[city],
                    sports=[sport],
                    check_duplicates=False
                )

            # Display results
            st.divider()
            st.subheader("📊 Results")

            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total Results", campaign_results['total_results'])
            with col2: st.metric("Valid URLs", campaign_results['valid_results'])
            with col3: st.metric("Invalid URLs", campaign_results['total_results'] - campaign_results['valid_results'])
            with col4: st.metric("Pass Rate", f"{campaign_results['pass_rate']:.1f}%")

            st.success(f"✅ {campaign_results['added_to_queue']} URLs added to scrape queue")

            # Show the URLs in expandable list
            if campaign_results['total_results'] > 0:
                st.subheader("Found URLs")
                search_results = db.table('search_results').select(
                    'url_raw, page_title, validation_status, priority'
                ).eq('city', city).eq('sport', sport).execute()

                for i, result in enumerate(search_results.data, 1):
                    status = "✓ VALID" if result['validation_status'] == 'PASSED' else "✗ INVALID"
                    priority_str = f"P{result['priority']}" if result['priority'] else ""

                    with st.expander(f"{i}. {result['page_title'][:60]} {priority_str} [{status}]"):
                        st.write(f"**URL:** {result['url_raw']}")
                        st.write(f"**Title:** {result['page_title']}")
                        st.write(f"**Status:** {result['validation_status']}")
                        if result['priority']:
                            st.write(f"**Priority:** {result['priority']}")
        else:
            st.warning("Please enter both city and sport")
```

**Key Features:**
- Simple city + sport input (not bulk campaigns)
- Real-time progress feedback
- Summary metrics display
- Expandable URL results with validation status
- Direct integration with SearchOrchestrator

---

## Environment Variables

Required in `.env` (root directory, NOT in git):

```bash
# Serper API (Google search results via API)
SERPER_API_KEY=<your-serper-api-key>

# Supabase (PostgreSQL backend)
SUPABASE_URL=<your-supabase-url>
SUPABASE_KEY=<your-service-role-key>
```

**Setup:**
1. Get Serper API key from https://serper.dev/
2. Get Supabase credentials from https://supabase.com/
3. Copy `.env.example` to `.env` and fill in values
4. Never commit `.env` to git

---

## Testing Checklist

**Unit Tests:** See [tests/](../../tests/) directory

- [ ] **Query Generation**
  - [ ] `build_query()` produces correct format with "adult rec"
  - [ ] `generate_query_fingerprint()` is consistent (lowercase, pipes, no state)
  - [ ] `check_duplicate_query()` detects recent searches

- [ ] **Serper Search**
  - [ ] `SerperClient.search()` returns normalized results (url_raw, page_title, page_snippet, search_rank)
  - [ ] Retry logic works (exponential backoff: 1s, 1.5s, 2.25s)
  - [ ] SerperAPIError raised after max retries

- [ ] **URL Validation**
  - [ ] `validate_url()` rejects PDFs, images
  - [ ] `validate_url()` rejects social media (Facebook, Instagram, etc.)
  - [ ] `validate_url()` rejects professional sports (MLS, NBA, Toronto FC)
  - [ ] `validate_url()` rejects youth orgs ("youth", "u18", "district")
  - [ ] `validate_url()` accepts league pages with keywords
  - [ ] `validate_url()` returns correct reason codes

- [ ] **Organization Extraction**
  - [ ] `extract_organization_name()` extracts from domain (tssc.ca → "TSSC")
  - [ ] Falls back to title if domain not useful

- [ ] **URL Canonicalization**
  - [ ] `canonicalize_url()` removes UTM params
  - [ ] Removes trailing slashes
  - [ ] Converts http → https
  - [ ] Removes www prefix
  - [ ] Normalizes case

- [ ] **Priority Scoring**
  - [ ] Known org (+40) pushes score to Priority 1
  - [ ] Adult rec keywords (+10 each) counted correctly
  - [ ] Search rank (20/15/10/5) applied correctly
  - [ ] Total score correctly maps to Priority 1/2/3

- [ ] **Result Processing**
  - [ ] Results stored in search_results with all fields
  - [ ] Valid results marked PASSED, invalid marked FAILED
  - [ ] Priority calculated only for PASSED results

- [ ] **Queue Management**
  - [ ] Valid URLs added to scrape_queue
  - [ ] Duplicates detected (already in queue)
  - [ ] Already-scraped URLs detected (in leagues_metadata)
  - [ ] search_results marked as `added_to_scrape_queue: True`

- [ ] **Streamlit Integration**
  - [ ] Campaign manager accepts city + sport
  - [ ] SearchOrchestrator coordinates workflow
  - [ ] Results display metrics (total, valid, pass rate)
  - [ ] Results expandable for each URL

---

## Configuration & Filtering

**Source:** [src/config/search_filters.py](../../src/config/search_filters.py)

The search filters are configuration-driven, allowing easy updates without code changes:

### Adult Rec Keywords
Used to boost priority and identify adult recreational leagues:
- adult, rec, recreational, coed, co-ed, social, beer league, mens, womens, mixed

### Youth Organization Indicators (Reject)
- youth, minor, junior, kids, children, u18-u6, district association, academy, rep team, house league

### Professional Sports Patterns (Reject)
- MLS, NBA, NFL, NHL, MLB, WNBA, CanPL, CFL, Toronto FC, professional, tickets, etc.

### Known Adult Rec Organizations (Boost Priority)
See [src/config/search_filters.py](../../src/config/search_filters.py) for full list:
- US: TSSC, Volo, ZogSports, JAM Sports, Underdog, Club WAKA, NAKID
- Canada: OSSC, KSSC, MTLSPORTSOCIAL, VSSC, CSSC, ESSC, CapitalVolley, Ottawa Rec Sports

---

## Analytics Queries (For Dashboards)

**Coverage by city/sport:**
```sql
SELECT city, sport, COUNT(*) as searches, SUM(valid_results) as valid_urls
FROM search_queries
WHERE status = 'COMPLETED'
GROUP BY city, sport
ORDER BY searches DESC;
```

**Validation pass rate by sport:**
```sql
SELECT
    sq.sport,
    COUNT(sr.result_id) as total_results,
    SUM(CASE WHEN sr.validation_status = 'PASSED' THEN 1 ELSE 0 END) as passed,
    ROUND(100.0 * SUM(CASE WHEN sr.validation_status = 'PASSED' THEN 1 ELSE 0 END) / COUNT(sr.result_id), 1) as pass_rate_pct
FROM search_queries sq
JOIN search_results sr ON sq.query_id = sr.query_id
WHERE sq.status = 'COMPLETED'
GROUP BY sq.sport
ORDER BY pass_rate_pct DESC;
```

**Priority distribution in queue:**
```sql
SELECT priority, status, COUNT(*) as count
FROM scrape_queue
GROUP BY priority, status
ORDER BY priority ASC;
```

---

## Reference Documents

- **URL Validator:** [src/search/url_validator.py](../../src/search/url_validator.py)
- **Search Filters Config:** [src/config/search_filters.py](../../src/config/search_filters.py)
- **Serper Client:** [src/search/serper_client.py](../../src/search/serper_client.py)
- **Query Generator:** [src/search/query_generator.py](../../src/search/query_generator.py)
- **Result Processor:** [src/search/result_processor.py](../../src/search/result_processor.py)
- **Queue Manager:** [src/search/queue_manager.py](../../src/search/queue_manager.py)
- **Streamlit UI:** [streamlit_app/pages/campaign_manager.py](../../streamlit_app/pages/campaign_manager.py)
- **Sport/Season Codes:** [docs/SSS_CODES.md](../SSS_CODES.md)
- **Extraction Phase:** [CLAUDE_EXTRACT.md](CLAUDE_EXTRACT.md)
