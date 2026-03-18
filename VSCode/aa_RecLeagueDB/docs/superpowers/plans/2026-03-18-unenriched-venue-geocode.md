# Unenriched Venue Address Geocoding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user enters an address for an unenriched venue, a "Resolve Address" button geocodes it via Google Places API and shows a read-only preview (google_name, formatted_address, lat, lng, place_id) before the user saves.

**Architecture:** Two-step flow entirely in `_render_unenriched_tab`. Address input and "Resolve Address" button live outside `st.form` so they can trigger a rerun. Resolved result is stored in `st.session_state[f"resolved_{name}"]`. If Places returns a result, a confirmation form shows google_name (editable) and "Save & Link Leagues". If Places returns nothing, manual lat/lng/place_id fields appear as fallback. League linking uses the original `venue_name` string — unaffected by the resolved address.

**Tech Stack:** Python 3.10+, Streamlit, `PlacesClient` (already in `src/enrichers/places_client.py`)

---

## File Map

| File | Change |
|------|--------|
| `streamlit_app/pages/venues_enricher.py` | Add `_get_places_client()` helper; refactor `_render_unenriched_tab` to two-step resolve + save flow |

No new DB methods. No new tests (UI code; `PlacesClient` is already tested separately).

---

## Context You Must Read First

Before touching any code, read these files:

- `streamlit_app/pages/venues_enricher.py` — full current page. Focus on `_render_unenriched_tab` and `_get_venue_enricher`.
- `src/enrichers/places_client.py` — `PlacesClient.search(venue_name, city=None)` accepts any text query (including an address string) and returns a normalized dict with keys: `place_id`, `name`, `formatted_address`, `lat`, `lng`, `types`, `user_ratings_total`, `raw`. Returns `None` if no result.
- `src/database/venue_store.py` — `save_venue()` signature, `toggle_verified()`, `link_leagues()`. League linking is by `venue_name` string, not address.

---

## Task 1: Add `_get_places_client()` helper

**Files:**
- Modify: `streamlit_app/pages/venues_enricher.py`

- [ ] **Step 1: Add the helper function**

Add this function after `_get_store()` in `streamlit_app/pages/venues_enricher.py`:

```python
def _get_places_client() -> PlacesClient:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        st.error("GOOGLE_PLACES_API_KEY not set in .env")
        st.stop()
    return PlacesClient(api_key=api_key)
```

- [ ] **Step 2: Confirm `PlacesClient` is already imported**

Check the import block at the top of `venues_enricher.py`. It should already import `PlacesClient` via `_get_venue_enricher`. If not, add:

