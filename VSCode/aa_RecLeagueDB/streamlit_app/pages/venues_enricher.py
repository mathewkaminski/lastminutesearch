"""Venues Enricher — enrich, classify, and review venue records."""

import os
import pandas as pd
import streamlit as st
from anthropic import Anthropic
from src.database.supabase_client import get_client
from src.database.venue_store import VenueStore
from src.enrichers.places_client import PlacesAPIError, PlacesClient
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


def _get_places_client() -> PlacesClient:
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        st.error("GOOGLE_PLACES_API_KEY not set in .env")
        st.stop()
    return PlacesClient(api_key=api_key)


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


def _render_venue_expanders(store: VenueStore, venues: list[dict]) -> None:
    """Render one st.expander per venue with league details, stats, and verified toggle."""
    venue_ids = [v["venue_id"] for v in venues]
    league_stats = store.get_league_stats_for_venues(venue_ids)

    for v in venues:
        vid = v["venue_id"]
        verified = v.get("manually_verified", False)
        verified_icon = "✓" if verified else "○"
        stats = league_stats.get(vid, {})
        n_leagues = stats.get("num_leagues", 0)
        conf = v.get("confidence_score", 0)

        label = (
            f"{verified_icon}  {v.get('google_name') or v.get('venue_name')}  "
            f"· {v.get('city', '')} {v.get('province', '')}  "
            f"· {n_leagues} league(s)  · conf {conf}"
        )

        with st.expander(label, expanded=False):
            col_info, col_actions = st.columns([3, 1])

            with col_info:
                st.caption(f"**Address:** {v.get('address', '—')}")
                if v.get("court_type_broad"):
                    st.caption(
                        f"**Court:** {v['court_type_broad']} / {v.get('court_type_specific', '—')}"
                    )
                sports_str = (
                    ", ".join(v["sports"]) if isinstance(v.get("sports"), list)
                    else (v.get("sports") or "—")
                )
                st.caption(f"**Sports:** {sports_str}")
                if stats.get("avg_team_fee") is not None:
                    st.caption(f"**Avg Team Fee:** ${stats['avg_team_fee']:.0f}")
                if stats.get("avg_individual_fee") is not None:
                    st.caption(f"**Avg Indiv. Fee:** ${stats['avg_individual_fee']:.0f}")
                if stats.get("hours"):
                    st.caption(f"**Hours:** {', '.join(stats['hours'])}")

            with col_actions:
                # Google Name editing
                new_name = st.text_input(
                    "Google Name",
                    value=v.get("google_name") or "",
                    key=f"gname_{vid}",
                )
                if st.button("Save Name", key=f"save_{vid}"):
                    if new_name.strip() != (v.get("google_name") or ""):
                        store.update_google_name(vid, new_name.strip() or None)
                        st.success("Saved.")
                        st.rerun()

                # Verified toggle
                btn_label = "Un-verify" if verified else "Mark Verified"
                if st.button(btn_label, key=f"verify_{vid}"):
                    store.toggle_verified(vid, not verified)
                    st.rerun()

            # League sub-list
            leagues = store.get_leagues_for_venue(vid)
            if leagues:
                st.markdown("**Leagues at this venue:**")
                for lg in leagues:
                    exclusions = ""
                    if lg.get("stat_holidays"):
                        dates = ", ".join(h.get("date", "") for h in lg["stat_holidays"])
                        exclusions = f" *(excl: {dates})*"
                    st.markdown(
                        f"- **{lg.get('sport_name', '?')}** · "
                        f"{lg.get('organization_name', '?')} · "
                        f"{lg.get('season_name', '?')} · "
                        f"{lg.get('day_of_week', '?')}"
                        f"{exclusions}"
                    )
            else:
                st.caption("No leagues linked yet.")


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

    fc1, fc2, fc3, fc4, fc5, fc6 = st.columns([1, 1, 1, 1, 1, 1])
    broad_filter = fc1.selectbox("Broad Type", broad_options, key="f_broad")
    specific_filter = fc2.selectbox("Specific Type", specific_options, key="f_specific")
    province_filter = fc3.selectbox("Province", province_options, key="f_province")
    city_filter = fc4.text_input("City", key="f_city")
    sport_filter = fc5.selectbox("Sport", sport_options, key="f_sport")
    season_filter = fc6.text_input("Season", key="f_season")

    venues = store.get_enriched_venues(
        broad=broad_filter or None,
        specific=specific_filter or None,
        province=province_filter or None,
        city=city_filter.strip() or None,
        sport=sport_filter or None,
        season=season_filter.strip() or None,
    )

    if not venues:
        st.write("No venues match the current filters.")
        return

    st.caption(f"{len(venues)} venue(s) shown")
    _render_venue_expanders(store, venues)


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
                    try:
                        result = places.search(address.strip())
                    except PlacesAPIError as e:
                        st.error(f"Google Places API error: {e}")
                        result = None
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
    tab_all, tab_enriched, tab_unenriched = st.tabs(["All Venues", "Enriched Venues", "Unenriched Venues"])

    with tab_all:
        _render_all_venues(store)

    with tab_enriched:
        _render_enriched_venues(store)

    with tab_unenriched:
        _render_unenriched_tab(store)
