"""Venues Enricher — enrich, classify, and review venue records."""

import os
import pandas as pd
import streamlit as st
from anthropic import Anthropic
from src.database.supabase_client import get_client
from src.database.venue_store import VenueStore
from src.enrichers.places_client import PlacesClient
from src.enrichers.venue_enricher import VenueEnricher
from src.enrichers.court_type_classifier import CourtTypeClassifier
from src.enrichers.court_type_enricher import CourtTypeEnricher


def _get_venue_enricher() -> VenueEnricher:
    client = get_client()
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        st.error("GOOGLE_PLACES_API_KEY not set in .env")
        st.stop()
    return VenueEnricher(
        places_client=PlacesClient(api_key=api_key),
        venue_store=VenueStore(client=client),
    )


def _get_court_enricher() -> CourtTypeEnricher:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("ANTHROPIC_API_KEY not set in .env")
        st.stop()
    return CourtTypeEnricher(
        classifier=CourtTypeClassifier(client=Anthropic(api_key=api_key)),
        venue_store=VenueStore(client=get_client()),
    )


def _get_store() -> VenueStore:
    return VenueStore(client=get_client())


def _render_all_venues(store: VenueStore) -> None:
    venues = store.get_all_venues()
    if not venues:
        st.write("No venues yet.")
        return

    df = pd.DataFrame(venues)
    for col in ("sports", "days_of_week"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: ", ".join(v) if isinstance(v, list) else (v or "")
            )

    edited = st.data_editor(
        df,
        column_config={
            "venue_id": None,
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
        key="all_venues_table",
    )

    if st.button("💾 Save Name Changes", key="save_all"):
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


def _render_enriched_venues(store: VenueStore) -> None:
    # ── Classify button ───────────────────────────────────────────
    unclassified = store.get_venues_for_classification()
    total_enriched = len(store.get_enriched_venues())
    classified_count = total_enriched - len(unclassified)

    st.caption(f"{classified_count} of {total_enriched} venues classified")

    if unclassified:
        st.info(f"{len(unclassified)} venue(s) not yet classified.")
        if st.button("▶ Classify Court Types", type="primary"):
            enricher = _get_court_enricher()
            progress_bar = st.progress(0)
            status_text = st.empty()

            def on_progress(current, total):
                progress_bar.progress((current + 1) / total)
                status_text.text(f"Classifying {current + 1} of {total}...")

            with st.spinner("Running..."):
                summary = enricher.run(progress_callback=on_progress)

            progress_bar.empty()
            status_text.empty()
            st.success(
                f"Done — {summary['classified']} classified, {summary['failed']} failed."
            )
            st.rerun()

    st.divider()

    # ── Filters ───────────────────────────────────────────────────
    all_venues = store.get_enriched_venues()
    if not all_venues:
        st.write("No enriched venues yet.")
        return

    df_all = pd.DataFrame(all_venues)

    broad_options = [""] + sorted(df_all["court_type_broad"].dropna().unique().tolist())
    specific_options = [""] + sorted(df_all["court_type_specific"].dropna().unique().tolist())
    province_options = [""] + sorted(df_all["province"].dropna().unique().tolist())
    sport_options = [""] + sorted({
        s for row in df_all["sports"].dropna()
        for s in (row if isinstance(row, list) else row.split(", "))
        if s
    })

    fc1, fc2, fc3, fc4, fc5 = st.columns([1, 1, 1, 1, 1])
    broad_filter = fc1.selectbox("Broad Type", broad_options, key="f_broad")
    specific_filter = fc2.selectbox("Specific Type", specific_options, key="f_specific")
    province_filter = fc3.selectbox("Province", province_options, key="f_province")
    city_filter = fc4.text_input("City", key="f_city")
    sport_filter = fc5.selectbox("Sport", sport_options, key="f_sport")

    venues = store.get_enriched_venues(
        broad=broad_filter or None,
        specific=specific_filter or None,
        province=province_filter or None,
        city=city_filter.strip() or None,
        sport=sport_filter or None,
    )

    if not venues:
        st.write("No venues match the current filters.")
        return

    # ── League stats ──────────────────────────────────────────────
    venue_ids = [v["venue_id"] for v in venues]
    league_stats = store.get_league_stats_for_venues(venue_ids)

    df = pd.DataFrame(venues)
    df["# Leagues"] = df["venue_id"].map(lambda vid: league_stats.get(vid, {}).get("num_leagues", 0))
    df["Avg Team Fee"] = df["venue_id"].map(lambda vid: league_stats.get(vid, {}).get("avg_team_fee"))
    df["Avg Indiv. Fee"] = df["venue_id"].map(lambda vid: league_stats.get(vid, {}).get("avg_individual_fee"))
    df["Hours"] = df["venue_id"].map(
        lambda vid: ", ".join(league_stats.get(vid, {}).get("hours", []))
    )

    for col in ("sports", "days_of_week"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: ", ".join(v) if isinstance(v, list) else (v or "")
            )

    st.caption(f"{len(df)} venue(s) shown")

    edited = st.data_editor(
        df,
        column_config={
            "venue_id": None,
            "venue_name": None,
            "manually_verified": None,
            "google_name": st.column_config.TextColumn("Google Name", width="medium"),
            "city": st.column_config.TextColumn("City", disabled=True, width="small"),
            "province": st.column_config.TextColumn("Prov.", disabled=True, width="small"),
            "address": st.column_config.TextColumn("Address", disabled=True, width="large"),
            "confidence_score": st.column_config.NumberColumn("Conf.", disabled=True, width="small"),
            "court_type_broad": st.column_config.TextColumn("Broad", disabled=True, width="small"),
            "court_type_broad_conf": st.column_config.NumberColumn("B.Conf", disabled=True, width="small"),
            "court_type_specific": st.column_config.TextColumn("Specific", disabled=True, width="medium"),
            "court_type_specific_conf": st.column_config.NumberColumn("S.Conf", disabled=True, width="small"),
            "sports": st.column_config.TextColumn("Sports", disabled=True, width="medium"),
            "days_of_week": st.column_config.TextColumn("Days", disabled=True, width="medium"),
            "# Leagues": st.column_config.NumberColumn("# Leagues", disabled=True, width="small"),
            "Avg Team Fee": st.column_config.NumberColumn("Avg Team $", disabled=True, format="$%.0f", width="small"),
            "Avg Indiv. Fee": st.column_config.NumberColumn("Avg Indiv. $", disabled=True, format="$%.0f", width="small"),
            "Hours": st.column_config.TextColumn("Hours", disabled=True, width="medium"),
        },
        hide_index=True,
        use_container_width=True,
        key="enriched_venues_table",
    )

    if st.button("💾 Save Name Changes", key="save_enriched"):
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

    # ── Trigger address enrichment ────────────────────────────────
    if stats["pending"] == 0:
        st.success("All venues are enriched.")
    else:
        st.info(f"{stats['pending']} venue(s) pending enrichment.")
        if st.button("▶ Run Enrichment", type="primary"):
            enricher = _get_venue_enricher()
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

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────
    tab_all, tab_enriched = st.tabs(["All Venues", "Enriched Venues"])

    with tab_all:
        _render_all_venues(store)

    with tab_enriched:
        _render_enriched_venues(store)
