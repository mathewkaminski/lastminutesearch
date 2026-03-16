# SSS Codes - Sport & Season Classification

**Format:** XYY (3 digits)
- **X** = Seasonality (1st digit)
- **YY** = Sport Code (last 2 digits)

**Purpose:** Standardized classification system for filtering and analyzing leagues

**Example:** `201` = Summer Soccer (2=Summer, 01=Soccer)

---

## Seasonality Codes (First Digit)

| Code | Season | Description |
|------|--------|-------------|
| 1 | Spring | March-May leagues |
| 2 | Summer | June-August leagues |
| 3 | Fall | September-November leagues |
| 4 | Winter | December-February leagues |
| 5 | Spring/Summer | Cross-season (March-August) |
| 6 | Fall/Winter | Cross-season (September-February) |
| 7 | Tournaments | One-time events, not seasonal |
| 8 | Youth | Under 18 programs (excluded from RecSportsDB) |
| 9 | Other | Multi-season, year-round, or undefined |

---

## Sport Codes (Last Two Digits)

### Field Sports
| Code | Sport |
|------|-------|
| 01 | Soccer (Outdoor) |
| 02 | Flag Football |
| 03 | Ultimate Frisbee |
| 04 | Rugby |
| 05 | Lacrosse |
| 06 | Cricket |
| 07 | Kickball |
| 08 | Field Hockey |

### Court Sports (Indoor)
| Code | Sport |
|------|-------|
| 10 | Basketball |
| 11 | Volleyball (Indoor) |
| 12 | Badminton |
| 13 | Pickleball |
| 14 | Squash |
| 15 | Racquetball |
| 16 | Table Tennis (Ping Pong) |

### Court Sports (Outdoor)
| Code | Sport |
|------|-------|
| 20 | Beach Volleyball |
| 21 | Tennis |
| 22 | Pickleball (Outdoor) |

### Ice/Rink Sports
| Code | Sport |
|------|-------|
| 30 | Ice Hockey |
| 31 | Broomball |
| 32 | Curling |
| 33 | Figure Skating |
| 34 | Speed Skating |
| 35 | Roller Hockey (Inline) |

### Diamond Sports
| Code | Sport |
|------|-------|
| 40 | Baseball |
| 41 | Softball (Slow Pitch) |
| 42 | Softball (Fast Pitch) |
| 43 | Wiffle Ball |

### Indoor Alternative Sports
| Code | Sport |
|------|-------|
| 50 | Dodgeball |
| 51 | Indoor Soccer (Futsal) |
| 52 | Floor Hockey |
| 53 | Handball |
| 54 | Cornhole |
| 55 | Darts |
| 56 | Bowling |
| 57 | Axe Throwing |

### Water Sports
| Code | Sport |
|------|-------|
| 60 | Swimming |
| 61 | Water Polo |
| 62 | Dragon Boat |
| 63 | Kayaking |
| 64 | Stand-Up Paddleboarding (SUP) |

### Fitness/Combat Sports
| Code | Sport |
|------|-------|
| 70 | Boxing |
| 71 | Kickboxing |
| 72 | Brazilian Jiu-Jitsu |
| 73 | Wrestling |
| 74 | Martial Arts (Mixed) |
| 75 | CrossFit |
| 76 | Bootcamp |

### Individual/Running Sports
| Code | Sport |
|------|-------|
| 80 | Running Club |
| 81 | Triathlon |
| 82 | Cycling |
| 83 | Track & Field |

### Other/Multi-Sport
| Code | Sport |
|------|-------|
| 90 | Multi-Sport Social League |
| 91 | Yard Games (Mixed) |
| 92 | Esports |
| 93 | Chess |
| 94 | Poker League |
| 99 | Other/Unclassified |

---

## Usage Examples

### Example 1: Summer Soccer
**SSS Code:** `201`
- Seasonality: 2 (Summer)
- Sport: 01 (Soccer)

### Example 2: Winter Hockey
**SSS Code:** `430`
- Seasonality: 4 (Winter)
- Sport: 30 (Ice Hockey)

### Example 3: Fall Volleyball
**SSS Code:** `311`
- Seasonality: 3 (Fall)
- Sport: 11 (Volleyball - Indoor)

### Example 4: Tournament Kickball
**SSS Code:** `707`
- Seasonality: 7 (Tournament)
- Sport: 07 (Kickball)

### Example 5: Year-Round Dodgeball
**SSS Code:** `950`
- Seasonality: 9 (Other/Multi-season)
- Sport: 50 (Dodgeball)

---

## Filtering Queries

### All Summer Leagues
```sql
SELECT * FROM leagues_metadata
WHERE sport_season_code LIKE '2%';
```

### All Soccer Leagues
```sql
SELECT * FROM leagues_metadata
WHERE sport_season_code LIKE '%01';
```

### Summer Soccer Only
```sql
SELECT * FROM leagues_metadata
WHERE sport_season_code = '201';
```

### Indoor Court Sports (Basketball, Volleyball, Badminton)
```sql
SELECT * FROM leagues_metadata
WHERE sport_season_code LIKE '%1_'
   OR sport_season_code LIKE '%10'
   OR sport_season_code LIKE '%11'
   OR sport_season_code LIKE '%12';
```

---

## Code Assignment Guidelines

### Ambiguous Seasons
- If league spans multiple seasons (e.g., April-September): Use code 5 (Spring/Summer)
- If season is unclear from website: Use code 9 (Other)

### Ambiguous Sports
- If multi-sport league (rotating sports): Use code 90 (Multi-Sport Social League)
- If sport is variant of listed sport (e.g., "Footgolf"): Map to closest match (01 = Soccer)
- If completely new sport: Use code 99 (Other) and document

### Indoor vs Outdoor
- Volleyball Indoor = 11, Beach Volleyball = 20
- Soccer Outdoor = 01, Indoor Soccer/Futsal = 51
- Pickleball Indoor = 13, Outdoor = 22

---

## Maintaining SSS Codes

**Adding new sports:**
1. Propose new code in unused range
2. Update this document
3. Update `src/config/sss_codes.py`
4. Document in changelog

**Deprecating codes:**
- Do NOT reuse deprecated codes (breaks historical data)
- Mark as DEPRECATED in comments
- Map old code to new code in migration scripts

---

## Python Mapping

**Location:** `src/config/sss_codes.py`

**Usage:**
```python
from src.config import sss_codes

# Get sport name from code
sport = sss_codes.get_sport_name('01')  # Returns "Soccer"

# Get season name from code
season = sss_codes.get_season_name('2')  # Returns "Summer"

# Build full code
code = sss_codes.build_sss_code('Summer', 'Soccer')  # Returns "201"

# Validate code
is_valid = sss_codes.validate_sss_code('201')  # Returns True
```

---

## Data Quality Notes

**Common extraction errors:**
- Confusing sport variants (Soccer vs Futsal)
- Missing season info (defaults to 9)
- Tournament vs league confusion (7 vs 1-6)

**Validation checks:**
- First digit must be 1-9
- Last two digits must be 01-99
- Code must exist in canonical list

---

**Source of Truth:** This document (`docs/SSS_CODES.md`)  
**Last Updated:** 2026-02-12  
**Legacy Reference:** https://docs.google.com/document/d/1BKZCkjD7eKZuHN_gWaU1toaKWoCDLQ2K3jOojW72IYw/edit