```python
from src.enrichers.places_client import PlacesClient
```

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/venues_enricher.py
git commit -m "feat: add _get_places_client helper to venues_enricher"
```

---

## Task 2: Refactor `_render_unenriched_tab` to two-step resolve + save

Replace the current `_render_unenriched_tab` body with the two-step flow.

**Files:**
- Modify: `streamlit_app/pages/venues_enricher.py`

- [ ] **Step 1: Replace `_render_unenriched_tab` with the new implementation**

Replace the entire function body (everything inside `def _render_unenriched_tab(store: VenueStore) -> None:`) with:

```python
def _render_unenriched_tab(store: VenueStore) -> None:
    """Show unenriched venue names with a two-step resolve + save form."""
    venues = store.get_unenriched_with_counts()
    if not venues:
        st.success("All venue names have been enriched.")
        return

    st.caption(f"{len(venues)} venue name(s) pending enrichment, sorted by league count.")

    for item in venues:
        name = item["venue_name"]
        count = item["league_count"]
        with st.expander(f"{name}  ({count} league(s))", expanded=False):
            # ── League context ────────────────────────────────────
            leagues = store.get_leagues_for_venue_name(name)
            if leagues:
                st.markdown("**Leagues referencing this venue:**")
                for lg in leagues:
                    st.markdown(
                        f"- **{lg.get('sport_name', '?')}** · "
                        f"{lg.get('organization_name', '?')} · "
                        f"{lg.get('season_name', '?')} · "
                        f"{lg.get('day_of_week', '?')}"
                    )
            st.divider()

            # ── Step 1: Address input + Resolve button ────────────
            address = st.text_input("Address", key=f"addr_{name}")
            if st.button("Resolve Address", key=f"resolve_{name}"):
                if not address.strip():
                    st.error("Enter an address first.")
                else:
                    places = _get_places_client()
                    result = places.search(address.strip())
                    st.session_state[f"resolved_{name}"] = result  # None if no result

            # ── Step 2: Show result or fallback ──────────────────
            resolved_key = f"resolved_{name}"

            if resolved_key not in st.session_state:
                # Nothing resolved yet — nothing more to show
                pass

            elif st.session_state[resolved_key] is not None:
                # Happy path: Places returned a result
                r = st.session_state[resolved_key]
                st.success(
                    f"**Found:** {r['name']}  \n"
                    f"{r['formatted_address']}  \n"
                    f"Lat: {r['lat']}, Lng: {r['lng']}  \n"
                    f"Place ID: {r['place_id']}"
                )

                with st.form(key=f"confirm_{name}"):
                    google_name = st.text_input(
                        "Google Name (editable)", value=r["name"] or name
                    )
                    submitted = st.form_submit_button("Save & Link Leagues")

                if submitted:
                    venue_id = store.save_venue(
                        venue_name=name,
                        google_name=google_name.strip() or None,
                        address=r["formatted_address"],
                        lat=r["lat"],
                        lng=r["lng"],
                        google_place_id=r["place_id"],
                        confidence_score=100,
                        raw_api_response=r.get("raw", {}),
                    )
                    store.toggle_verified(venue_id, True)
                    linked = store.link_leagues(venue_id, name)
                    del st.session_state[resolved_key]
                    st.success(f"Saved and linked {linked} league(s).")
                    st.rerun()

            else:
                # No Places result — show manual fallback
                st.warning("No result found for that address. Enter coordinates manually.")

                with st.form(key=f"manual_{name}"):
                    google_name = st.text_input("Google Name (display label)", value=name)
                    col_lat, col_lng = st.columns(2)
                    lat = col_lat.number_input("Latitude", value=0.0, format="%.6f")
                    lng = col_lng.number_input("Longitude", value=0.0, format="%.6f")
                    place_id = st.text_input("Google Place ID (optional)")
                    submitted = st.form_submit_button("Save & Link Leagues")

                if submitted:
                    venue_id = store.save_venue(
                        venue_name=name,
                        google_name=google_name.strip() or None,
                        address=address.strip(),
                        lat=lat if lat != 0.0 else None,
                        lng=lng if lng != 0.0 else None,
                        google_place_id=place_id.strip() or None,
                        confidence_score=100,
                        raw_api_response={},
                    )
                    store.toggle_verified(venue_id, True)
                    linked = store.link_leagues(venue_id, name)
                    del st.session_state[resolved_key]
                    st.success(f"Saved and linked {linked} league(s).")
                    st.rerun()
```

- [ ] **Step 2: Verify manually in Streamlit**

Restart Docker or run `streamlit run streamlit_app/app.py` and navigate to Venues Enricher → Unenriched Venues tab.

Confirm:
- Each venue expander shows its associated leagues, then a divider, then an "Address" text input and "Resolve Address" button
- Entering a valid address and clicking "Resolve Address" shows a green success block with name, formatted_address, lat, lng, place_id, plus a "Google Name" text input (pre-filled) and "Save & Link Leagues" button
- Clicking "Save & Link Leagues" saves the venue and shows a success message with league count
- After saving, the venue disappears from the tab (cleared from session_state, rerun)
- Entering a nonsense/unresolvable address shows a warning and reveals manual lat/lng/place_id fields
- Manual save path also works end-to-end

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/venues_enricher.py
git commit -m "feat: unenriched venues — two-step address resolve via Google Places"
```

---

## Task 3: Push

- [ ] **Step 1: Push**

```bash
git push
```
