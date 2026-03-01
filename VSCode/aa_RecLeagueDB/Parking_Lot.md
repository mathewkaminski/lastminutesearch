# RecSportsDB Parking Lot

**Last Updated:** 2026-02-12  
**Project Status:** Active Development
**Primary Developer:** User (with Claude Code)

---

## Historical Tracking (FUTURE)

**Objective:** Year-over-year analysis, pricing trends  

### Changes Required

- Split `league_id` into:
  - `leagues` (stable)
  - `league_seasons` (instances)
- Add `league_season_id` to schema  
- Historical price tracking table  
- Change detection on re-scrape  

### Enables

- “How has TSSC summer soccer pricing changed 2023→2024?”  
- “Which leagues have grown/shrunk in team count?”  
- “Seasonal trends in market pricing”  

**Dependencies:** Phase 4 complete, proven analytics value  

---

## Venue Normalization (FUTURE)

**Objective:** Venue-level analytics, capacity planning  

### Changes Required

- Create `venues` table  
- Migrate `venue_name` → `venue_id` (FK)  
- AI-assisted venue matching (address, name variants)  
- Human data entry for availability, cost  

### Enables

- “Which venues are underutilized on Tuesdays?”  
- “Optimal venue selection for new league”  
- “Venue cost-per-hour comparison”  

**Dependencies:** Phase 4 complete, venue data collection strategy  

---

## Multi-Agent Query System (FUTURE)

**Objective:** Natural language analytics interface  

### Architecture

- **Supervisor Agent** — query router  
- **Financial Agent** — pricing analysis  
- **Scheduling Agent** — date/time patterns  
- **Rules & Vibe Agent** — RAG queries  

### Enables

- “Find the best value volleyball league in Toronto on weeknights with a casual vibe”  
- “Compare pricing strategies across top 5 orgs”  
- “What are typical co-ed roster requirements?”  

**Dependencies:** Clean data (`quality_score` ≥ 70 avg), proven query patterns  

## Scheduling Tools (FUTURE)

### Future Capabilities

#### Constraint Satisfaction Scheduling

- Venue availability matching  
- Referee assignment  
- Blackout dates (holidays, venue exceptions)  
- Double-header detection  

#### Rescheduling Engine

- Find alternative dates/venues  
- Minimize conflicts  
- Notify affected teams  

#### Capacity Planning

- Optimal league sizing (teams per league)  
- Venue utilization optimization  
- Multi-sport venue sharing  

**Dependencies:** `venue_id` normalization, historical data, proven demand  

## Parking Lot Simple

- **leagues_metadata viewer page** — Streamlit page to browse/filter the leagues_metadata table (sport, org, status, quality score, etc.)
- **Automated venue phone calls for availability**
- **Direct API integrations with major orgs (TSSC, Volo, etc.)**
- **Real-time web scraping (monitor for schedule changes)**
- **User-submitted league data**
- **Mobile app for league search**