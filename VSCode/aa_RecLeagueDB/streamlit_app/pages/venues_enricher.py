"""Venues Enricher — trigger enrichment and review/edit venue records."""

import os
import pandas as pd
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

    # ── Venues table ─────────────────────────────────────────────
    st.subheader("All Venues")
    venues = store.get_all_venues()

    if not venues:
        st.write("No venues yet.")
        return

    df = pd.DataFrame(venues)

    # Convert list columns to comma-separated strings for display
    for col in ("sports", "days_of_week"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: ", ".join(v) if isinstance(v, list) else (v or "")
            )

    edited = st.data_editor(
        df,
        column_config={
            "venue_id": None,  # hidden — used for save logic only
            "venue_name": st.column_config.TextColumn("Scraped Name", disabled=True),
            "google_name": st.column_config.TextColumn("Google Name", width="medium"),
            "city": st.column_config.TextColumn("City", disabled=True, width="small"),
            "province": st.column_config.TextColumn("Prov.", disabled=True, width="small"),
            "address": st.column_config.TextColumn("Address", disabled=True, width="large"),
            "confidence_score": st.column_config.NumberColumn("Conf.", disabled=True, width="small"),
            "manually_verified": st.column_config.CheckboxColumn("Verified", disabled=True, width="small"),
            "sports": st.column_config.TextColumn("Sports", disabled=True, width="medium"),
            "days_of_week": st.column_config.TextColumn("Days", disabled=True, width="medium"),
        },
        hide_index=True,
        use_container_width=True,
        key="venues_table",
    )

    if st.button("💾 Save Name Changes"):
        orig = df.set_index("venue_id")["google_name"]
        updated = edited.set_index("venue_id")["google_name"]
        changed = orig[orig != updated].index.tolist()
        if changed:
            for vid in changed:
                store.update_google_name(vid, updated[vid] or None)
            st.success(f"Saved {len(changed)} name change(s).")
            st.rerun()
        else:
            st.info("No changes detected.")
