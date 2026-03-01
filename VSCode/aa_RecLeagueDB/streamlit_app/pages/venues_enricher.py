"""Venues Enricher — trigger enrichment and review low-confidence results."""

import os
import streamlit as st
from src.database.supabase_client import get_client
from src.database.venue_store import VenueStore
from src.enrichers.places_client import PlacesClient
from src.enrichers.venue_enricher import VenueEnricher


def _get_enricher() -> VenueEnricher:
    client = get_client()
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        st.error("GOOGLE_PLACES_API_KEY not set in .env")
        st.stop()
    return VenueEnricher(
        places_client=PlacesClient(api_key=api_key),
        venue_store=VenueStore(client=client),
    )


def _get_store() -> VenueStore:
    return VenueStore(client=get_client())


def render():
    st.title("📍 Venues Enricher")
    st.markdown("Resolve venue names to structured addresses via Google Places API.")

    store = _get_store()
    stats = store.get_enrichment_stats()

    # ── Stats panel ──────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Venues", stats["total"])
    col2.metric("Enriched", stats["enriched"])
    col3.metric("Pending", stats["pending"])
    col4.metric("Needs Review", stats["needs_review"])

    st.divider()

    # ── Trigger enrichment ───────────────────────────────────────
    if stats["pending"] == 0:
        st.success("All venues are enriched.")
    else:
        st.info(f"{stats['pending']} venue(s) pending enrichment.")
        if st.button("▶ Run Enrichment", type="primary"):
            enricher = _get_enricher()
            progress_bar = st.progress(0)
            status_text = st.empty()

            def on_progress(current, total):
                progress_bar.progress((current + 1) / total)
                status_text.text(f"Processing {current + 1} of {total}...")

            with st.spinner("Running..."):
                summary = enricher.run(progress_callback=on_progress)

            progress_bar.empty()
            status_text.empty()
            st.success(
                f"Done — {summary['auto_saved']} auto-saved, "
                f"{summary['queued_review']} queued for review, "
                f"{summary['failed']} failed (no result)."
            )
            st.rerun()

    # ── Review queue ─────────────────────────────────────────────
    st.subheader("Review Queue")
    queue = store.get_review_queue()

    if not queue:
        st.write("No items to review.")
        return

    for venue in queue:
        conf = venue.get("confidence_score", 0)
        label = f"**{venue['venue_name']}**, {venue.get('city', '?')} — confidence: {conf}/100"

        with st.expander(label):
            st.write(f"**Returned address:** {venue.get('address', 'N/A')}")
            if venue.get("lat") and venue.get("lng"):
                maps_url = (
                    f"https://www.google.com/maps/search/?api=1"
                    f"&query={venue['lat']},{venue['lng']}"
                )
                st.markdown(f"[Open in Google Maps ↗]({maps_url})")
            st.write(f"**Google Place ID:** {venue.get('google_place_id', 'N/A')}")

            col_a, col_b, col_c = st.columns(3)

            with col_a:
                if st.button("✓ Accept", key=f"accept_{venue['venue_id']}"):
                    store.accept_venue(venue["venue_id"])
                    store.link_leagues(venue["venue_id"], venue["venue_name"], venue.get("city", ""))
                    st.rerun()

            with col_b:
                new_address = st.text_input(
                    "Corrected address",
                    value=venue.get("address", ""),
                    key=f"edit_{venue['venue_id']}",
                )
                if st.button("💾 Save edit", key=f"save_{venue['venue_id']}"):
                    store.update_venue_address(venue["venue_id"], new_address, None, None)
                    store.link_leagues(venue["venue_id"], venue["venue_name"], venue.get("city", ""))
                    st.rerun()

            with col_c:
                if st.button("⏭ Skip", key=f"skip_{venue['venue_id']}"):
                    st.rerun()
