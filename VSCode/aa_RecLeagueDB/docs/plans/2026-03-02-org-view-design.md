# Design: Organization View — Domain Grouping & Listing Type Classification

**Date:** 2026-03-02
**Status:** Approved
**Author:** User + Claude Code

---

## Problem

The League Checker shows every scraped URL as a flat list. A single company like Javelin can produce 20+ URLs (one per city/sport/page), making it hard to see the full picture of what was scraped per organization. Additionally, there is no distinction between multi-week leagues (true "leagues") and one-off drop-in games — both appear as league records in the DB.

---

## Goals

1. **Group URLs by organization** (base domain) so Javelin's 20 URLs appear as one collapsible group.
2. **Classify each record** as `league`, `drop_in`, or `unknown` using heuristics, with manual override in the UI.
3. **Manual grouping override** — ability to rename a domain group or merge two domain groups.

---

## Approach: Two Columns on `leagues_metadata` (Approach B)

Add `base_domain` and `listing_type` directly to `leagues_metadata`. Group by `base_domain` in a new Streamlit page. Classification runs at insert time going forward; a backfill script handles existing records.

---

## Data Model

### Migration: `migrations/004_add_domain_and_listing_type.sql`

```sql
ALTER TABLE leagues_metadata
  ADD COLUMN base_domain  TEXT,
  ADD COLUMN listing_type TEXT DEFAULT 'unknown'
    CHECK (listing_type IN ('league', 'drop_in', 'unknown'));

CREATE INDEX idx_leagues_base_domain  ON leagues_metadata(base_domain);
CREATE INDEX idx_leagues_listing_type ON leagues_metadata(listing_type);
```

- **`base_domain`** — extracted from `url_scraped` (e.g. `"javelin.com"`). Can be manually overridden per domain group.
- **`listing_type`** — `'league'` | `'drop_in'` | `'unknown'`. Set by classifier; overrideable in UI.

---

## Listing Type Classifier

### Module: `src/utils/listing_classifier.py`

```python
def classify_listing_type(record: dict) -> str:
    """Returns 'drop_in', 'league', or 'unknown'."""
```

Rules applied in order (first match wins):

| Priority | Signal | Result |
|----------|--------|--------|
| 1 | Keywords in `league_name` or `division_name`: `drop.?in`, `pick.?up`, `one.?time`, `casual`, `social night`, `open play` | `drop_in` |
| 2 | `num_weeks` is 1 or NULL **and** `individual_fee` < 20 (when present) | `drop_in` |
| 3 | `num_weeks` >= 4 **or** `team_fee` > 0 | `league` |
| 4 | No signals match | `unknown` |

### Module: `src/utils/domain_extractor.py`

```python
def extract_base_domain(url: str) -> str:
    """Returns e.g. 'javelin.com' from any URL under that domain."""
```

Uses `urllib.parse.urlparse` — strips scheme, `www.`, and path.

---

## Integration Points

### `src/database/writer.py`
Call classifier and domain extractor at insert time so all new records are classified on arrival.

### `scripts/backfill_listing_type.py`
One-time script to classify existing records:
- Fetches all records where `listing_type = 'unknown'` OR `base_domain IS NULL`
- Runs classifier + domain extractor on each
- Bulk-updates in batches of 100
- Prints summary: `X classified as league, Y as drop_in, Z remain unknown`

---

## Organization View Page

### File: `streamlit_app/pages/org_view.py`

**Layout:**
```
Organization View
─────────────────────────────────────────────────
[Summary: X orgs | Y URLs | Z drop-ins flagged]

[Search: filter by org name or domain]
[Filter: All | Leagues only | Drop-ins only | Unknown]

▶ javelin.com  (20 URLs)   League ████████ 18   Drop-in ██ 2
   ▼ expand
     ├─ javelin.com/calgary-vball  →  4 leagues  [League ✅]  [Edit]
     ├─ javelin.com/calgary-games  →  2 entries  [Drop-in 🎯]  [Edit]
     └─ ...

▶ torontossc.com  (5 URLs)  League █████ 5
   ...
```

**Interactions:**
- **Expand/collapse** each org group to see individual URLs and listing types
- **[Edit] on a URL row** — inline selectbox to change `listing_type` for all records at that URL; writes to DB
- **[Rename domain group]** — text input to change `base_domain` for all records under that domain (manual grouping override)
- **Merge two domains** — select two domain groups; reassigns one group's `base_domain` to match the other

### Navigation: `streamlit_app/app.py`
Add "Org View" to the page navigation.

---

## Files Changed

| File | Type | Description |
|------|------|-------------|
| `migrations/004_add_domain_and_listing_type.sql` | New | Two columns + indexes |
| `src/utils/listing_classifier.py` | New | Rule-based classifier |
| `src/utils/domain_extractor.py` | New | URL → base domain |
| `src/database/writer.py` | Modified | Call classifier + extractor at insert |
| `scripts/backfill_listing_type.py` | New | One-time backfill |
| `streamlit_app/pages/org_view.py` | New | Organization View page |
| `streamlit_app/app.py` | Modified | Add Org View to nav |

---

## Future Work (Parking Lot)

- **League merge tool within Org View**: if two records at the same URL appear to be duplicates (same division after a name change), rename one and merge them. This would reuse/extend the existing `merge_tool.py` patterns.

---

## Success Criteria

- [ ] All existing records get `base_domain` populated by backfill
- [ ] Classifier correctly identifies drop-ins in test dataset (manual spot check)
- [ ] Org View groups Javelin's 20 URLs under `javelin.com`
- [ ] Rename domain group renames all records in one action
- [ ] Listing type edit persists across page refreshes
- [ ] New scraped records automatically get `base_domain` and `listing_type` set
